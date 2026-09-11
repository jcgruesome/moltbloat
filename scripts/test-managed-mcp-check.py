#!/usr/bin/env python3
"""Tests for managed-mcp-check.py: managedMcpServers collision detection.

Run: python3 scripts/test-managed-mcp-check.py
"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("managed_mcp_check", os.path.join(HERE, "managed-mcp-check.py"))
mmc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mmc)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def run():
    with tempfile.TemporaryDirectory() as d:
        config_dir = os.path.join(d, "dotclaude")
        os.makedirs(config_dir, exist_ok=True)

        print("Test: managed settings file entirely absent -> no error, empty result")
        missing_path = os.path.join(d, "does-not-exist", "managed-settings.json")
        managed = mmc.load_managed_servers(missing_path)
        _assert(managed == {}, "absent managed-settings.json yields empty dict, no exception")
        result_absent = mmc.scan(managed, mmc.collect_local_servers(config_dir, None))
        _assert(result_absent == {"managed_server_count": 0, "managed_servers": [], "collisions": []},
                "absent managed settings -> empty scan result")

        print("Test: managed servers present + colliding with a plugin MCP -> flagged")
        plugin_mcp = os.path.join(config_dir, "plugins", "cache", "acme-market", "playwright-tools", "1.0.0", ".mcp.json")
        write_json(plugin_mcp, {"mcpServers": {"playwright": {"command": "npx", "args": ["playwright-mcp"]}}})
        managed_settings_path = os.path.join(d, "managed-settings.json")
        write_json(managed_settings_path, {
            "managedMcpServers": {
                "playwright": {"type": "http", "url": "https://mcp.example.com/playwright"},
                "search": {"type": "http", "url": "https://search.example.com/mcp"},
            }
        })

        managed = mmc.load_managed_servers(managed_settings_path)
        _assert(set(managed.keys()) == {"playwright", "search"}, "managed servers loaded from managed-settings.json")

        local_sources = mmc.collect_local_servers(config_dir, None)
        _assert("playwright" in local_sources, "plugin-provided .mcp.json server discovered")

        result = mmc.scan(managed, local_sources)
        _assert(result["managed_server_count"] == 2, "both managed servers counted")
        collision_names = {c["name"] for c in result["collisions"]}
        _assert(collision_names == {"playwright"}, "only the colliding server name is flagged")
        hit = result["collisions"][0]
        _assert(hit["severity"] == "CRITICAL", "collision severity matches the existing duplicate-server CRITICAL model")
        _assert(any(src.startswith("plugin:") for src in hit["local_sources"]), "collision names the owning plugin source")

        print("Test: managed servers present + no collision -> not flagged")
        write_json(managed_settings_path, {
            "managedMcpServers": {
                "records": {"type": "http", "url": "https://records.example.com/mcp"},
            }
        })
        managed_no_collision = mmc.load_managed_servers(managed_settings_path)
        result_no_collision = mmc.scan(managed_no_collision, local_sources)
        _assert(result_no_collision["collisions"] == [], "managed server with no local counterpart isn't flagged")

        print("Test: global and per-project mcpServers cross-referenced via state file")
        state_path = os.path.join(d, ".claude.json")
        write_json(state_path, {
            "mcpServers": {"search": {"command": "search-server"}},
            "projects": {"/Users/x/proj": {"mcpServers": {"records": {"command": "records-server"}}}},
        })
        local_sources_state = mmc.collect_local_servers(config_dir, state_path)
        _assert("search" in local_sources_state and "global" in local_sources_state["search"],
                "global mcpServers entry recorded with 'global' source label")
        _assert(any(s.startswith("project:") for s in local_sources_state["records"]),
                "per-project mcpServers entry recorded with a project source label")

        managed_both = mmc.load_managed_servers(managed_settings_path)  # {"records": ...} from above
        managed_both["search"] = {"type": "http", "url": "https://search.example.com/mcp"}
        result_both = mmc.scan(managed_both, local_sources_state)
        collision_names_both = {c["name"] for c in result_both["collisions"]}
        _assert(collision_names_both == {"search", "records"},
                "collisions detected against both global and per-project scopes")

        print("Test: malformed managed-settings.json does not raise")
        bad_path = os.path.join(d, "bad-managed-settings.json")
        with open(bad_path, "w") as f:
            f.write("{ not valid json")
        _assert(mmc.load_managed_servers(bad_path) == {}, "malformed JSON yields empty dict, no exception")

    print("\nAll managed-mcp-check tests passed")


if __name__ == "__main__":
    run()
