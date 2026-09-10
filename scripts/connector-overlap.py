#!/usr/bin/env python3
"""Detect overlap between claude.ai org-managed connectors and local plugins/MCPs.

Connectors (`mcp__claude_ai_<Service>__*`) are injected per-session by the harness
from org settings and never touch `.claude.json`/`settings.json` — but their tool
names DO land in session transcripts, the same ground truth `/moltbloat:usage`
mines. This scans that source and flags local servers whose tools structurally
overlap a connector's (shared tool-name suffixes, with a name-similarity
fallback) — no hardcoded service list.

Usage: python3 connector-overlap.py [PROJECTS_DIR] [--json] [--min-shared N]
Output: markdown, or one JSON object with --json. Fails fast if PROJECTS_DIR is missing.
"""
import glob
import json
import os
import re
import sys

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
CONNECTOR_PREFIX = "claude_ai_"
DEFAULT_MIN_SHARED = 2
# A tool suffix on more than this many distinct servers is a naming convention
# (auth handshakes, list/get verbs), not evidence of overlap — exclude it.
DEFAULT_BOILERPLATE_DF = 3

# A full `mcp__<server>__<tool>` token, wherever it appears in a transcript line —
# a tool_use block, or plain text in a deferred-tools listing never invoked.
TOOL_TOKEN_RE = re.compile(r"mcp__[A-Za-z0-9_\-]+")


def split_tool_token(token):
    """`mcp__<server>__<tool>` -> (server, tool). None if malformed."""
    body = token[len("mcp__"):]
    if "__" not in body:
        return None
    server, tool = body.split("__", 1)
    if not server or not tool:
        return None
    return server, tool


def plugin_of(server):
    """Extract the owning plugin name from a `plugin_<plugin>_<server>` token, else None."""
    if not server.startswith("plugin_"):
        return None
    rest = server[len("plugin_"):]
    return rest.split("_", 1)[0] if "_" in rest else rest


def normalize(name):
    """Lowercase, strip non-alphanumerics, for loose name-similarity matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def names_similar(a, b, min_len=4):
    """True if the normalized forms overlap by containment, above a noise floor."""
    na, nb = normalize(a), normalize(b)
    if len(na) < min_len or len(nb) < min_len:
        return False
    return na in nb or nb in na


def scan(files, min_shared=DEFAULT_MIN_SHARED, boilerplate_df=DEFAULT_BOILERPLATE_DF):
    """Scan transcript files for claude.ai connectors and local server overlap.

    Returns {"connectors": {...}, "local_servers": {...}, "overlaps": [...]}.
    """
    connectors = {}
    local_servers = {}
    scanned_files = 0

    for fp in files:
        try:
            fh = open(fp, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned_files += 1
        with fh:
            for line in fh:
                if "mcp__" not in line:
                    continue
                for token in TOOL_TOKEN_RE.findall(line):
                    split = split_tool_token(token)
                    if split is None:
                        continue
                    server, tool = split
                    if server.startswith(CONNECTOR_PREFIX):
                        bucket = connectors.setdefault(server, {"tools": set()})
                        bucket["tools"].add(tool)
                    else:
                        bucket = local_servers.setdefault(
                            server, {"tools": set(), "plugin": plugin_of(server)}
                        )
                        bucket["tools"].add(tool)

    # Document frequency per tool suffix across all servers — filters boilerplate.
    tool_df = {}
    for data in list(connectors.values()) + list(local_servers.values()):
        for tool in data["tools"]:
            tool_df[tool] = tool_df.get(tool, 0) + 1
    distinctive = {tool for tool, df in tool_df.items() if df <= boilerplate_df}

    overlaps = []
    for c_server, c_data in connectors.items():
        service = c_server[len(CONNECTOR_PREFIX):]
        for l_server, l_data in local_servers.items():
            shared = c_data["tools"] & l_data["tools"] & distinctive
            name_hit = names_similar(service, l_server) or (
                l_data["plugin"] and names_similar(service, l_data["plugin"])
            )
            tool_hit = len(shared) >= min_shared
            if not (name_hit or tool_hit):
                continue
            if name_hit and tool_hit:
                basis = "both"
            elif tool_hit:
                basis = "tools"
            else:
                basis = "name"
            overlaps.append({
                "connector": c_server,
                "local": l_server,
                "local_plugin": l_data["plugin"],
                "match_basis": basis,
                "shared_tool_count": len(shared),
                "connector_tool_count": len(c_data["tools"]),
                "local_tool_count": len(l_data["tools"]),
                "sample_shared_tools": sorted(shared)[:8],
            })

    overlaps.sort(key=lambda o: -o["shared_tool_count"])

    return {
        "scanned_files": scanned_files,
        "connectors": {
            k: {"tool_count": len(v["tools"]), "sample_tools": sorted(v["tools"])[:8]}
            for k, v in connectors.items()
        },
        "local_servers": {
            k: {"tool_count": len(v["tools"]), "plugin": v["plugin"], "sample_tools": sorted(v["tools"])[:8]}
            for k, v in local_servers.items()
        },
        "overlaps": overlaps,
    }


def find_transcripts(projects_dir):
    return glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True)


def render_markdown(result):
    lines = ["# Claude.ai Connector Overlap", ""]
    lines.append(f"Scanned {result['scanned_files']} transcript file(s).")
    lines.append(f"Connectors seen: {len(result['connectors'])}. Local MCP/plugin servers seen: {len(result['local_servers'])}.")
    lines.append("")
    if not result["overlaps"]:
        lines.append("No overlap detected between claude.ai connectors and local plugins/MCPs.")
        return "\n".join(lines)
    lines.append("| Connector | Local server | Basis | Shared tools | Sample |")
    lines.append("|---|---|---|---|---|")
    for o in result["overlaps"]:
        local_label = f"{o['local']} (plugin: {o['local_plugin']})" if o["local_plugin"] else o["local"]
        sample = ", ".join(o["sample_shared_tools"]) or "-"
        lines.append(
            f"| {o['connector']} | {local_label} | {o['match_basis']} | "
            f"{o['shared_tool_count']}/{min(o['connector_tool_count'], o['local_tool_count'])} | {sample} |"
        )
    return "\n".join(lines)


def main(argv):
    args = argv[1:]
    projects_dir = PROJECTS_DIR
    as_json = False
    min_shared = DEFAULT_MIN_SHARED
    boilerplate_df = DEFAULT_BOILERPLATE_DF

    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--min-shared":
            i += 1
            if i >= len(args):
                sys.stderr.write("error: --min-shared requires an integer\n")
                return 2
            min_shared = int(args[i])
        elif a == "--boilerplate-df":
            i += 1
            if i >= len(args):
                sys.stderr.write("error: --boilerplate-df requires an integer\n")
                return 2
            boilerplate_df = int(args[i])
        else:
            positional.append(a)
        i += 1

    if positional:
        projects_dir = positional[0]

    if not os.path.isdir(projects_dir):
        sys.stderr.write(f"error: projects dir not found: {projects_dir}\n")
        return 1

    files = find_transcripts(projects_dir)
    result = scan(files, min_shared=min_shared, boilerplate_df=boilerplate_df)

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
