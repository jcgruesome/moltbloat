#!/usr/bin/env python3
"""List the instruction files Claude Code can load for a project, and how.

Load modes:
  always       loaded at session start: ~/.claude/CLAUDE.md, project and
               ancestor CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md,
               AGENTS.md, rules without `paths:` frontmatter, and the
               project's auto memory MEMORY.md
  path-scoped  rules with `paths:` frontmatter (load when a matching file
               is in play)
  lazy         CLAUDE.md in a subdirectory of the project (loads when Claude
               reads files there)
  imported     targets of `@path` references, resolved up to 4 hops

AGENTS.md is listed as `always` per the memory docs; the `observed` field
from --ledger-json says whether transcripts ever showed it loading. Paths
that resolve to the same file (e.g. AGENTS.md symlinked to CLAUDE.md) are
listed once. Imports carry `parent_load_mode`: an import from a lazy file is
lazy too.

Usage:
  python3 instruction-files.py --project DIR [--home DIR] [--ledger-json FILE] [--json]
"""
import json
import os
import re
import subprocess
import sys

MAX_IMPORT_HOPS = 4
MAX_LAZY_DEPTH = 6
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}

FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
IMPORT_RE = re.compile(r"(?<![\w@`])@((?:~/|\.{1,2}/|/)?[\w.\-/]+)")


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def rule_paths_frontmatter(text):
    """True / False for a `paths:` key in YAML frontmatter; None if unclosed."""
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return any(line.startswith("paths:") for line in text[3:end].splitlines())


def find_imports(text):
    """`@path` tokens outside fenced blocks and inline code, in order."""
    out = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in IMPORT_RE.finditer(INLINE_CODE_RE.sub("", line)):
            out.append(m.group(1).rstrip(".,;:)"))
    return out


def _looks_like_path(token):
    return token.startswith(("~/", "./", "../", "/")) or token.endswith(".md")


def resolve_imports(start_files, home):
    """Follow @imports from start_files, a list of (path, load_mode).

    Returns (imported, unresolved). imported: list of {path, imported_from,
    hop, parent_load_mode}. unresolved: list of {token, imported_from} for
    path-like tokens that do not exist. Tokens that are neither existing
    files nor path-like (e.g. `@scope/pkg`) are ignored.
    """
    seen = set(os.path.realpath(p) for p, _ in start_files)
    imported, unresolved = [], []
    frontier = [(p, 0, mode) for p, mode in start_files]
    while frontier:
        src, hop, mode = frontier.pop(0)
        if hop >= MAX_IMPORT_HOPS:
            continue
        for token in find_imports(_read(src)):
            if token.startswith("~/"):
                target = os.path.join(home, token[2:])
            elif token.startswith("/"):
                target = token
            else:
                target = os.path.join(os.path.dirname(src), token)
            target = os.path.normpath(target)
            if not os.path.isfile(target):
                if _looks_like_path(token):
                    unresolved.append({"token": "@" + token, "imported_from": src})
                continue
            real = os.path.realpath(target)
            if real in seen:
                continue
            seen.add(real)
            imported.append({"path": target, "imported_from": src, "hop": hop + 1,
                             "parent_load_mode": mode})
            frontier.append((target, hop + 1, mode))
    return imported, unresolved


def memory_root(project):
    """The main repository root for `project` (worktrees share it), or the
    project itself outside git."""
    out = subprocess.run(["git", "-C", project, "rev-parse", "--git-common-dir"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return os.path.realpath(project)
    common = out.stdout.strip()
    if not os.path.isabs(common):
        common = os.path.join(project, common)
    return os.path.dirname(os.path.realpath(common))


def encode_project_dir(path):
    """Claude Code's ~/.claude/projects directory name for a path: every
    non-alphanumeric character becomes '-' (verified against real dirs)."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def automem_path(home, project):
    """Claude Code's auto memory index for a project."""
    return os.path.join(home, ".claude", "projects", encode_project_dir(memory_root(project)),
                        "memory", "MEMORY.md")


def _rules(rules_dir, kind, warnings):
    out = []
    if not os.path.isdir(rules_dir):
        return out
    for root, _dirs, files in os.walk(rules_dir):
        for name in sorted(files):
            if name.endswith(".md"):
                p = os.path.join(root, name)
                scoped = rule_paths_frontmatter(_read(p))
                if scoped is None:
                    warnings.append(f"{p}: frontmatter is not closed; treated as always-loaded")
                mode = "path-scoped" if scoped else "always"
                out.append({"path": p, "kind": kind, "load_mode": mode})
    return out


def _lazy_claude_mds(project):
    out = []
    base_depth = project.rstrip("/").count("/")
    for root, dirs, files in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        if root.count("/") - base_depth >= MAX_LAZY_DEPTH:
            dirs[:] = []
        if root != project and "CLAUDE.md" in files:
            out.append({"path": os.path.join(root, "CLAUDE.md"), "kind": "nested", "load_mode": "lazy"})
    return out


def collect(project, home):
    """All instruction files for `project`, as dicts {path, kind, load_mode, ...}."""
    project = os.path.realpath(project)
    files, warnings, seen = [], [], set()

    def add_entry(entry):
        real = os.path.realpath(entry["path"])
        if real in seen:
            return
        seen.add(real)
        files.append(entry)

    def add(path, kind, mode="always"):
        if os.path.isfile(path):
            add_entry({"path": path, "kind": kind, "load_mode": mode})

    add(os.path.join(home, ".claude", "CLAUDE.md"), "user")
    # Claude Code reads CLAUDE.md in every ancestor up to, not including, "/".
    ancestors = []
    d = os.path.dirname(project)
    while d and d != os.path.dirname(d):
        ancestors.append(d)
        d = os.path.dirname(d)
    for anc in reversed(ancestors):
        add(os.path.join(anc, "CLAUDE.md"), "ancestor")
        add(os.path.join(anc, "CLAUDE.local.md"), "ancestor")
    add(os.path.join(project, "CLAUDE.md"), "project")
    add(os.path.join(project, ".claude", "CLAUDE.md"), "project")
    add(os.path.join(project, "CLAUDE.local.md"), "local")
    add(os.path.join(project, "AGENTS.md"), "agents")
    add(automem_path(home, project), "automem")
    for entry in (_rules(os.path.join(home, ".claude", "rules"), "user-rule", warnings)
                  + _rules(os.path.join(project, ".claude", "rules"), "project-rule", warnings)
                  + _lazy_claude_mds(project)):
        add_entry(entry)

    starts = [(f["path"], f["load_mode"]) for f in files]
    imported, unresolved = resolve_imports(starts, home)
    for imp in imported:
        add_entry({"path": imp["path"], "kind": "import", "load_mode": "imported",
                   "parent_load_mode": imp["parent_load_mode"],
                   "imported_from": imp["imported_from"], "hop": imp["hop"]})
    return {"project": project, "files": files, "unresolved_imports": unresolved, "warnings": warnings}


def mark_observed(result, ledger):
    """Set `observed` per file from a context-ledger --json result.

    True: seen loaded. False: an always-loaded file never seen across the
    ledger's instruction samples for this project. None: no samples.
    """
    inst = (ledger.get("sources") or {}).get("instructions")
    loaded = {os.path.realpath(f["path"]) for f in (inst or {}).get("files", [])}
    for f in result["files"]:
        if not inst:
            f["observed"] = None
        elif os.path.realpath(f["path"]) in loaded:
            f["observed"] = True
        else:
            always = f["load_mode"] == "always" or f.get("parent_load_mode") == "always"
            f["observed"] = False if always else None
    result["ledger_samples"] = (inst or {}).get("samples", 0)
    return result


def render_markdown(result):
    lines = ["# Instruction Files", "", f"Project: {result['project']}", "",
             "| File | Kind | Loads | Seen loaded |", "|---|---|---|---|"]
    for f in result["files"]:
        seen = {True: "yes", False: "no", None: "-"}[f.get("observed")]
        lines.append(f"| {f['path']} | {f['kind']} | {f['load_mode']} | {seen} |")
    for w in result.get("warnings", []):
        lines.append(f"Warning: {w}")
    if result["unresolved_imports"]:
        lines += ["", "## Unresolved imports", ""]
        lines += [f"- `{u['token']}` in {u['imported_from']}" for u in result["unresolved_imports"]]
    return "\n".join(lines)


def main(argv):
    opts = {"--project": None, "--home": os.path.expanduser("~"), "--ledger-json": None}
    as_json = False
    args = argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a in opts:
            i += 1
            if i >= len(args):
                sys.stderr.write(f"error: {a} requires a value\n")
                return 2
            opts[a] = args[i]
        else:
            sys.stderr.write(f"error: unknown argument {a}\n")
            return 2
        i += 1
    if not opts["--project"] or not os.path.isdir(opts["--project"]):
        sys.stderr.write(f"error: --project must be an existing directory (got {opts['--project']})\n")
        return 2
    result = collect(opts["--project"], opts["--home"])
    if opts["--ledger-json"]:
        with open(opts["--ledger-json"], encoding="utf-8") as f:
            mark_observed(result, json.load(f))
    print(json.dumps(result, indent=2) if as_json else render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
