#!/bin/bash
# Lightweight usage tracker — logs tool/skill/agent invocations to ~/.moltbloat/usage.jsonl
# Called by PostToolUse hook. Receives tool name and target via env vars.
# Designed to be fast (<50ms) so it doesn't slow down the session.

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
    # Extract skill name from input
    NAME=$(echo "$TOOL_INPUT" | grep -o '"skill":"[^"]*"' | head -1 | cut -d'"' -f4)
    [ -z "$NAME" ] && NAME="unknown-skill"
    ;;
  Agent)
    TYPE="agent"
    NAME=$(echo "$TOOL_INPUT" | grep -o '"subagent_type":"[^"]*"' | head -1 | cut -d'"' -f4)
    [ -z "$NAME" ] && NAME="general-purpose"
    ;;
  mcp__*)
    TYPE="mcp"
    # Extract server name: mcp__servername__toolname -> servername
    NAME=$(echo "$TOOL_NAME" | cut -d'_' -f4)
    ;;
esac

# Append to usage log (one JSON line)
echo "{\"ts\":\"$TIMESTAMP\",\"date\":\"$DATE\",\"type\":\"$TYPE\",\"name\":\"$NAME\",\"tool\":\"$TOOL_NAME\"}" >> "$USAGE_FILE"
