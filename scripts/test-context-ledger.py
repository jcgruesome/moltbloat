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
