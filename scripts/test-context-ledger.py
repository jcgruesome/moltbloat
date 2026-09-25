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


def run():
    with tempfile.TemporaryDirectory() as d:
        test_extract_session(d)
        test_skill_overflow(d)
        test_hook_owners(d)
        test_build_ledger(d)
        test_cli(d)
    print("All context-ledger tests passed.")


if __name__ == "__main__":
    run()
