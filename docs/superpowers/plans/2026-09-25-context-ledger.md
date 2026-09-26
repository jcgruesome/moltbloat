# Context Ledger (Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the context each Claude Code session actually loaded (skill listing, deferred tool names, MCP instructions, agent listing, SessionStart hook output, instruction files) from transcripts, and use it in `/moltbloat:token-budget` in place of estimates.

**Architecture:** One new stdlib-only script, `scripts/context-ledger.py`, built from small pure functions: per-session extraction, skill listing overflow detection, hook ownership, and per-source sampling with medians. `token-budget` calls it first and falls back to its existing estimates only for sources the ledger could not measure, labeling those "est.".

**Tech Stack:** Python 3 standard library, Markdown SKILL.md instructions, bash `validate.sh`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-25-instruction-audit-design.md` (component 1 and the token-budget part of component 6; delivery slice 1).

## Global Constraints

- Python 3 standard library only; no third-party imports.
- No hardcoded plugin, skill, server, or agent names in any check.
- Fail fast: missing input directory or unrecognized transcript format exits non-zero with a clear message; never silently fall back to estimates.
- Missing individual source types are reported as "not present in transcripts", never as zero.
- Median is over sessions where the type was present; absent sessions are excluded, not counted as 0.
- Hook totals are never summed across `hook_additional_context` and `hook_success`.
- Defaults: `thresholds.context_ledger_samples: 10`, `thresholds.context_ledger_max_sessions: 100`.
- Tokens are `chars * estimates.tokens_per_byte` (default 0.25), rounded.
- Interactive sessions only by default: skip `entrypoint` values starting with `sdk-`, report the skipped counts, `--include-sdk` to override.
- Tests follow the repo pattern: `scripts/test-<name>.py`, self-running, `_assert` helper, temp-dir fixtures.
- No em dashes in any written copy (docs, SKILL.md text, commit messages).
- Every commit message ends with the line `Claude-Session: https://claude.ai/code/session_01CJQqC6KKB82TVmLiQxj9Kr`.
- Out of scope for this slice: audit Check 15, the `skill_description_dropped` audit finding, clean actions, delegation cost.

## Review Focus

1. A live session's transcript has a truncated final line: the line is skipped and the rest of the session still measured (test in Task 1).
2. A session whose deferred tools are all built-in (no `mcp__` names): grouped under `(built-in)`, not dropped or crashed (test in Task 1).
3. A multi-line skill description whose continuation line starts with `- `: not reported as a dropped skill (name-pattern guard, test in Task 2).
4. The same hook command string registered by two plugins: owner shows both, not whichever loaded first (test in Task 3).
5. A projects dir that has only subagent transcripts, or only SDK sessions: exits 1 with a message naming why, not an empty ledger (tests in Task 4).

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/context-ledger.py` (create) | Extraction, overflow detection, hook ownership, sampling, CLI, markdown |
| `scripts/test-context-ledger.py` (create) | Fixture-based tests for all of the above |
| `scripts/init-config.py` (modify) | Two new threshold defaults, version bump |
| `scripts/test-init-config.py` (modify) | Assert new defaults and migration |
| `scripts/validate.sh` (modify) | Compile and run the new test |
| `.github/workflows/ci.yml` (modify) | Run the new test in CI |
| `skills/token-budget/SKILL.md` (modify) | Call the ledger first; measured vs est. rows; dropped-skills section |
| `README.md` (modify) | Document measured context |

Transcript facts the code relies on (verified against real data 2026-09-25):

- Main-session transcripts are `~/.claude/projects/<project>/<session>.jsonl`. Subagent transcripts are deeper (`<project>/<session>/subagents/agent-*.jsonl`), so the glob `<projects>/*/*.jsonl` returns main sessions only.
- Attachment lines look like `{"type": "attachment", "attachment": {"type": "<kind>", ...}, "timestamp": ...}`.
- `skill_listing`: `content` (str, lines `- name: description` or bare `- name`), `skillCount` (int).
- `deferred_tools_delta`: `addedNames` (list[str]), `addedLines` (list[str]).
- `mcp_instructions_delta`: `addedNames` (list[str]) aligned with `addedBlocks` (list[str]).
- `agent_listing_delta`: `addedTypes` (list[str]) aligned with `addedLines` (list[str]).
- The three `*_delta` kinds arrive as several records per session (e.g. 15 built-in names, then 764 more once MCP servers connect; removals and re-adds occur).
- Every line carries `entrypoint`: `cli` for interactive terminal sessions, `sdk-cli` / `sdk-py` for automated SDK sessions (observed: 54 of the 60 newest transcripts were SDK sessions, many spawned by plugins).
- `instructions`: `files` (list of `{path, type, content}`).
- `hook_additional_context`: `content` (list[str], one entry per hook; accept a plain str too).
- `hook_success`: `hookEvent`, `toolUseID`, `command` (unexpanded, e.g. `"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start`), `stdout` (str, often JSON `{"hookSpecificOutput": {"additionalContext": "..."}}`).
- Installed plugins: `~/.claude/plugins/installed_plugins.json` → `{"plugins": {"<name>@<marketplace>": [{"installPath": ...}]}}`.

Per-session rules:
- `skill_listing`, `instructions`, `hook_additional_context`: first record only (re-injection after compaction or resume would double count).
- `*_delta` kinds: union of every added entry across the session, keyed by name (tool name, server name, agent type), so re-adds do not double count and late-connecting MCP servers are included.
- `hook_success`: every `SessionStart` record sharing the first SessionStart `toolUseID`.
- Sessions whose `entrypoint` starts with `sdk-` are skipped by default (counted in `skipped_entrypoints`); `--include-sdk` measures them too. Sessions with no `entrypoint` are included.

---

### Task 1: Per-session extraction

**Files:**
- Create: `scripts/context-ledger.py`
- Test: `scripts/test-context-ledger.py`

**Interfaces:**
- Produces:
  - `server_of(tool_name: str) -> str`
  - `hook_context_len(stdout: str) -> tuple[str, int]` returning `("context", n)`, `("no_context", 0)`, or `("unparsed", 0)`
  - `session_entrypoint(path: str) -> str | None`
  - `extract_session(path: str) -> dict` with optional keys `instructions`, `skill_listing`, `deferred_tools`, `mcp_instructions`, `agent_listing`, `hook_merged`, `hooks`, and always `entrypoint` and `format_errors` (list[str])

- [ ] **Step 1: Write the failing test**

Create `scripts/test-context-ledger.py`:

```python
#!/usr/bin/env python3
"""Tests for context-ledger.py: measured per-session context from transcripts.

Run: python3 scripts/test-context-ledger.py
"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("context_ledger", os.path.join(HERE, "context-ledger.py"))
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def att(payload):
    return {"type": "attachment", "attachment": payload}


def hook(stdout, command="cmd-a", tool_use_id="t1", event="SessionStart"):
    return att({"type": "hook_success", "hookEvent": event, "toolUseID": tool_use_id,
                "command": command, "stdout": stdout})


def write_session(path, records, raw_tail=None, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
        if raw_tail is not None:
            f.write(raw_tail)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_extract_session(d):
    print("Test: extract_session reads each attachment kind")
    ctx_json = json.dumps({"hookSpecificOutput": {"additionalContext": "x" * 40}})
    records = [
        {"type": "user", "entrypoint": "cli", "message": {"content": "hi"}},
        att({"type": "skill_listing", "content": "- a: does a\n- b", "skillCount": 2}),
        att({"type": "skill_listing", "content": "- later: ignored", "skillCount": 1}),
        att({"type": "deferred_tools_delta",
             "addedNames": ["mcp__srv1__t1", "mcp__srv1__t2", "WebFetch"],
             "addedLines": ["mcp__srv1__t1", "mcp__srv1__t2", "WebFetch"]}),
        att({"type": "deferred_tools_delta",
             "addedNames": ["mcp__srv1__t2", "mcp__srv2__x"],
             "addedLines": ["mcp__srv1__t2", "mcp__srv2__x"]}),
        att({"type": "mcp_instructions_delta", "addedNames": ["srv1", "srv2"],
             "addedBlocks": ["## srv1\nuse it", "## srv2"]}),
        att({"type": "mcp_instructions_delta", "addedNames": ["srv1"], "addedBlocks": ["## srv1\nuse it"]}),
        att({"type": "agent_listing_delta", "addedTypes": ["explore", "executor"],
             "addedLines": ["- explore: read-only", "- executor: builds"]}),
        att({"type": "instructions", "files": [
            {"path": "/u/.claude/CLAUDE.md", "type": "User", "content": "y" * 100},
            {"path": "/p/CLAUDE.md", "type": "Project", "content": "z" * 30}]}),
        att({"type": "hook_additional_context", "content": ["m" * 30, "m" * 25]}),
        hook(ctx_json, command="cmd-a"),
        hook('{"continue":true}', command="cmd-b"),
        hook("plain text", command="cmd-c"),
        hook(ctx_json, command="cmd-d", tool_use_id="t2"),
        hook(ctx_json, command="cmd-e", event="PostToolUse"),
    ]
    p = os.path.join(d, "proj", "s1.jsonl")
    write_session(p, records, raw_tail='{"type": "attachment", "attachm')
    s = cl.extract_session(p)

    _assert(s["entrypoint"] == "cli", "entrypoint read from transcript")
    _assert(s["skill_listing"]["chars"] == len("- a: does a\n- b"), "skill listing chars from first record")
    _assert(s["skill_listing"]["skill_count"] == 2, "skill count from first record")
    _assert(s["deferred_tools"]["names"] == 4, "deferred names are the union across deltas")
    _assert(s["deferred_tools"]["by_server"] == {"srv1": 28, "(built-in)": 9, "srv2": 13},
            "deferred grouped by server, re-added name not double counted, built-ins grouped")
    _assert(s["deferred_tools"]["chars"] == 50, "deferred chars = sum of unique line lengths plus newlines")
    _assert(s["mcp_instructions"]["by_server"] == {"srv1": 14, "srv2": 7}, "mcp instructions by server, re-add not doubled")
    _assert(s["mcp_instructions"]["chars"] == 21, "mcp instructions total")
    _assert(s["agent_listing"]["chars"] == len("- explore: read-only") + 1 + len("- executor: builds") + 1, "agent listing chars")
    _assert(s["instructions"] == [
        {"path": "/u/.claude/CLAUDE.md", "type": "User", "chars": 100},
        {"path": "/p/CLAUDE.md", "type": "Project", "chars": 30}], "instruction files with sizes")
    _assert(s["hook_merged"]["chars"] == 55, "merged hook context sums the content list")
    _assert(s["hooks"] == [
        {"command": "cmd-a", "status": "context", "chars": 40},
        {"command": "cmd-b", "status": "no_context", "chars": 0},
        {"command": "cmd-c", "status": "unparsed", "chars": 0}],
        "only first SessionStart batch; other events and later batches ignored")
    _assert(s["format_errors"] == [], "no format errors; truncated tail line skipped")

    print("Test: mismatched arrays are a format error, not a guess")
    p2 = os.path.join(d, "proj", "s2.jsonl")
    write_session(p2, [att({"type": "mcp_instructions_delta", "addedNames": ["a", "b"], "addedBlocks": ["x"]})])
    s2 = cl.extract_session(p2)
    _assert("mcp_instructions" not in s2, "mismatched record not measured")
    _assert(len(s2["format_errors"]) == 1 and "mcp_instructions_delta" in s2["format_errors"][0], "format error recorded")
    _assert(s2["entrypoint"] is None, "no entrypoint field -> None")

    print("Test: all-built-in deferred tools and plain-string merged hook content")
    p3 = os.path.join(d, "proj", "s3.jsonl")
    write_session(p3, [att({"type": "deferred_tools_delta", "addedNames": ["Read2"], "addedLines": ["Read2"]}),
                       att({"type": "hook_additional_context", "content": "abc"})])
    s3 = cl.extract_session(p3)
    _assert(s3["deferred_tools"]["by_server"] == {"(built-in)": 6}, "built-in only grouped")
    _assert(s3["hook_merged"]["chars"] == 3, "plain string content accepted")


def run():
    with tempfile.TemporaryDirectory() as d:
        test_extract_session(d)
    print("All context-ledger tests passed.")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test-context-ledger.py`
Expected: FAIL, `FileNotFoundError` for `context-ledger.py`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/context-ledger.py`:

```python
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
    Returns ("context", n), ("no_context", 0) for JSON without it, or
    ("unparsed", 0) for non-JSON output.
    """
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


def _aligned(a, keys_field, values_field, kind, path, errors):
    keys = a.get(keys_field) or []
    values = a.get(values_field) or []
    if len(keys) != len(values):
        errors.append(f"{kind}: {len(keys)} {keys_field} vs {len(values)} {values_field} in {path}")
        return []
    return list(zip(keys, values))


def extract_session(path):
    """Measure one main-session transcript (per-session rules in the plan)."""
    s = {"format_errors": [], "entrypoint": session_entrypoint(path)}
    deferred, mcp, agents = {}, {}, {}
    hook_batch = None
    hooks = []
    for a in _iter_attachments(path):
        kind = a["type"]
        if kind == "skill_listing" and "skill_listing" not in s:
            content = a.get("content") or ""
            s["skill_listing"] = {"chars": len(content), "skill_count": a.get("skillCount"), "content": content}
        elif kind == "deferred_tools_delta":
            names = a.get("addedNames") or []
            if "addedLines" not in a:
                a = dict(a, addedLines=names)
            deferred.update(_aligned(a, "addedNames", "addedLines", kind, path, s["format_errors"]))
        elif kind == "mcp_instructions_delta":
            mcp.update(_aligned(a, "addedNames", "addedBlocks", kind, path, s["format_errors"]))
        elif kind == "agent_listing_delta":
            agents.update(_aligned(a, "addedTypes", "addedLines", kind, path, s["format_errors"]))
        elif kind == "instructions" and "instructions" not in s:
            s["instructions"] = [
                {"path": f.get("path"), "type": f.get("type"), "chars": len(f.get("content") or "")}
                for f in a.get("files") or [] if isinstance(f, dict)
            ]
        elif kind == "hook_additional_context" and "hook_merged" not in s:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test-context-ledger.py`
Expected: every line `ok`, last line `All context-ledger tests passed.`

- [ ] **Step 5: Commit**

```bash
git add scripts/context-ledger.py scripts/test-context-ledger.py
git commit -F - <<'EOF'
feat: extract per-session context from transcript attachments

Claude-Session: https://claude.ai/code/session_01CJQqC6KKB82TVmLiQxj9Kr
EOF
```

---

### Task 2: Skill listing overflow detection

**Files:**
- Modify: `scripts/context-ledger.py` (append functions)
- Test: `scripts/test-context-ledger.py` (add `test_skill_overflow`, call it from `run()`)

**Interfaces:**
- Consumes: `extract_session(...)["skill_listing"]["content"]` from Task 1.
- Produces:
  - `parse_skill_listing(content: str) -> list[tuple[str, bool]]` (name, listed_with_description)
  - `load_skill_descriptions(config_dir: str) -> dict[str, bool]` (skill name to "SKILL.md has a description")
  - `dropped_skills(content: str, skill_descs: dict[str, bool]) -> list[dict]` with entries `{"name", "reason"}`, reason `"has_description"` or `"source_not_found"`
  - `listing_chars_by_owner(content: str) -> dict[str, int]`: listing chars per plugin (the part before `:` in the skill name) or `"(local)"` for unprefixed skills; continuation lines count toward the entry above them

- [ ] **Step 1: Write the failing test**

Add to `scripts/test-context-ledger.py` above `run()`:

```python
def write_skill(root, name, description):
    os.makedirs(os.path.join(root, name), exist_ok=True)
    fm = f"description: {description}\n" if description is not None else ""
    with open(os.path.join(root, name, "SKILL.md"), "w") as f:
        f.write(f"---\nname: {name}\n{fm}---\n\nBody.\n")


def test_skill_overflow(d):
    print("Test: parse_skill_listing splits named entries from bare ones")
    content = ("- api-design: REST patterns\n"
               "- tool:setup: Configure it\n"
               "  continued line of a description\n"
               "- tool:bare\n"
               "- - not a skill, a markdown bullet inside a description\n"
               "- local-bare")
    entries = cl.parse_skill_listing(content)
    _assert(("api-design", True) in entries, "described entry")
    _assert(("tool:setup", True) in entries, "plugin:skill entry keeps colon in name")
    _assert(("tool:bare", False) in entries, "bare plugin entry")
    _assert(("local-bare", False) in entries, "bare local entry")

    print("Test: load_skill_descriptions reads plugin and local SKILL.md frontmatter")
    config_dir = os.path.join(d, "cfg")
    install = os.path.join(d, "cache", "tool", "1.0.0")
    write_skill(os.path.join(install, "skills"), "setup", "Configure it")
    write_skill(os.path.join(install, "skills"), "bare", "Has one on disk")
    write_skill(os.path.join(install, "skills"), "empty", None)
    os.makedirs(os.path.join(config_dir, "plugins"), exist_ok=True)
    with open(os.path.join(config_dir, "plugins", "installed_plugins.json"), "w") as f:
        json.dump({"plugins": {"tool@market": [{"installPath": install}]}}, f)
    write_skill(os.path.join(config_dir, "skills"), "local-bare", "Local desc")
    descs = cl.load_skill_descriptions(config_dir)
    _assert(descs.get("tool:setup") is True and descs.get("tool:bare") is True, "plugin skills keyed plugin:skill")
    _assert(descs.get("tool:empty") is False, "missing description recorded as False")
    _assert(descs.get("local-bare") is True, "local skill keyed by bare name")

    print("Test: dropped_skills reports bare entries that do have descriptions")
    dropped = cl.dropped_skills(content + "\n- tool:empty\n- ghost:skill", descs)
    names = {x["name"]: x["reason"] for x in dropped}
    _assert(names.get("tool:bare") == "has_description", "bare plugin skill with description is dropped")
    _assert(names.get("local-bare") == "has_description", "bare local skill with description is dropped")
    _assert("tool:empty" not in names, "skill with no description is not a finding")
    _assert(names.get("ghost:skill") == "source_not_found", "unknown bare skill reported as source_not_found")
    _assert(not any(n.startswith("-") for n in names), "markdown bullet in a description is not a skill")

    print("Test: listing_chars_by_owner attributes lines, including continuations")
    by_owner = cl.listing_chars_by_owner("- tool:a: desc\n  more\n- b: x\n- tool:c")
    _assert(by_owner == {"tool": len("- tool:a: desc") + 1 + len("  more") + 1 + len("- tool:c") + 1,
                         "(local)": len("- b: x") + 1},
            "chars grouped by plugin prefix, continuation lines follow their entry")
```

And in `run()` add `test_skill_overflow(d)` after `test_extract_session(d)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test-context-ledger.py`
Expected: FAIL with `AttributeError: module 'context_ledger' has no attribute 'parse_skill_listing'`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/context-ledger.py` (before any `main`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test-context-ledger.py`
Expected: all `ok`, final `All context-ledger tests passed.`

- [ ] **Step 5: Commit**

```bash
git add scripts/context-ledger.py scripts/test-context-ledger.py
git commit -F - <<'EOF'
feat: detect skills listed without their descriptions

Claude-Session: https://claude.ai/code/session_01CJQqC6KKB82TVmLiQxj9Kr
EOF
```

---

### Task 3: Hook ownership

**Files:**
- Modify: `scripts/context-ledger.py` (append)
- Test: `scripts/test-context-ledger.py` (add `test_hook_owners`, call from `run()`)

**Interfaces:**
- Produces: `load_hook_owners(config_dir: str) -> dict[str, str]` mapping the literal command string to an owner label (plugin name, `"settings.json"`, or comma-joined sorted names when shared). Commands not in the map are labeled `"unattributed"` by Task 4.

- [ ] **Step 1: Write the failing test**

Add above `run()`:

```python
def test_hook_owners(d):
    print("Test: load_hook_owners matches literal commands to plugins and settings.json")
    config_dir = os.path.join(d, "cfg-hooks")
    p1 = os.path.join(d, "cache-h", "alpha", "1.0.0")
    p2 = os.path.join(d, "cache-h", "beta", "2.0.0")
    shared = '"${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" start'
    for root, cmds in ((p1, [shared, "${CLAUDE_PLUGIN_ROOT}/a.sh"]), (p2, [shared])):
        os.makedirs(os.path.join(root, "hooks"), exist_ok=True)
        with open(os.path.join(root, "hooks", "hooks.json"), "w") as f:
            json.dump({"hooks": {"SessionStart": [{"matcher": "startup",
                       "hooks": [{"type": "command", "command": c} for c in cmds]}]}}, f)
    os.makedirs(os.path.join(config_dir, "plugins"), exist_ok=True)
    with open(os.path.join(config_dir, "plugins", "installed_plugins.json"), "w") as f:
        json.dump({"plugins": {"alpha@m": [{"installPath": p1}], "beta@m": [{"installPath": p2}]}}, f)
    with open(os.path.join(config_dir, "settings.json"), "w") as f:
        json.dump({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "~/my-hook.sh"}]}]}}, f)

    owners = cl.load_hook_owners(config_dir)
    _assert(owners["${CLAUDE_PLUGIN_ROOT}/a.sh"] == "alpha", "unique plugin command attributed")
    _assert(owners[shared] == "alpha, beta", "shared command lists both owners")
    _assert(owners["~/my-hook.sh"] == "settings.json", "settings.json hook attributed")
```

Add `test_hook_owners(d)` to `run()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test-context-ledger.py`
Expected: FAIL with `AttributeError: ... 'load_hook_owners'`.

- [ ] **Step 3: Write minimal implementation**

Append:

```python
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
```

Malformed JSON in `hooks.json` or `settings.json` raises `json.JSONDecodeError`; that is intended (fail fast, the file is broken for Claude Code too).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test-context-ledger.py`
Expected: all `ok`.

- [ ] **Step 5: Commit**

```bash
git add scripts/context-ledger.py scripts/test-context-ledger.py
git commit -F - <<'EOF'
feat: attribute SessionStart hook output to its plugin

Claude-Session: https://claude.ai/code/session_01CJQqC6KKB82TVmLiQxj9Kr
EOF
```

---

### Task 4: Ledger build, CLI, and markdown

**Files:**
- Modify: `scripts/context-ledger.py` (append)
- Test: `scripts/test-context-ledger.py` (add `test_build_ledger`, `test_cli`, call from `run()`)

**Interfaces:**
- Consumes: `extract_session`, `dropped_skills`, `load_skill_descriptions`, `load_hook_owners`.
- Produces:
  - `class LedgerFormatError(Exception)`
  - `find_sessions(projects_dir: str) -> list[str]` newest first, main sessions only
  - `build_ledger(files: list[str], samples: int, max_sessions: int, hook_owners: dict, skill_descs: dict, tokens_per_byte: float, include_sdk: bool = False) -> dict`
  - `render_markdown(ledger: dict) -> str`
  - `main(argv: list[str]) -> int` (0 ok, 1 no transcripts, 2 bad args or unrecognized format)

Ledger JSON shape (the contract Task 5 reads):

```json
{
  "scanned_sessions": 12,
  "skipped_entrypoints": {"sdk-cli": 30, "sdk-py": 18},
  "tokens_per_byte": 0.25,
  "sources": {
    "skill_listing":    {"samples": 10, "median_chars": 29999, "median_tokens": 7500, "skill_count": 134,
                         "dropped": [{"name": "x:y", "reason": "has_description"}], "by_owner": {"marketing": 4000}},
    "deferred_tools":   {"samples": 10, "median_chars": 52371, "median_tokens": 13093, "median_names": 1061,
                         "by_server": {"claude_ai_Vercel": 12000}},
    "mcp_instructions": {"samples": 10, "median_chars": 20689, "median_tokens": 5172, "by_server": {"figma": 3000}},
    "agent_listing":    {"samples": 10, "median_chars": 3578, "median_tokens": 894},
    "hook_context":     {"samples": 4, "median_chars": 6846, "median_tokens": 1712,
                         "by_owner": {"superpowers": 3604}, "no_context_outputs": 3, "unparsed_outputs": 0},
    "instructions":     {"samples": 4, "files": [{"path": "/u/.claude/CLAUDE.md", "type": "User",
                         "samples": 4, "median_chars": 16557, "median_tokens": 4139}]}
  },
  "missing": [],
  "format_errors": []
}
```

`max_sessions` counts included (interactive) sessions; skipped SDK sessions only cost a scan for the `entrypoint` field. A source with zero samples is omitted from `sources` and listed in `missing`. `by_server` / `by_owner` values are medians over sessions where that key appeared.

- [ ] **Step 1: Write the failing test**

Add above `run()`:

```python
def listing_session(path, listing_chars, mtime, with_instructions=False, hooks_merged=None, hook_stdouts=()):
    recs = [att({"type": "skill_listing", "content": "- s: " + "d" * (listing_chars - 5), "skillCount": 1})]
    if with_instructions:
        recs.append(att({"type": "instructions", "files": [{"path": "/g/CLAUDE.md", "type": "User", "content": "c" * 80}]}))
    if hooks_merged is not None:
        recs.append(att({"type": "hook_additional_context", "content": "h" * hooks_merged}))
    for cmd, out in hook_stdouts:
        recs.append(hook(out, command=cmd))
    write_session(path, recs, mtime=mtime)


def test_build_ledger(d):
    print("Test: build_ledger samples per type, medians exclude absent sessions")
    root = os.path.join(d, "projects")
    ctx = lambda n: json.dumps({"hookSpecificOutput": {"additionalContext": "x" * n}})
    listing_session(os.path.join(root, "p", "a.jsonl"), 100, 1000, with_instructions=True,
                    hooks_merged=70, hook_stdouts=[("cmd-a", ctx(50)), ("cmd-z", ctx(20))])
    listing_session(os.path.join(root, "p", "b.jsonl"), 200, 2000,
                    hook_stdouts=[("cmd-a", ctx(30)), ("cmd-q", "{}")])
    listing_session(os.path.join(root, "p", "c.jsonl"), 300, 3000, with_instructions=True)
    write_session(os.path.join(root, "p", "c", "subagents", "agent-x.jsonl"),
                  [att({"type": "skill_listing", "content": "- zzz", "skillCount": 1})], mtime=9000)

    files = cl.find_sessions(root)
    _assert([os.path.basename(f) for f in files] == ["c.jsonl", "b.jsonl", "a.jsonl"], "main sessions newest first, subagents excluded")

    led = cl.build_ledger(files, samples=10, max_sessions=100, hook_owners={"cmd-a": "alpha"},
                          skill_descs={}, tokens_per_byte=0.25)
    src = led["sources"]
    _assert(src["skill_listing"]["samples"] == 3 and src["skill_listing"]["median_chars"] == 200, "listing median over 3")
    _assert(src["skill_listing"]["median_tokens"] == 50, "tokens = chars * tokens_per_byte")
    _assert(src["skill_listing"]["by_owner"] == {"(local)": 301}, "by_owner from newest listing (300 chars + newline)")
    _assert(src["instructions"]["samples"] == 2, "instructions sampled only where present")
    _assert(src["instructions"]["files"][0]["median_chars"] == 80, "per-file median")
    hc = src["hook_context"]
    _assert(hc["samples"] == 2, "hook context present in 2 sessions")
    _assert(hc["median_chars"] == 50, "merged total (70) used for a, per-command sum (30) for b; median 50")
    _assert(hc["by_owner"] == {"alpha": 40, "unattributed": 20}, "owner medians; unknown command unattributed")
    _assert(hc["no_context_outputs"] == 1, "JSON without additionalContext tallied")
    _assert("deferred_tools" in led["missing"] and "deferred_tools" not in src, "absent type listed as missing, not zero")

    print("Test: samples cap stops collecting a type early")
    led2 = cl.build_ledger(files, samples=1, max_sessions=100, hook_owners={}, skill_descs={}, tokens_per_byte=0.25)
    _assert(led2["sources"]["skill_listing"]["samples"] == 1 and led2["sources"]["skill_listing"]["median_chars"] == 300,
            "only newest session used when samples=1")

    print("Test: max_sessions bounds the scan")
    led3 = cl.build_ledger(files, samples=10, max_sessions=1, hook_owners={}, skill_descs={}, tokens_per_byte=0.25)
    _assert(led3["scanned_sessions"] == 1, "scan stops at max_sessions")

    print("Test: SDK sessions are skipped by default and counted")
    sdk = os.path.join(root, "p", "sdk.jsonl")
    write_session(sdk, [{"type": "user", "entrypoint": "sdk-cli"},
                        att({"type": "skill_listing", "content": "- s: " + "d" * 995, "skillCount": 1})], mtime=5000)
    files_sdk = cl.find_sessions(root)
    led4 = cl.build_ledger(files_sdk, 10, 100, {}, {}, 0.25)
    _assert(led4["skipped_entrypoints"] == {"sdk-cli": 1}, "sdk session skipped and counted")
    _assert(led4["sources"]["skill_listing"]["median_chars"] == 200, "sdk listing excluded from median")
    led5 = cl.build_ledger(files_sdk, 10, 100, {}, {}, 0.25, include_sdk=True)
    _assert(led5["sources"]["skill_listing"]["samples"] == 4, "include_sdk measures sdk sessions too")
    os.remove(sdk)

    print("Test: no known record types anywhere raises LedgerFormatError")
    junk = os.path.join(d, "junk", "p", "j.jsonl")
    write_session(junk, [{"type": "user", "message": {"content": "hi"}}])
    try:
        cl.build_ledger([junk], 10, 100, {}, {}, 0.25)
        _assert(False, "expected LedgerFormatError")
    except cl.LedgerFormatError:
        _assert(True, "unrecognized format fails fast")


def test_cli(d):
    print("Test: main exit codes")
    empty = os.path.join(d, "only-sub")
    write_session(os.path.join(empty, "p", "s", "subagents", "agent-1.jsonl"),
                  [att({"type": "skill_listing", "content": "- a", "skillCount": 1})])
    cfg = os.path.join(d, "cfg-empty")
    os.makedirs(cfg, exist_ok=True)
    _assert(cl.main(["x", "--projects-dir", empty, "--config-dir", cfg, "--json"]) == 1, "only subagent transcripts -> exit 1")
    _assert(cl.main(["x", "--projects-dir", os.path.join(d, "nope"), "--config-dir", cfg]) == 1, "missing projects dir -> exit 1")
    _assert(cl.main(["x", "--samples"]) == 2, "missing flag value -> exit 2")
    sdk_only = os.path.join(d, "sdk-only")
    write_session(os.path.join(sdk_only, "p", "s.jsonl"),
                  [{"type": "user", "entrypoint": "sdk-py"}, att({"type": "skill_listing", "content": "- a", "skillCount": 1})])
    _assert(cl.main(["x", "--projects-dir", sdk_only, "--config-dir", cfg]) == 1, "only sdk sessions -> exit 1")
    _assert(cl.main(["x", "--projects-dir", sdk_only, "--config-dir", cfg, "--include-sdk"]) == 0, "--include-sdk measures them")
    good = os.path.join(d, "projects")
    _assert(cl.main(["x", "--projects-dir", good, "--config-dir", cfg]) == 0, "markdown run succeeds")
```

Add `test_build_ledger(d)` and `test_cli(d)` to `run()` after the earlier tests (`test_cli` must run after `test_build_ledger`, which creates `projects/`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test-context-ledger.py`
Expected: FAIL with `AttributeError: ... 'find_sessions'`.

- [ ] **Step 3: Write minimal implementation**

Append:

```python
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


def build_ledger(files, samples, max_sessions, hook_owners, skill_descs, tokens_per_byte, include_sdk=False):
    collected = {k: [] for k in ALL_SOURCES}
    format_errors = []
    skipped = {}
    scanned = 0
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
            "tokens_per_byte": tokens_per_byte, "sources": sources,
            "missing": [k for k in ALL_SOURCES if k not in sources], "format_errors": format_errors}


def _top(mapping, n=10):
    return sorted(mapping.items(), key=lambda kv: -kv[1])[:n]


def render_markdown(ledger):
    src = ledger["sources"]
    lines = ["# Measured Context Ledger", "",
             f"Sessions scanned: {ledger['scanned_sessions']}"
             + (" (skipped non-interactive: " + ", ".join(f"{k} {v}" for k, v in sorted(ledger["skipped_entrypoints"].items())) + ")"
                if ledger["skipped_entrypoints"] else ""), "",
             "| Source | Samples | ~Chars | ~Tokens |", "|---|---|---|---|"]
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
            "--samples": "10", "--max-sessions": "100", "--tokens-per-byte": "0.25"}
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
                              load_skill_descriptions(config_dir), tpb, include_sdk=include_sdk)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test-context-ledger.py`
Expected: all `ok`, final `All context-ledger tests passed.`

- [ ] **Step 5: Run against real data (smoke check)**

Run: `python3 scripts/context-ledger.py | head -40`
Expected: exit 0; table rows for Skill listing, Deferred tool names, MCP server instructions, Agent listing; the "Skills listed without descriptions" section lists several names. If it exits 2, stop and report: the real transcript format differs from the verified shapes.

- [ ] **Step 6: Commit**

```bash
git add scripts/context-ledger.py scripts/test-context-ledger.py
git commit -F - <<'EOF'
feat: add context-ledger.py with per-type sampling and CLI

Claude-Session: https://claude.ai/code/session_01CJQqC6KKB82TVmLiQxj9Kr
EOF
```

---

### Task 5: Wire into token-budget, config, validation, and docs

**Files:**
- Modify: `scripts/init-config.py` (`CONFIG_VERSION`, `DEFAULT_CONFIG["thresholds"]`)
- Modify: `scripts/test-init-config.py`
- Modify: `scripts/validate.sh` (compile block after `count-installed-plugins.py`; test block after `test-init-config.py`)
- Modify: `.github/workflows/ci.yml` (`test-scripts` job)
- Modify: `skills/token-budget/SKILL.md` (step 3 intro, step 4 table)
- Modify: `README.md` ("What it checks")

**Interfaces:**
- Consumes: `context-ledger.py --json` output shape from Task 4.

- [ ] **Step 1: Write the failing config test**

In `scripts/test-init-config.py`, inside the existing test runner after the `context_windows` assertions, add:

```python
    print("Test: context ledger thresholds have defaults and migrate in")
    th = ic.DEFAULT_CONFIG["thresholds"]
    _assert(th["context_ledger_samples"] == 10, "context_ledger_samples default 10")
    _assert(th["context_ledger_max_sessions"] == 100, "context_ledger_max_sessions default 100")
    migrated_th = ic.migrate_config({"version": "1.4", "thresholds": {"token_warning": 1}})["thresholds"]
    _assert(migrated_th["context_ledger_samples"] == 10 and migrated_th["token_warning"] == 1,
            "migration adds new keys and keeps customized ones")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 scripts/test-init-config.py`
Expected: FAIL with `KeyError: 'context_ledger_samples'`.

- [ ] **Step 3: Add the defaults**

In `scripts/init-config.py`, change `CONFIG_VERSION = "1.4"` to `CONFIG_VERSION = "1.5"`, and in `DEFAULT_CONFIG["thresholds"]` replace

```python
        "claude_md_verbose_lines": 200
```

with

```python
        "claude_md_verbose_lines": 200,
        "context_ledger_samples": 10,
        "context_ledger_max_sessions": 100
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 scripts/test-init-config.py`
Expected: all `ok`.

- [ ] **Step 5: Add the new script to validate.sh and CI**

In `scripts/validate.sh`, after the `count-installed-plugins.py` compile block, add:

```bash
if python3 -m py_compile "$PLUGIN_ROOT/scripts/context-ledger.py" 2>/dev/null; then
  echo "  ✓ context-ledger.py: syntax valid"
else
  echo "  ✗ context-ledger.py: syntax errors"
  ((ERRORS++))
fi
```

After the `test-init-config.py` test block, add:

```bash
# context-ledger: deterministic fixture-based test
if python3 "$PLUGIN_ROOT/scripts/test-context-ledger.py" >/dev/null 2>&1; then
  echo "  ✓ test-context-ledger.py: all assertions pass"
else
  echo "  ✗ test-context-ledger.py: FAILED"
  ((ERRORS++))
fi
```


In `.github/workflows/ci.yml`, in the `test-scripts` job after the "Test config initialization" step, add:

```yaml
      - name: Run context ledger tests
        run: python3 scripts/test-context-ledger.py
```

- [ ] **Step 6: Run validation**

Run: `bash scripts/validate.sh`
Expected: exit 0, including `✓ context-ledger.py: syntax valid` and `✓ test-context-ledger.py: all assertions pass`.

- [ ] **Step 7: Wire token-budget**

In `skills/token-budget/SKILL.md`:

(a) In step 2, add to the config reads:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.context_ledger_samples
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.context_ledger_max_sessions
```

(b) Insert at the start of step 3, before `**2a. CLAUDE.md files**`:

````markdown
   **2.0 Measured context ledger (run first)**

   Claude Code records what it injected at session start in the transcripts.
   Measure that directly:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/context-ledger.py" --json \
     --samples <context_ledger_samples> --max-sessions <context_ledger_max_sessions> \
     --tokens-per-byte <tokens_per_byte>
   ```

   - Exit 0: use `sources.*.median_tokens` for every source it reports
     (skill listing, deferred tool names, MCP server instructions, agent
     listing, SessionStart hook context, and each instruction file). These
     replace the estimates in 2a, 2d, 2e, 2f, and 2g for those sources.
   - Sources in `missing`: fall back to the estimate for that source only,
     and mark its row "est.".
   - Exit 1 (no transcripts) or 2 (format not recognized): tell the user
     the ledger is unavailable and why (quote stderr), then use estimates
     for every row, all marked "est.". Do not hide this.

   The 2a to 2g measurements below still run: they supply rows the ledger
   does not cover (per-plugin breakdown, rules not seen loaded) and the
   fallbacks above.
````

(c) In step 4's breakdown table, change the header to `| Source | Bytes | ~Tokens | % of Window | Measured? | Notes |` and document: "Measured?" is `measured (N sessions)` using the row's `samples`, or `est.`. Add these rows (ledger-backed) in place of the old MCP/skill/agent/hook rows:

```
| Skill listing (N skills) | - | X | X% | measured (N) | Listed every turn |
| Deferred tool names (N names) | - | X | X% | measured (N) | Names only; schemas load on use |
| MCP server instructions | - | X | X% | measured (N) | Per-server instruction blocks |
| Agent listing | - | X | X% | measured (N) | Agent types and descriptions |
| SessionStart hook context | - | X | X% | measured (N) | Injected once per session |
```

(d) After "Top 5 Token Consumers", add:

```markdown
   ## Where the ledger points

   - Top 5 servers by deferred-name chars and by MCP instruction chars
     (from `by_server`), top 5 plugins by skill listing chars
     (`skill_listing.by_owner`), and hook context by owner
     (`hook_context.by_owner`), each named so the user can disable it.
   - If `sources.skill_listing.dropped` is non-empty: "Your skill listing
     hit its size budget. N skills appear by name only, so Claude cannot
     match them to a request:" then the names. Suggest disabling unused
     skill-heavy plugins (see `/moltbloat:usage`).
   - If `hook_context.unparsed_outputs` > 0: note that some SessionStart
     hooks print non-JSON output, which is not counted as context.
```

(e) Replace the old line "Multiply tool count by 350 (midpoint estimate)." in 2d with: "Only used when the ledger reports `deferred_tools` missing. With deferred tools, only names are in context until a tool is loaded, so this estimate overstates cost; label it est."

- [ ] **Step 8: Docs**

In `README.md` under "## What it checks", add a bullet:

```markdown
- **Measured context**: reads what each session actually loaded from Claude Code's transcripts (skill listing, deferred MCP tool names, MCP instructions, agent listing, SessionStart hook output, instruction files) instead of estimating, and flags skills whose descriptions were dropped because the listing hit its size budget.
```

`CLAUDE.md` is not edited in this slice: its command list uses em-dash separators, and rewriting that list is a separate change.

- [ ] **Step 9: Run everything**

Run: `bash scripts/validate.sh && python3 scripts/test-context-ledger.py && python3 scripts/test-init-config.py`
Expected: all pass, exit 0.

- [ ] **Step 10: Commit**

```bash
git add scripts/init-config.py scripts/test-init-config.py scripts/validate.sh .github/workflows/ci.yml skills/token-budget/SKILL.md README.md
git commit -F - <<'EOF'
feat: token-budget uses measured context ledger where available

Claude-Session: https://claude.ai/code/session_01CJQqC6KKB82TVmLiQxj9Kr
EOF
```
