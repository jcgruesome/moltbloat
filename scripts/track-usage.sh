#!/bin/bash
# Lightweight usage tracker — logs tool/skill/agent invocations to ~/.moltbloat/usage.jsonl
# Called by PostToolUse hook. Receives tool name and target via env vars.
# Typically completes in under 50ms; hard timeout of 2 seconds set in hooks.json.

set -e

USAGE_DIR="$HOME/.moltbloat"
USAGE_FILE="$USAGE_DIR/usage.jsonl"
ERROR_LOG="$USAGE_DIR/errors.log"
LOCK_FILE="$USAGE_DIR/usage.lock"

# Ensure directory exists
mkdir -p "$USAGE_DIR" 2>/dev/null || {
    echo "[moltbloat] Error: Cannot create $USAGE_DIR" >&2
    exit 1
}

# Function to log errors
log_error() {
    local msg="[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $1"
    echo "$msg" >> "$ERROR_LOG" 2>/dev/null || true
}

# Function to acquire lock (with timeout)
acquire_lock() {
    local timeout=5
    local elapsed=0
    while [ -f "$LOCK_FILE" ] && [ $elapsed -lt $timeout ]; do
        sleep 0.1
        elapsed=$((elapsed + 1))
    done
    
    if [ -f "$LOCK_FILE" ]; then
        log_error "Lock timeout, stale lock file exists"
        rm -f "$LOCK_FILE" 2>/dev/null || true
    fi
    
    touch "$LOCK_FILE" 2>/dev/null || {
        log_error "Cannot create lock file"
        exit 1
    }
}

# Function to release lock
release_lock() {
    rm -f "$LOCK_FILE" 2>/dev/null || true
}

# Trap to ensure lock is always released
trap release_lock EXIT

# Acquire lock
acquire_lock

# Extract tool info from environment
TOOL_NAME="${CLAUDE_TOOL_NAME:-unknown}"
TOOL_INPUT="${CLAUDE_TOOL_INPUT:-}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "unknown")
DATE=$(date -u +"%Y-%m-%d" 2>/dev/null || echo "unknown")

# Sanitize inputs (remove newlines and control chars to prevent JSON corruption)
TOOL_NAME=$(echo "$TOOL_NAME" | tr -d '\n\r\t' | head -c 200)

# Classify the invocation
TYPE="tool"
NAME="$TOOL_NAME"

case "$TOOL_NAME" in
  Skill|skill)
    TYPE="skill"
    # Extract skill name from input (handle optional whitespace in JSON)
    NAME=$(echo "$TOOL_INPUT" | grep -oE '"skill"[[:space:]]*:[[:space:]]*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*:[[:space:]]*"\([^"]*\)".*/\1/')
    [ -z "$NAME" ] && NAME="unknown-skill"
    ;;
  Agent|agent)
    TYPE="agent"
    NAME=$(echo "$TOOL_INPUT" | grep -oE '"subagent_type"[[:space:]]*:[[:space:]]*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*:[[:space:]]*"\([^"]*\)".*/\1/')
    [ -z "$NAME" ] && NAME="general-purpose"
    ;;
  mcp__plugin_*)
    TYPE="mcp"
    # Plugin MCP: mcp__plugin_oh-my-claudecode_t__tool -> oh-my-claudecode
    NAME=$(echo "$TOOL_NAME" | sed 's/^mcp__plugin_//' | sed 's/_[^_]*__.*$//')
    ;;
  mcp__*)
    TYPE="mcp"
    # Direct MCP: mcp__figma-console__tool -> figma-console
    NAME=$(echo "$TOOL_NAME" | sed 's/^mcp__//' | sed 's/__.*//')
    ;;
esac

# Sanitize name
NAME=$(echo "$NAME" | tr -d '\n\r\t"\\' | head -c 100)

# Build JSON entry
JSON_ENTRY="{\"ts\":\"$TIMESTAMP\",\"date\":\"$DATE\",\"type\":\"$TYPE\",\"name\":\"$NAME\",\"tool\":\"$TOOL_NAME\"}"

# Validate JSON (basic check)
if ! echo "$JSON_ENTRY" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    log_error "Invalid JSON generated: $JSON_ENTRY"
    exit 1
fi

# Append to usage log (atomic write)
if ! echo "$JSON_ENTRY" >> "$USAGE_FILE" 2>/dev/null; then
    log_error "Failed to write to $USAGE_FILE"
    exit 1
fi

# Release lock (trap handles this, but be explicit)
release_lock

exit 0
