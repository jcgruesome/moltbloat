#!/usr/bin/env python3
"""Measure the context each Claude Code session actually loaded.

Claude Code writes what it injected at session start into the transcript as
`attachment` records: the skill listing, deferred tool names, MCP server
instructions, the agent listing, SessionStart hook output, and the
instruction files (CLAUDE.md and friends) it loaded. This script reads those
records instead of estimating from file sizes.

These record shapes are undocumented internals verified on 2026-09-25. If no
known record type is found at all, the script fails rather than guessing.

Usage:
  python3 context-ledger.py [--projects-dir DIR] [--config-dir DIR]
                            [--samples N] [--max-sessions N]
                            [--tokens-per-byte F] [--include-sdk] [--json]
                            [--project PATH]

--project PATH restricts the `instructions` source (CLAUDE.md and friends)
to sessions whose recorded cwd is PATH or a subdirectory of it. All other
sources stay global (every sampled interactive session).
"""
import glob
import json
import os
import re
import statistics
import sys

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
CONFIG_DIR = os.path.expanduser("~/.claude")


def server_of(tool_name):
    """MCP server segment of a tool name, or "(built-in)" for non-MCP tools."""
    if tool_name.startswith("mcp__"):
        return tool_name[len("mcp__"):].split("__", 1)[0]
    return "(built-in)"


def hook_context_len(stdout):
    """Classify a SessionStart hook's stdout.

    Only JSON `hookSpecificOutput.additionalContext` is injected as context.
    Returns ("context", n), ("no_context", 0) for JSON without it (including
    empty stdout), or ("unparsed", 0) for non-JSON output.
    """
    if stdout == "":
        return ("no_context", 0)
    try:
        obj = json.loads(stdout)
    except (TypeError, ValueError):
        return ("unparsed", 0)
    if not isinstance(obj, dict):
        return ("unparsed", 0)
    hso = obj.get("hookSpecificOutput")
    ctx = hso.get("additionalContext") if isinstance(hso, dict) else None
    if isinstance(ctx, str):
        return ("context", len(ctx))
    return ("no_context", 0)


def _lines_chars(lines):
    return sum(len(x) + 1 for x in lines)


def _iter_attachments(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"attachment"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # truncated line in a live session
            a = obj.get("attachment") if isinstance(obj, dict) else None
            if isinstance(a, dict) and a.get("type"):
                yield a


def session_entrypoint(path):
    """The session's `entrypoint` (e.g. "cli", "sdk-cli"), or None if absent."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"entrypoint"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            ep = obj.get("entrypoint") if isinstance(obj, dict) else None
            if ep:
                return ep
    return None


def session_cwd(path):
    """The session's working directory: `cwd` of the first transcript line that has one."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"cwd"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            cwd = obj.get("cwd") if isinstance(obj, dict) else None
            if cwd:
                return cwd
    return None


def _aligned(a, keys_field, values_field, kind, path, errors):
    keys = a.get(keys_field) or []
    values = a.get(values_field) or []
    if len(keys) != len(values):
        errors.append(f"{kind}: {len(keys)} {keys_field} vs {len(values)} {values_field} in {path}")
        return []
    return list(zip(keys, values))


def extract_session(path):
    """Measure one main-session transcript (per-session rules in the plan)."""
    s = {"format_errors": [], "entrypoint": session_entrypoint(path), "cwd": session_cwd(path)}
    deferred, mcp, agents = {}, {}, {}
    hook_batch = None
    hooks = []
    for a in _iter_attachments(path):
        kind = a["type"]
        if kind == "skill_listing" and "skill_listing" not in s:
            content = a.get("content") or ""
            s["skill_listing"] = {"chars": len(content), "skill_count": a.get("skillCount"), "content": content}
        elif kind == "deferred_tools_delta":
            if "addedLines" not in a:
                s["format_errors"].append(f"deferred_tools_delta: missing addedLines in {path}")
                continue
            # Re-added names appear in addedNames but get no new line;
            # addedLines covers only the fresh names (verified on real
            # transcripts 2026-09-26). A tool's line is its name.
            readded = set(a.get("readdedNames") or [])
            fresh = [n for n in a.get("addedNames") or [] if n not in readded]
            deferred.update(_aligned({"addedNames": fresh, "addedLines": a["addedLines"]},
                                     "addedNames", "addedLines", kind, path, s["format_errors"]))
            for name in readded:
                deferred.setdefault(name, name)
        elif kind == "mcp_instructions_delta":
            mcp.update(_aligned(a, "addedNames", "addedBlocks", kind, path, s["format_errors"]))
        elif kind == "agent_listing_delta":
            agents.update(_aligned(a, "addedTypes", "addedLines", kind, path, s["format_errors"]))
        elif kind == "instructions" and "instructions" not in s:
            s["instructions"] = [
                {"path": f.get("path"), "type": f.get("type"), "chars": len(f.get("content") or "")}
                for f in a.get("files") or [] if isinstance(f, dict)
            ]
        elif (kind == "hook_additional_context" and "hook_merged" not in s
              and a.get("hookEvent") in (None, "SessionStart")):
            content = a.get("content")
            parts = content if isinstance(content, list) else [content or ""]
            s["hook_merged"] = {"chars": sum(len(x) for x in parts if isinstance(x, str))}
        elif kind == "hook_success" and a.get("hookEvent") == "SessionStart":
            if hook_batch is None:
                hook_batch = a.get("toolUseID")
            if a.get("toolUseID") != hook_batch:
                continue
            status, n = hook_context_len(a.get("stdout") or "")
            hooks.append({"command": a.get("command") or "", "status": status, "chars": n})
    if deferred:
        by_server = {}
        for name, line in deferred.items():
            srv = server_of(name)
            by_server[srv] = by_server.get(srv, 0) + len(line) + 1
        s["deferred_tools"] = {"chars": _lines_chars(deferred.values()), "names": len(deferred), "by_server": by_server}
    if mcp:
        by_server = {name: len(block) for name, block in mcp.items()}
        s["mcp_instructions"] = {"chars": sum(by_server.values()), "by_server": by_server}
    if agents:
        s["agent_listing"] = {"chars": _lines_chars(agents.values())}
    if hooks:
        s["hooks"] = hooks
    return s


SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+(:[A-Za-z0-9_.-]+)?$")


def parse_skill_listing(content):
    """[(name, listed_with_description)] for each `- name[: description]` line.

    Lines not starting with `- `, or whose name is not a valid skill name, are
    description continuations and are skipped.
    """
    entries = []
    for line in content.split("\n"):
        if not line.startswith("- "):
            continue
        name, sep, desc = line[2:].partition(": ")
        name = name.strip()
        if not SKILL_NAME_RE.match(name):
            continue
        entries.append((name, bool(sep and desc.strip())))
    return entries


def _skill_has_description(skill_md):
    with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    for line in text[3:end].splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip() not in ("", '""', "''")
    return False


def load_skill_descriptions(config_dir):
    """Map every locally installed skill name to whether its SKILL.md has a description."""
    descs = {}
    manifest = os.path.join(config_dir, "plugins", "installed_plugins.json")
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            plugins = (json.load(f).get("plugins") or {})
        for key, entries in plugins.items():
            plugin = key.split("@", 1)[0]
            for entry in entries or []:
                install = (entry or {}).get("installPath")
                if not install:
                    continue
                for md in glob.glob(os.path.join(install, "skills", "*", "SKILL.md")):
                    descs[f"{plugin}:{os.path.basename(os.path.dirname(md))}"] = _skill_has_description(md)
    for md in glob.glob(os.path.join(config_dir, "skills", "*", "SKILL.md")):
        descs[os.path.basename(os.path.dirname(md))] = _skill_has_description(md)
    return descs


def listing_chars_by_owner(content):
    """Skill listing chars per owning plugin; unprefixed skills are "(local)"."""
    out = {}
    owner = None
    for line in content.split("\n"):
        if line.startswith("- "):
            name = line[2:].partition(": ")[0].strip()
            if SKILL_NAME_RE.match(name):
                owner = name.split(":", 1)[0] if ":" in name else "(local)"
        if owner is not None:
            out[owner] = out.get(owner, 0) + len(line) + 1
    return out


def dropped_skills(content, skill_descs):
    """Bare listing entries for skills that have a description Claude never saw."""
    out = []
    for name, described in parse_skill_listing(content):
        if described:
            continue
        if name not in skill_descs:
            out.append({"name": name, "reason": "source_not_found"})
        elif skill_descs[name]:
            out.append({"name": name, "reason": "has_description"})
    return out


def _hook_commands(hooks_obj):
    for groups in (hooks_obj or {}).values():
        for group in groups or []:
            for h in (group or {}).get("hooks") or []:
                cmd = (h or {}).get("command")
                if cmd:
                    yield cmd


def load_hook_owners(config_dir):
    """Literal hook command string -> owner label.

    Transcripts record commands unexpanded, so matching is verbatim.
    """
    owners = {}
    manifest = os.path.join(config_dir, "plugins", "installed_plugins.json")
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            plugins = (json.load(f).get("plugins") or {})
        for key, entries in plugins.items():
            plugin = key.split("@", 1)[0]
            for entry in entries or []:
                hooks_path = os.path.join((entry or {}).get("installPath") or "", "hooks", "hooks.json")
                if not os.path.isfile(hooks_path):
                    continue
                with open(hooks_path, encoding="utf-8") as f:
                    for cmd in _hook_commands(json.load(f).get("hooks")):
                        owners.setdefault(cmd, set()).add(plugin)
    settings = os.path.join(config_dir, "settings.json")
    if os.path.isfile(settings):
        with open(settings, encoding="utf-8") as f:
            for cmd in _hook_commands(json.load(f).get("hooks")):
                owners.setdefault(cmd, set()).add("settings.json")
    return {cmd: ", ".join(sorted(names)) for cmd, names in owners.items()}


SIMPLE_SOURCES = ("skill_listing", "deferred_tools", "mcp_instructions", "agent_listing")
ALL_SOURCES = SIMPLE_SOURCES + ("hook_context", "instructions")


class LedgerFormatError(Exception):
    pass


def find_sessions(projects_dir):
    """Main-session transcripts, newest first. Subagent transcripts sit deeper and are excluded."""
    files = glob.glob(os.path.join(projects_dir, "*", "*.jsonl"))
    return sorted(files, key=os.path.getmtime, reverse=True)


def _median(values):
    return int(round(statistics.median(values)))


def _session_hook_context(s, hook_owners):
    """(total_chars, {owner: chars}, no_context_count, unparsed_count) or None if no hook data."""
    hooks = s.get("hooks") or []
    if "hook_merged" not in s and not hooks:
        return None
    by_owner = {}
    for h in hooks:
        if h["status"] == "context":
            owner = hook_owners.get(h["command"], "unattributed")
            by_owner[owner] = by_owner.get(owner, 0) + h["chars"]
    total = s["hook_merged"]["chars"] if "hook_merged" in s else sum(by_owner.values())
    no_ctx = sum(1 for h in hooks if h["status"] == "no_context")
    unparsed = sum(1 for h in hooks if h["status"] == "unparsed")
    return total, by_owner, no_ctx, unparsed


def build_ledger(files, samples, max_sessions, hook_owners, skill_descs, tokens_per_byte,
                 include_sdk=False, project=None):
    collected = {k: [] for k in ALL_SOURCES}
    format_errors = []
    skipped = {}
    scanned = 0
    norm_project = os.path.realpath(project) if project else None
    for path in files:
        if scanned >= max_sessions or all(len(v) >= samples for v in collected.values()):
            break
        ep = session_entrypoint(path)
        if not include_sdk and ep and ep.startswith("sdk-"):
            skipped[ep] = skipped.get(ep, 0) + 1
            continue
        scanned += 1
        s = extract_session(path)
        format_errors.extend(s["format_errors"])
        for key in SIMPLE_SOURCES:
            if key in s and len(collected[key]) < samples:
                collected[key].append(s[key])
        hc = _session_hook_context(s, hook_owners)
        if hc is not None and len(collected["hook_context"]) < samples:
            collected["hook_context"].append(hc)
        if "instructions" in s and len(collected["instructions"]) < samples:
            if norm_project is None:
                collected["instructions"].append(s["instructions"])
            else:
                cwd = s.get("cwd")
                if cwd:
                    ncwd = os.path.realpath(cwd)
                    if ncwd == norm_project or ncwd.startswith(norm_project + "/"):
                        collected["instructions"].append(s["instructions"])

    if scanned and not any(collected.values()):
        raise LedgerFormatError(
            f"transcript format not recognized; context ledger unavailable "
            f"(no known attachment records in {scanned} sessions)")

    tok = lambda chars: int(round(chars * tokens_per_byte))

    def base(rows):
        m = _median([r["chars"] for r in rows])
        return {"samples": len(rows), "median_chars": m, "median_tokens": tok(m)}

    def median_map(maps):
        keys = {k for m in maps for k in m}
        return {k: _median([m[k] for m in maps if k in m]) for k in sorted(keys)}

    sources = {}
    if collected["skill_listing"]:
        rows = collected["skill_listing"]
        sources["skill_listing"] = dict(base(rows),
                                        skill_count=rows[0]["skill_count"],
                                        dropped=dropped_skills(rows[0]["content"], skill_descs),
                                        by_owner=listing_chars_by_owner(rows[0]["content"]))
    if collected["deferred_tools"]:
        rows = collected["deferred_tools"]
        sources["deferred_tools"] = dict(base(rows),
                                         median_names=_median([r["names"] for r in rows]),
                                         by_server=median_map([r["by_server"] for r in rows]))
    if collected["mcp_instructions"]:
        rows = collected["mcp_instructions"]
        sources["mcp_instructions"] = dict(base(rows), by_server=median_map([r["by_server"] for r in rows]))
    if collected["agent_listing"]:
        sources["agent_listing"] = base(collected["agent_listing"])
    if collected["hook_context"]:
        rows = collected["hook_context"]
        m = _median([r[0] for r in rows])
        sources["hook_context"] = {"samples": len(rows), "median_chars": m, "median_tokens": tok(m),
                                   "by_owner": median_map([r[1] for r in rows]),
                                   "no_context_outputs": sum(r[2] for r in rows),
                                   "unparsed_outputs": sum(r[3] for r in rows)}
    if collected["instructions"]:
        per_path = {}
        for session_files in collected["instructions"]:
            for f in session_files:
                per_path.setdefault(f["path"], {"type": f["type"], "chars": []})["chars"].append(f["chars"])
        files_out = []
        for p, v in sorted(per_path.items()):
            m = _median(v["chars"])
            files_out.append({"path": p, "type": v["type"], "samples": len(v["chars"]),
                              "median_chars": m, "median_tokens": tok(m)})
        sources["instructions"] = {"samples": len(collected["instructions"]), "files": files_out}

    return {"scanned_sessions": scanned, "skipped_entrypoints": skipped,
            "tokens_per_byte": tokens_per_byte, "project": project, "sources": sources,
            "missing": [k for k in ALL_SOURCES if k not in sources], "format_errors": format_errors}


def _top(mapping, n=10):
    return sorted(mapping.items(), key=lambda kv: -kv[1])[:n]


def render_markdown(ledger):
    src = ledger["sources"]
    lines = ["# Measured Context Ledger", "",
             f"Sessions scanned: {ledger['scanned_sessions']}"
             + (" (skipped non-interactive: " + ", ".join(f"{k} {v}" for k, v in sorted(ledger["skipped_entrypoints"].items())) + ")"
                if ledger["skipped_entrypoints"] else "")]
    if ledger.get("project"):
        lines.append(f"Instruction files: sessions in {ledger['project']}")
    lines += ["", "| Source | Samples | ~Chars | ~Tokens |", "|---|---|---|---|"]
    labels = {"skill_listing": "Skill listing", "deferred_tools": "Deferred tool names",
              "mcp_instructions": "MCP server instructions", "agent_listing": "Agent listing",
              "hook_context": "SessionStart hook context"}
    for key, label in labels.items():
        if key in src:
            r = src[key]
            lines.append(f"| {label} | {r['samples']} | {r['median_chars']:,} | {r['median_tokens']:,} |")
    for f in (src.get("instructions") or {}).get("files", []):
        lines.append(f"| {f['type']}: {f['path']} | {f['samples']} | {f['median_chars']:,} | {f['median_tokens']:,} |")
    if ledger["missing"]:
        lines += ["", "Not present in transcripts: " + ", ".join(ledger["missing"])]
    for key, title, field in (("skill_listing", "Skill listing by plugin", "by_owner"),
                              ("deferred_tools", "Deferred tool names by server", "by_server"),
                              ("mcp_instructions", "MCP instructions by server", "by_server"),
                              ("hook_context", "Hook context by owner", "by_owner")):
        if key in src and src[key][field]:
            lines += ["", f"## {title}", "", "| Name | ~Chars |", "|---|---|"]
            lines += [f"| {k} | {v:,} |" for k, v in _top(src[key][field])]
    dropped = (src.get("skill_listing") or {}).get("dropped") or []
    if dropped:
        lines += ["", "## Skills listed without descriptions", "",
                  "The skill listing hit its size budget; these skills appear by name only, "
                  "so Claude cannot match them to a request.", ""]
        lines += [f"- {x['name']} ({x['reason']})" for x in dropped]
    if ledger["format_errors"]:
        lines += ["", "## Unparseable records", ""] + [f"- {e}" for e in ledger["format_errors"]]
    return "\n".join(lines)


def main(argv):
    opts = {"--projects-dir": PROJECTS_DIR, "--config-dir": CONFIG_DIR,
            "--samples": "10", "--max-sessions": "100", "--tokens-per-byte": "0.25",
            "--project": None}
    as_json = False
    include_sdk = False
    args = argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--include-sdk":
            include_sdk = True
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
    try:
        samples = int(opts["--samples"])
        max_sessions = int(opts["--max-sessions"])
        tpb = float(opts["--tokens-per-byte"])
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    if samples < 1:
        sys.stderr.write("error: --samples must be >= 1\n")
        return 2
    if max_sessions < 1:
        sys.stderr.write("error: --max-sessions must be >= 1\n")
        return 2

    projects_dir = opts["--projects-dir"]
    if not os.path.isdir(projects_dir):
        sys.stderr.write(f"error: projects dir not found: {projects_dir}\n")
        return 1
    files = find_sessions(projects_dir)
    if not files:
        sys.stderr.write(f"error: no main-session transcripts under {projects_dir}\n")
        return 1
    config_dir = opts["--config-dir"]
    try:
        ledger = build_ledger(files, samples, max_sessions, load_hook_owners(config_dir),
                              load_skill_descriptions(config_dir), tpb, include_sdk=include_sdk,
                              project=opts["--project"])
    except LedgerFormatError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    if ledger["scanned_sessions"] == 0:
        sys.stderr.write(f"error: no interactive sessions among {len(files)} transcripts "
                         f"(skipped: {ledger['skipped_entrypoints']}); pass --include-sdk to measure them\n")
        return 1
    print(json.dumps(ledger, indent=2) if as_json else render_markdown(ledger))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
