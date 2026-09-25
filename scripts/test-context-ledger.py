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


def run():
    with tempfile.TemporaryDirectory() as d:
        test_extract_session(d)
        test_skill_overflow(d)
    print("All context-ledger tests passed.")


if __name__ == "__main__":
    run()
