#!/usr/bin/env python3
"""Detect org-managed MCP servers (`managedMcpServers`) and cross-reference
against local MCP servers (global, per-project, plugin `.mcp.json`) for name
collisions. `managedMcpServers` centrally pushes servers to every user via a
system `managed-settings.json` outside `~/.claude/`
(docs: https://code.claude.com/docs/en/managed-mcp) -- moltbloat's Check 2 and
Check 11 never see it otherwise. Absent/unreadable file -> common case, not
an error.

Usage: python3 managed-mcp-check.py [CONFIG_DIR] [--managed-settings PATH] [--json]
"""
import glob
import json
import os
import sys

MANAGED_SETTINGS_PATHS = {
    "darwin": "/Library/Application Support/ClaudeCode/managed-settings.json",
    "linux": "/etc/claude-code/managed-settings.json",
}


def default_managed_settings_path():
    return MANAGED_SETTINGS_PATHS.get(sys.platform, MANAGED_SETTINGS_PATHS["linux"])


def load_managed_servers(managed_settings_path):
    """Read `managedMcpServers` from a managed-settings.json file.

    Returns {} if the file is absent, unreadable, or malformed -- absence is
    the common case (no org-managed settings deployed), not an error.
    """
    if not managed_settings_path or not os.path.isfile(managed_settings_path):
        return {}
    try:
        with open(managed_settings_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("managedMcpServers") or {}


def collect_local_servers(config_dir, state_path):
    """Build {server_name: [source_label, ...]} for MCP servers already visible
    to moltbloat: global config, per-project entries, and plugin-provided
    `.mcp.json` files.
    """
    sources = {}

    def add(name, label):
        sources.setdefault(name, []).append(label)

    if state_path and os.path.isfile(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            d = {}
        for name in (d.get("mcpServers") or {}):
            add(name, "global")
        for path, v in (d.get("projects") or {}).items():
            for name in ((v or {}).get("mcpServers") or {}):
                add(name, f"project:{path}")

    settings_path = os.path.join(config_dir, "settings.json")
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                d = json.load(f)
            for name in (d.get("mcpServers") or {}):
                add(name, "settings.json")
        except (OSError, json.JSONDecodeError):
            pass

    mcp_glob = os.path.join(config_dir, "plugins", "cache", "*", "*", "*", ".mcp.json")
    for mcp_file in glob.glob(mcp_glob):
        try:
            with open(mcp_file, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        plugin = os.path.basename(os.path.dirname(mcp_file))
        for name in (d.get("mcpServers") or {}):
            add(name, f"plugin:{plugin}")

    return sources


def scan(managed_servers, local_sources):
    """Cross-reference managed servers against local sources for name collisions.

    Same severity model as the existing duplicate-server-names check: CRITICAL
    when the same MCP name is loaded from 2+ sources (here, a managed source
    plus at least one local one) -- it causes the same tool-name conflicts.
    """
    collisions = []
    for name in sorted(managed_servers):
        local = local_sources.get(name)
        if local:
            collisions.append({
                "name": name,
                "managed": True,
                "local_sources": local,
                "severity": "CRITICAL",
            })
    return {
        "managed_server_count": len(managed_servers),
        "managed_servers": sorted(managed_servers.keys()),
        "collisions": collisions,
    }


def render_markdown(result, managed_settings_path):
    lines = ["# Managed MCP Server Check", "", f"Managed settings source: {managed_settings_path}"]
    if result["managed_server_count"] == 0:
        lines.append("No `managedMcpServers` found (no org-managed MCP servers deployed to this machine).")
        return "\n".join(lines)
    lines.append(f"Managed servers found: {result['managed_server_count']} ({', '.join(result['managed_servers'])}).")
    lines.append("")
    if not result["collisions"]:
        lines.append("No collisions between managed servers and locally configured MCP servers.")
        return "\n".join(lines)
    lines.append("| Managed server | Local sources | Severity |")
    lines.append("|---|---|---|")
    for c in result["collisions"]:
        lines.append(f"| {c['name']} | {', '.join(c['local_sources'])} | {c['severity']} |")
    return "\n".join(lines)


def main(argv):
    args = argv[1:]
    as_json = False
    managed_settings_path = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--managed-settings":
            i += 1
            if i >= len(args):
                sys.stderr.write("error: --managed-settings requires a path\n")
                return 2
            managed_settings_path = args[i]
        else:
            positional.append(a)
        i += 1

    config_dir = os.path.expanduser(positional[0] if positional else os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"))
    if managed_settings_path is None:
        managed_settings_path = default_managed_settings_path()

    state_candidates = [os.path.join(os.path.expanduser("~"), ".claude.json"),
                        os.path.join(config_dir, ".claude.json")]
    state_path = next((p for p in state_candidates if os.path.isfile(p)), None)

    managed_servers = load_managed_servers(managed_settings_path)
    local_sources = collect_local_servers(config_dir, state_path)
    result = scan(managed_servers, local_sources)

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(render_markdown(result, managed_settings_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
