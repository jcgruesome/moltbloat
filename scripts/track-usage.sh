#!/bin/bash
# Lightweight usage tracker — logs tool/skill/agent invocations to ~/.moltbloat/usage.jsonl
# Called by PostToolUse hook. Receives tool name and target via env vars.
# Typically completes in under 50ms; hard timeout of 2 seconds set in hooks.json.

USAGE_DIR="$HOME/.moltbloat"
USAGE_FILE="$USAGE_DIR/usage.jsonl"

mkdir -p "$USAGE_DIR"

# Extract tool info from environment
TOOL_NAME="${CLAUDE_TOOL_NAME:-unknown}"
TOOL_INPUT="${CLAUDE_TOOL_INPUT:-}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATE=$(date -u +"%Y-%m-%d")

# Classify the invocation
TYPE="tool"
NAME="$TOOL_NAME"

case "$TOOL_NAME" in
  Skill)
    TYPE="skill"
    # Extract skill name from input (handle optional whitespace in JSON)
    NAME=$(echo "$TOOL_INPUT" | grep -oE '"skill"\s*:\s*"[^"]*"' | head -1 | sed 's/.*:.*"\([^"]*\)"/\1/')
    [ -z "$NAME" ] && NAME="unknown-skill"
    ;;
  Agent)
    TYPE="agent"
    NAME=$(echo "$TOOL_INPUT" | grep -oE '"subagent_type"\s*:\s*"[^"]*"' | head -1 | sed 's/.*:.*"\([^"]*\)"/\1/')
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

# Append to usage log (one JSON line)
echo "{\"ts\":\"$TIMESTAMP\",\"date\":\"$DATE\",\"type\":\"$TYPE\",\"name\":\"$NAME\",\"tool\":\"$TOOL_NAME\"}" >> "$USAGE_FILE"
