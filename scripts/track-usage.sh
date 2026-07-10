#!/bin/bash
# Lightweight usage tracker — logs tool/skill/agent invocations to ~/.moltbloat/usage.jsonl
# Called by PostToolUse hook. Receives the hook payload (tool_name, tool_input, ...) as JSON on stdin.
# Typically completes in under 50ms; hard timeout of 2 seconds set in hooks.json.

set -e

USAGE_DIR="$HOME/.moltbloat"
USAGE_FILE="$USAGE_DIR/usage.jsonl"
ERROR_LOG="$USAGE_DIR/errors.log"

# Ensure directory exists
mkdir -p "$USAGE_DIR" 2>/dev/null || {
    echo "[moltbloat] Error: Cannot create $USAGE_DIR" >&2
    exit 1
}

export MOLTBLOAT_USAGE_FILE="$USAGE_FILE"
export MOLTBLOAT_ERROR_LOG="$ERROR_LOG"

PYSCRIPT=$(cat <<'PYEOF'
import sys, json, fcntl, re, time, os

usage_file = os.environ["MOLTBLOAT_USAGE_FILE"]
error_log = os.environ["MOLTBLOAT_ERROR_LOG"]

def log_error(msg):
    try:
        with open(error_log, "a") as f:
            f.write("[" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "] " + msg + "\n")
    except Exception:
        pass

try:
    payload = json.load(sys.stdin)
except Exception as e:
    log_error("Failed to parse stdin JSON: " + str(e))
    sys.exit(1)

tool_name = payload.get("tool_name") or "unknown"
tool_input = payload.get("tool_input") or {}
if not isinstance(tool_input, dict):
    tool_input = {}

ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
date = time.strftime("%Y-%m-%d", time.gmtime())

typ = "tool"
name = tool_name

if tool_name in ("Skill", "skill"):
    typ = "skill"
    name = tool_input.get("skill") or "unknown-skill"
elif tool_name in ("Agent", "agent"):
    typ = "agent"
    name = tool_input.get("subagent_type") or "general-purpose"
elif tool_name.startswith("mcp__plugin_"):
    typ = "mcp"
    # mcp__plugin_<pluginname>_<serverkey>__<tool> -> <pluginname>
    rest = tool_name[len("mcp__plugin_"):]
    name = re.sub(r"_[^_]*__.*$", "", rest)
elif tool_name.startswith("mcp__"):
    typ = "mcp"
    # mcp__<server>__<tool> -> <server>
    name = tool_name[len("mcp__"):].split("__", 1)[0]

def clean(s, n):
    return "".join(c for c in str(s) if c not in "\n\r\t\"\\")[:n]

entry = {
    "ts": ts,
    "date": date,
    "type": typ,
    "name": clean(name, 100),
    "tool": clean(tool_name, 200),
}

try:
    with open(usage_file, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
except Exception as e:
    log_error("Failed to write to " + usage_file + ": " + str(e))
    sys.exit(1)
PYEOF
)

python3 -c "$PYSCRIPT"

exit 0
