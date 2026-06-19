#!/usr/bin/env python3
"""Mine Claude Code's native session transcripts for real tool/MCP/skill/agent usage.

Claude Code records every session under ~/.claude/projects/**/*.jsonl. Each `assistant`
line carries `tool_use` blocks and a per-line ISO-8601 `timestamp`. This script streams
those transcripts and emits a JSON aggregate of what was actually used, with first/last
use timestamps and session counts — a retroactive usage record available immediately,
unlike moltbloat's own hook data which must accumulate over weeks.

Usage:
    python3 parse-history.py [--since DAYS] [--json]

Output: a single JSON object on stdout (see aggregate()). Fails fast (non-zero exit) if
~/.claude/projects does not exist.
"""
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def categorize(name, inp):
    """Map a tool_use (name, input) to (category, key, plugin).

    Categories: "mcp", "skill", "agent", "tool".
    `plugin` is the owning plugin name for plugin-provided MCP servers, else None.
    Returns None for entries we cannot key (e.g. missing name).
    """
    if not name:
        return None
    inp = inp or {}

    if name.startswith("mcp__"):
        # mcp__<server>__<tool>  or  mcp__plugin_<plugin>_<server>__<tool>
        body = name[len("mcp__"):]
        server = body.split("__", 1)[0] if "__" in body else body
        plugin = None
        if server.startswith("plugin_"):
            # plugin_<plugin>_<server> — the plugin name is the first segment after
            # "plugin_". Server token is kept whole as the key for stable identity.
            rest = server[len("plugin_"):]
            plugin = rest.split("_", 1)[0] if "_" in rest else rest
        return ("mcp", server, plugin)

    if name == "Skill":
        return ("skill", inp.get("skill", "?"), None)

    if name in ("Task", "Agent"):
        return ("agent", inp.get("subagent_type", "?"), None)

    return ("tool", name, None)


def _parse_ts(ts):
    """Parse an ISO-8601 timestamp (trailing Z) into an aware UTC datetime, or None."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _record(bucket, key, ts, plugin, session_id):
    entry = bucket.get(key)
    if entry is None:
        entry = {
            "count": 0,
            "first_used": ts,
            "last_used": ts,
            "plugin": plugin,
            "_sessions": set(),
        }
        bucket[key] = entry
    entry["count"] += 1
    if ts:
        if not entry["last_used"] or ts > entry["last_used"]:
            entry["last_used"] = ts
        if not entry["first_used"] or ts < entry["first_used"]:
            entry["first_used"] = ts
    if plugin and not entry["plugin"]:
        entry["plugin"] = plugin
    entry["_sessions"].add(session_id)


def aggregate(files, since_days=None, now=None):
    """Aggregate usage across the given transcript file paths.

    `since_days` drops tool_uses whose timestamp is older than N days before `now`.
    `now` defaults to the current UTC time (injectable for tests).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=since_days) if since_days is not None else None

    items = {"tool": {}, "mcp": {}, "skill": {}, "agent": {}}
    scanned_files = 0
    scanned_lines = 0
    tool_uses = 0

    for fp in files:
        try:
            fh = open(fp, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned_files += 1
        with fh:
            for line in fh:
                scanned_lines += 1
                # Cheap guard: skip lines that cannot contain a tool_use.
                if '"tool_use"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                ts = obj.get("timestamp")
                if cutoff is not None:
                    dt = _parse_ts(ts)
                    if dt is None or dt < cutoff:
                        continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    cat = categorize(block.get("name"), block.get("input"))
                    if cat is None:
                        continue
                    category, key, plugin = cat
                    _record(items[category], key, ts, plugin, fp)
                    tool_uses += 1

    # Finalize: replace the session set with its size.
    for bucket in items.values():
        for entry in bucket.values():
            entry["sessions"] = len(entry.pop("_sessions"))

    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "since_days": since_days,
        "scanned": {
            "files": scanned_files,
            "lines": scanned_lines,
            "tool_uses": tool_uses,
        },
        "items": items,
    }


def find_transcripts(projects_dir=PROJECTS_DIR):
    """Recursively find all transcript .jsonl files under projects_dir."""
    return glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True)


def main(argv):
    since_days = None
    args = argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--since":
            i += 1
            if i >= len(args):
                sys.stderr.write("error: --since requires a number of days\n")
                return 2
            try:
                since_days = int(args[i])
            except ValueError:
                sys.stderr.write("error: --since expects an integer\n")
                return 2
        elif a == "--json":
            pass  # default and only output form
        else:
            sys.stderr.write(f"error: unknown argument: {a}\n")
            return 2
        i += 1

    if not os.path.isdir(PROJECTS_DIR):
        sys.stderr.write(
            f"error: {PROJECTS_DIR} not found — no Claude Code history to analyze\n"
        )
        return 1

    files = find_transcripts()
    result = aggregate(files, since_days=since_days)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
