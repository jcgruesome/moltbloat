#!/usr/bin/env python3
"""Flag stale and bloated content in CLAUDE.md / SKILL.md files.

The one moltbloat check that cross-references file content against what
Claude Code *itself* currently supports, catching drift the product caused
rather than internal contradictions (other checks already cover those).

Two kinds of checks: (1) structural heuristics that never need updating
(verbosity vs. Anthropic's ~200-line guidance, header density, unknown
slash-command references that don't match any installed skill); (2)
KNOWN_DEPRECATIONS, a small dated snapshot of Claude Code capability changes
from docs.claude.com/code.claude.com research on SNAPSHOT_DATE below. This is
a snapshot, not a live feed — refresh it by hand periodically; an empty
result here is not proof a file has no stale content.

Usage:
  python3 claude-md-staleness.py <file> [<file> ...] [--json]
                                  [--verbose-threshold N]
                                  [--known-skill-refs a,b,c]
Output: markdown, or one JSON object with --json. Fails fast on a missing path.
"""
import json
import os
import re
import sys

SNAPSHOT_DATE = "2026-09-10"

# Anthropic's own guidance: keep CLAUDE.md under ~200 lines (frontier models
# reliably follow only ~150-200 instructions). Same ceiling for SKILL.md.
DEFAULT_VERBOSE_THRESHOLD = 200

# A long, nearly headerless file is a wall of prose, expensive to scan and
# easy to let rot. Only fires above this many lines.
UNSTRUCTURED_MIN_LINES = 60
UNSTRUCTURED_MAX_LINES_PER_HEADER = 40

# Dated snapshot from changelog/docs research on SNAPSHOT_DATE — refresh by
# hand, see module docstring. Each regex hit means the file cites something
# Claude Code has since renamed, removed, or superseded.
KNOWN_DEPRECATIONS = [
    {
        "id": "reload-plugins-removed",
        "pattern": re.compile(r"/reload-plugins"),
        "message": (
            "References `/reload-plugins`, removed in Claude Code 2.1.268 "
            "(Sept 10, 2026) — plugin install/enable/disable now takes "
            "effect as soon as the menu closes."
        ),
        "severity": "MEDIUM",
    },
    {
        "id": "keybinding-flavor-removed",
        "pattern": re.compile(r"\bkeybindingFlavor\b"),
        "message": (
            "References `keybindingFlavor`, removed in Claude Code 2.1.261 "
            "(Sept 4, 2026) — word-editing keys now match Bash defaults "
            "(Ctrl+W, Alt+F/Alt+D) unconditionally."
        ),
        "severity": "MEDIUM",
    },
    {
        "id": "bypass-permissions-default-mode-ignored",
        "pattern": re.compile(r'defaultMode["\']?\s*[:=]\s*["\']?bypassPermissions'),
        "message": (
            '`defaultMode: "bypassPermissions"` ignored since Claude Code '
            "2.1.257 (Sept 1, 2026) — set permission mode in "
            "user/managed settings or `--permission-mode` instead."
        ),
        "severity": "MEDIUM",
    },
    {
        "id": "force-login-gateway-url-changed",
        "pattern": re.compile(r"\bforceLoginGatewayUrl\b"),
        "message": (
            "References `forceLoginGatewayUrl`, whose behavior changed in "
            "Claude Code 2.1.257 (Sept 1, 2026) — verify it still matches "
            "the intended setup."
        ),
        "severity": "LOW",
    },
    {
        "id": "task-output-tool-deprecated",
        "pattern": re.compile(r"\bTaskOutput\b"),
        "message": "References `TaskOutput`, deprecated in favor of `Read` on the task's output file.",
        "severity": "LOW",
    },
    {
        "id": "manual-git-worktree-workaround",
        "pattern": re.compile(r"\bgit worktree add\b"),
        "message": (
            "Documents a hand-rolled `git worktree add` workflow. Claude "
            "Code has had native `--worktree` support (with cross-worktree "
            "`--resume`) since v2.1.49 (Feb 2026) — check if it now covers this."
        ),
        "severity": "LOW",
    },
    {
        "id": "legacy-model-name",
        "pattern": re.compile(r"claude-3-(opus|sonnet|haiku)-\d{8}|\bclaude-2\b"),
        "message": "References an older Claude model id/name — model ids and default aliases drift; verify this is still intended.",
        "severity": "LOW",
    },
]

HEADER_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)

# Matches a backtick- or bare-quoted slash command reference, e.g.
# `/moltbloat:audit` or `/audit`. Captures the part after the leading slash.
SKILL_REF_RE = re.compile(r"/([a-z][a-z0-9_-]*(?::[a-z][a-z0-9_-]*)?)\b")

# Slash-command-shaped tokens that are common-word false positives, not
# actual skill/command references (e.g. "and/or", a literal filesystem path).
SKILL_REF_STOPWORDS = {"or", "and", "etc", "dev", "usr", "bin", "tmp", "path", "home"}


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def analyze_text(path, text, verbose_threshold=DEFAULT_VERBOSE_THRESHOLD, known_skill_refs=None):
    """Return a list of findings for a single file's already-read content.

    Each finding: {type, id, severity, message, line, file}.
    `known_skill_refs`, if given, is a set of "plugin:skill" or "skill"
    strings currently installed — used to flag slash-command references that
    no longer resolve to anything. Pass None to skip that check entirely
    (an incomplete inventory would otherwise produce false positives).
    """
    findings = []
    lines = text.splitlines()
    line_count = len(lines)

    for dep in KNOWN_DEPRECATIONS:
        m = dep["pattern"].search(text)
        if m:
            findings.append({
                "type": "deprecated_reference",
                "id": dep["id"],
                "severity": dep["severity"],
                "message": dep["message"],
                "line": _line_of(text, m.start()),
                "file": path,
            })

    if line_count > verbose_threshold:
        findings.append({
            "type": "verbose",
            "id": "verbose-file",
            "severity": "LOW",
            "message": (
                f"{line_count} lines, over the ~{verbose_threshold}-line ceiling "
                "Anthropic recommends for always-loaded memory files (frontier "
                "models reliably follow only ~150-200 instructions, and the "
                "system prompt already spends some of that budget). Consider "
                "moving detail into @-imported files or skill docs loaded on demand."
            ),
            "line": 1,
            "file": path,
        })

    if line_count >= UNSTRUCTURED_MIN_LINES:
        header_count = len(HEADER_RE.findall(text))
        max_headers_expected = max(1, line_count // UNSTRUCTURED_MAX_LINES_PER_HEADER)
        if header_count < max_headers_expected:
            findings.append({
                "type": "unstructured",
                "id": "low-header-density",
                "severity": "LOW",
                "message": (
                    f"{line_count} lines with only {header_count} header(s). "
                    "A long, unbroken file is harder to scan and easier to let "
                    "rot silently; consider breaking it into headed sections."
                ),
                "line": 1,
                "file": path,
            })

    if known_skill_refs is not None:
        seen = set()
        for m in SKILL_REF_RE.finditer(text):
            ref = m.group(1)
            if ref in seen or ref.lower() in SKILL_REF_STOPWORDS:
                continue
            seen.add(ref)
            if ref in known_skill_refs:
                continue
            # Bare skill name (no plugin prefix) might still match any
            # installed plugin's skill of that name.
            bare = ref.split(":")[-1]
            if any(k.split(":")[-1] == bare for k in known_skill_refs):
                continue
            findings.append({
                "type": "unknown_skill_reference",
                "id": "unknown-skill-reference",
                "severity": "HIGH",
                "message": (
                    f"References `/{ref}`, which doesn't match any currently "
                    "installed skill. It may have been renamed, removed, or "
                    "the plugin providing it was uninstalled."
                ),
                "line": _line_of(text, m.start()),
                "file": path,
            })

    return findings


def scan_paths(paths, verbose_threshold=DEFAULT_VERBOSE_THRESHOLD, known_skill_refs=None):
    """Read and analyze each path. Raises if a path doesn't exist (fail fast)."""
    all_findings = []
    for p in paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        all_findings.extend(
            analyze_text(p, text, verbose_threshold=verbose_threshold, known_skill_refs=known_skill_refs)
        )
    return {
        "snapshot_date": SNAPSHOT_DATE,
        "files_scanned": len(paths),
        "findings": all_findings,
    }


def render_markdown(result):
    lines = ["# CLAUDE.md / SKILL.md Staleness Check", ""]
    lines.append(
        f"Scanned {result['files_scanned']} file(s). Known-deprecations table is a dated "
        f"snapshot from {result['snapshot_date']} research against Claude Code's changelog — "
        "refresh it periodically; an empty result here is not proof nothing is stale."
    )
    lines.append("")
    if not result["findings"]:
        lines.append("No staleness or bloat findings.")
        return "\n".join(lines)

    by_severity = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
    for f in result["findings"]:
        by_severity.setdefault(f["severity"], []).append(f)

    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        items = by_severity.get(severity, [])
        if not items:
            continue
        lines.append(f"### {severity} ({len(items)})")
        lines.append("| File | Line | Finding |")
        lines.append("|---|---|---|")
        for f in items:
            lines.append(f"| {f['file']} | {f['line']} | {f['message']} |")
        lines.append("")

    return "\n".join(lines)


def main(argv):
    args = argv[1:]
    as_json = False
    verbose_threshold = DEFAULT_VERBOSE_THRESHOLD
    known_skill_refs = None
    positional = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--verbose-threshold":
            i += 1
            if i >= len(args):
                sys.stderr.write("error: --verbose-threshold requires an integer\n")
                return 2
            verbose_threshold = int(args[i])
        elif a == "--known-skill-refs":
            i += 1
            if i >= len(args):
                sys.stderr.write("error: --known-skill-refs requires a comma-separated list\n")
                return 2
            known_skill_refs = {s.strip() for s in args[i].split(",") if s.strip()}
        else:
            positional.append(a)
        i += 1

    if not positional:
        sys.stderr.write("error: no files given\n")
        return 2

    try:
        result = scan_paths(positional, verbose_threshold=verbose_threshold, known_skill_refs=known_skill_refs)
    except FileNotFoundError as e:
        sys.stderr.write(f"error: file not found: {e}\n")
        return 1

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
