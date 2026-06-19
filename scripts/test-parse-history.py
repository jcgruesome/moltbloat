#!/usr/bin/env python3
"""Tests for parse-history.py — the native-transcript usage miner.

Run: python3 scripts/test-parse-history.py
Exits non-zero on first failure so it can gate CI.
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# Import the hyphenated module by path.
_spec = importlib.util.spec_from_file_location(
    "parse_history", os.path.join(HERE, "parse-history.py")
)
ph = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ph)


def _assert(cond, msg):
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def _assistant_line(ts, blocks):
    return json.dumps(
        {"type": "assistant", "timestamp": ts, "message": {"content": blocks}}
    )


def _tool_use(name, inp=None):
    return {"type": "tool_use", "name": name, "input": inp or {}}


def make_fixture(path):
    old = "2026-01-01T00:00:00.000Z"   # well before `now`
    recent = "2026-06-18T12:00:00.000Z"
    lines = [
        # core tools
        _assistant_line(old, [_tool_use("Bash"), _tool_use("Read")]),
        _assistant_line(recent, [_tool_use("Bash")]),
        # mcp with plugin-owned server
        _assistant_line(recent, [_tool_use("mcp__plugin_figma_figma__get_metadata")]),
        # mcp claude.ai connector (no plugin_ prefix)
        _assistant_line(old, [_tool_use("mcp__claude_ai_Linear__list_issues")]),
        # skill
        _assistant_line(recent, [_tool_use("Skill", {"skill": "moltbloat:audit"})]),
        # agent
        _assistant_line(old, [_tool_use("Task", {"subagent_type": "general-purpose"})]),
        # a non-assistant line and a malformed line — must be skipped
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        "{ this is not valid json",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def run():
    now = datetime(2026, 6, 19, 0, 0, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as d:
        fx = os.path.join(d, "session.jsonl")
        make_fixture(fx)

        print("Test: full aggregate")
        res = ph.aggregate([fx], now=now)
        items = res["items"]

        _assert(items["tool"]["Bash"]["count"] == 2, "Bash counted twice")
        _assert(items["tool"]["Read"]["count"] == 1, "Read counted once")
        _assert(
            items["tool"]["Bash"]["last_used"] == "2026-06-18T12:00:00.000Z",
            "Bash last_used is the most recent timestamp",
        )
        _assert(
            items["tool"]["Bash"]["first_used"] == "2026-01-01T00:00:00.000Z",
            "Bash first_used is the earliest timestamp",
        )

        _assert("plugin_figma_figma" in items["mcp"], "mcp server keyed by raw server token")
        _assert(
            items["mcp"]["plugin_figma_figma"]["plugin"] == "figma",
            "plugin extracted from mcp__plugin_<plugin>_<server>__tool",
        )
        _assert(
            items["mcp"]["claude_ai_Linear"]["plugin"] is None,
            "claude.ai connector has no owning plugin",
        )

        _assert(items["skill"]["moltbloat:audit"]["count"] == 1, "skill keyed by input.skill")
        _assert(
            items["agent"]["general-purpose"]["count"] == 1,
            "agent keyed by input.subagent_type",
        )

        _assert(res["scanned"]["files"] == 1, "one file scanned")
        _assert(res["scanned"]["tool_uses"] == 7, "seven tool_uses extracted (malformed skipped)")

        print("Test: --since window excludes old lines")
        res2 = ph.aggregate([fx], since_days=30, now=now)
        items2 = res2["items"]
        _assert(items2["tool"]["Bash"]["count"] == 1, "only the recent Bash survives since=30")
        _assert("Read" not in items2["tool"], "old-only tool dropped by since window")
        _assert(
            "general-purpose" not in items2.get("agent", {}),
            "old agent call dropped by since window",
        )
        _assert(
            "plugin_figma_figma" in items2["mcp"],
            "recent mcp call retained within since window",
        )

        print("Test: sessions counted distinctly across files")
        fx2 = os.path.join(d, "session2.jsonl")
        make_fixture(fx2)  # a second distinct transcript with the same shape
        res3 = ph.aggregate([fx, fx2], now=now)
        _assert(res3["items"]["tool"]["Bash"]["sessions"] == 2, "distinct files counted as 2 sessions")
        _assert(res3["items"]["tool"]["Bash"]["count"] == 4, "counts aggregate across files")

    print("\n✓ All parse-history tests passed")


if __name__ == "__main__":
    run()
