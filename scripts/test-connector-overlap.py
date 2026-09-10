#!/usr/bin/env python3
"""Tests for connector-overlap.py — claude.ai connector vs local plugin/MCP overlap.

Run: python3 scripts/test-connector-overlap.py
Exits non-zero on first failure so it can gate CI.
"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location(
    "connector_overlap", os.path.join(HERE, "connector-overlap.py")
)
co = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(co)


def _assert(cond, msg):
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def write_fixture(path, lines):
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def run():
    with tempfile.TemporaryDirectory() as d:

        print("Test: extracts claude_ai connectors and local mcp servers")
        fx = os.path.join(d, "session.jsonl")
        write_fixture(fx, [
            # A deferred-tool listing (plain text, never invoked) — must still count.
            json.dumps({"type": "system", "message": {
                "content": "deferred tools: mcp__claude_ai_Reshape_Design_MCP__rxds_apply_unified_deck, "
                            "mcp__claude_ai_Reshape_Design_MCP__rxds_ds_search, "
                            "mcp__claude_ai_Reshape_Design_MCP__rxds_illustrate"
            }}),
            # The local plugin exposing near-identical tool names.
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__plugin_reshapex-design_rxds__rxds_apply_unified_deck", "input": {}},
                {"type": "tool_use", "name": "mcp__plugin_reshapex-design_rxds__rxds_ds_search", "input": {}},
            ]}}),
            # An unrelated connector with no local counterpart.
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__claude_ai_Gmail__send_message", "input": {}},
            ]}}),
            "{ not valid json",
        ])

        result = co.scan([fx])

        _assert(
            "claude_ai_Reshape_Design_MCP" in result["connectors"],
            "claude_ai_Reshape_Design_MCP recognized as a connector",
        )
        _assert(
            "claude_ai_Gmail" in result["connectors"],
            "claude_ai_Gmail recognized as a connector",
        )
        _assert(
            "plugin_reshapex-design_rxds" in result["local_servers"],
            "local plugin server recorded",
        )
        _assert(
            result["local_servers"]["plugin_reshapex-design_rxds"]["plugin"] == "reshapex-design",
            "plugin name extracted from plugin_<plugin>_<server> token",
        )

        print("Test: flags tool-suffix overlap, not name-only matches")
        overlaps = {o["connector"]: o for o in result["overlaps"]}
        _assert(
            "claude_ai_Reshape_Design_MCP" in overlaps,
            "overlap detected between claude_ai_Reshape_Design_MCP and local plugin",
        )
        ov = overlaps["claude_ai_Reshape_Design_MCP"]
        _assert(ov["local"] == "plugin_reshapex-design_rxds", "overlap paired with the right local server")
        _assert(ov["shared_tool_count"] == 2, "two shared tool suffixes counted")
        _assert(
            "rxds_apply_unified_deck" in ov["sample_shared_tools"],
            "shared tool names surfaced as evidence",
        )
        _assert(
            "claude_ai_Gmail" not in overlaps,
            "connector with no local counterpart produces no overlap finding",
        )

        print("Test: name-based fallback catches overlap with zero shared tools")
        fx2 = os.path.join(d, "session2.jsonl")
        write_fixture(fx2, [
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__claude_ai_Slack__send_message", "input": {}},
            ]}}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__plugin_slack_slack__slack_send_message", "input": {}},
            ]}}),
        ])
        result2 = co.scan([fx2])
        overlaps2 = {o["connector"]: o for o in result2["overlaps"]}
        _assert("claude_ai_Slack" in overlaps2, "name-similar connector/plugin pair flagged")
        _assert(overlaps2["claude_ai_Slack"]["match_basis"] in ("name", "both"), "match basis records name similarity")

        print("Test: no overlaps when nothing local matches")
        fx3 = os.path.join(d, "session3.jsonl")
        write_fixture(fx3, [
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__claude_ai_Neon__authenticate", "input": {}},
            ]}}),
        ])
        result3 = co.scan([fx3])
        _assert(result3["overlaps"] == [], "isolated connector produces no overlap findings")

    print("\n✓ All connector-overlap tests passed")


if __name__ == "__main__":
    run()
