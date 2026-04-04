---
name: token-budget
description: Analyze context window cost of installed plugins, rules, CLAUDE.md, hooks, and MCP tool definitions
level: 2
---

<Purpose>
Measure how much of your context window is consumed by the Claude Code ecosystem — plugins, rules, CLAUDE.md files, hook outputs, and MCP tool definitions. Identifies the biggest token consumers so you can make informed decisions about what to keep.
</Purpose>

<Use_When>
- User wants to know what's eating their context window
- User says "token budget", "context cost", "token waste", "context window"
- After installing new plugins and wanting to see the impact
- When hitting context limits during long sessions
</Use_When>

<Do_Not_Use_When>
- User wants a full ecosystem audit — use `/moltbloat:audit`
- User wants to remove things — use `/moltbloat:clean`
</Do_Not_Use_When>

<Steps>

1. **Announce**

   Tell the user:
   > Analyzing context window cost of your Claude Code ecosystem...

2. **Measure each context source**

   For each category below, measure the byte size of all files that get injected into context. Use `wc -c` for accuracy. Estimate tokens as `bytes / 4` (conservative approximation for English/code mixed content).

   Run all measurements in parallel.

   **2a. CLAUDE.md files**
   These are always loaded into context:
   ```bash
   # Global
   wc -c ~/.claude/CLAUDE.md 2>/dev/null
   # Project-level (for current project)
   wc -c ./CLAUDE.md 2>/dev/null
   wc -c ./.claude/CLAUDE.md 2>/dev/null
   ```

   **2b. Rules**
   All `.md` files in `~/.claude/rules/` are loaded:
   ```bash
   find ~/.claude/rules -name "*.md" -type f -exec cat {} + 2>/dev/null | wc -c
   ```
   Also measure per-directory to show breakdown:
   ```bash
   for dir in ~/.claude/rules/*/; do
     name=$(basename "$dir")
     size=$(find "$dir" -name "*.md" -type f -exec cat {} + 2>/dev/null | wc -c)
     echo "$name: $size bytes"
   done
   ```

   **2c. Plugin CLAUDE.md and instructions**
   Each enabled plugin can inject instructions:
   ```bash
   for plugin_dir in ~/.claude/plugins/cache/*/*/; do
     name=$(basename "$plugin_dir")
     size=0
     # Check CLAUDE.md
     if [ -f "$plugin_dir/CLAUDE.md" ]; then
       s=$(wc -c < "$plugin_dir/CLAUDE.md")
       size=$((size + s))
     fi
     # Check AGENTS.md
     if [ -f "$plugin_dir/AGENTS.md" ]; then
       s=$(wc -c < "$plugin_dir/AGENTS.md")
       size=$((size + s))
     fi
     echo "$name: $size bytes"
   done
   ```

   **2d. MCP tool definitions**
   Each MCP server registers tools that consume context. Count the number of MCP tools visible in the current session by checking deferred tools:
   ```bash
   # Count MCP tool entries from plugin configs
   for mcp_file in $(find ~/.claude/plugins/cache -name ".mcp.json" -type f 2>/dev/null); do
     plugin=$(echo "$mcp_file" | sed 's|.*/cache/[^/]*/\([^/]*\)/.*|\1|')
     echo "$plugin: $mcp_file"
   done
   ```
   Note: Each MCP tool definition is approximately 200-500 tokens for the name + description + parameter schema. Multiply tool count by 350 (midpoint estimate).

   **2e. Skill metadata**
   Skills are listed in system reminders. Each skill listing is roughly one line (~100 chars = ~25 tokens):
   ```bash
   # Count total skills across all plugins
   total=0
   for plugin_dir in ~/.claude/plugins/cache/*/*/skills/*/; do
     total=$((total + 1))
   done 2>/dev/null
   echo "Total skills: $total"
   ```
   Estimate: `skill_count * 25` tokens for the skill listing in system reminders.

   **2f. Hook injection**
   Hooks inject `<system-reminder>` content. Measure hook definitions:
   ```bash
   find ~/.claude -name "hooks.json" -type f 2>/dev/null -exec wc -c {} +
   ```
   Note: Hook *output* varies per invocation and can't be pre-measured. Flag hooks that run on every tool call as potentially expensive.

   **2g. Agent definitions**
   Local agents are registered and their descriptions consume context:
   ```bash
   for f in ~/.claude/agents/*.md; do
     name=$(basename "$f" .md)
     size=$(wc -c < "$f")
     echo "$name: $size bytes"
   done 2>/dev/null
   ```

3. **Build the budget table**

   Calculate totals and percentages. Use 1,000,000 tokens as the context window size (1M for opus).

   Output in this format:

   ```
   # Moltbloat Token Budget

   **Context window**: 1,000,000 tokens
   **Total ecosystem cost**: ~X tokens (Y% of window)

   ## Breakdown by Source

   | Source | Bytes | ~Tokens | % of Window | Notes |
   |--------|-------|---------|-------------|-------|
   | CLAUDE.md (global) | X | X | X% | Always loaded |
   | CLAUDE.md (project) | X | X | X% | Per-project |
   | Rules (common) | X | X | X% | Always loaded |
   | Rules (typescript) | X | X | X% | Language-specific |
   | Rules (python) | X | X | X% | Language-specific |
   | ... | ... | ... | ... | ... |
   | Plugin: oh-my-claudecode | X | X | X% | Instructions + AGENTS.md |
   | Plugin: everything-claude-code | X | X | X% | Instructions |
   | Plugin: superpowers | X | X | X% | Instructions |
   | ... | ... | ... | ... | ... |
   | MCP tools (~N tools) | - | X | X% | Tool schemas in context |
   | Skill listings (~N skills) | - | X | X% | Skill menu |
   | Agent definitions (N agents) | X | X | X% | Agent descriptions |
   | Hook definitions | X | X | X% | Static cost only |
   | **TOTAL** | **X** | **X** | **X%** | |

   ## Top 5 Token Consumers
   1. <source> — X tokens (Y%)
   2. <source> — X tokens (Y%)
   3. ...

   ## Cost in Dollars

   Estimate real dollar cost of ecosystem overhead per message and per day.

   Use these rates (input tokens — ecosystem content is always input):
   - **Opus 4.6**: $15.00 / 1M input tokens
   - **Sonnet 4.6**: $3.00 / 1M input tokens
   - **Haiku 4.5**: $0.80 / 1M input tokens

   Calculate: `(total_tokens / 1,000,000) * rate`

   Assume 200 messages/day for daily cost.

   | Model | Per Message | Per Day (200 msgs) | Per Month |
   |-------|------------|-------------------|-----------|
   | Opus 4.6 | $X.XXXX | $X.XX | $X.XX |
   | Sonnet 4.6 | $X.XXXX | $X.XX | $X.XX |
   | Haiku 4.5 | $X.XXXX | $X.XX | $X.XX |

   **Note**: This is the FIXED overhead cost — the ecosystem tax you pay on every message regardless of what you're doing. Your actual message content and tool results are on top of this.

   ## Context Pressure

   Calculate what percentage of the context window is consumed by ecosystem overhead alone (before any user messages, tool results, or conversation history):

   ```
   Ecosystem overhead: ~<X> tokens (<Y>% of 1M context window)
   Remaining for work: ~<Z> tokens
   ```

   If overhead exceeds 3% (~30K tokens):
   > **Context pressure: ELEVATED** — Your ecosystem consumes <Y>% of the context
   > window before you start working. For long sessions, you'll need to `/compact`
   > sooner. Consider `/moltbloat:profile lean` for extended work sessions.

   If overhead exceeds 5% (~50K tokens):
   > **Context pressure: HIGH** — At <Y>% ecosystem overhead, you're losing
   > significant working context. This means more frequent `/compact` cycles and
   > degraded performance in the last 20% of your context window. Strongly
   > recommend reviewing the top consumers above.

   ## Effort Setting Impact

   Show how `/effort` interacts with ecosystem overhead:

   ```
   Your ecosystem costs ~<X> tokens/message regardless of effort level.

   | Effort | Typical response | Ecosystem as % of message |
   |--------|-----------------|--------------------------|
   | low    | ~2K tokens      | <X / (X+2000) * 100>%   |
   | medium | ~8K tokens      | <X / (X+8000) * 100>%   |
   | high   | ~20K tokens     | <X / (X+20000) * 100>%  |
   ```

   If ecosystem overhead is >30K tokens:
   > **Tip**: With <X> tokens of ecosystem overhead, `/effort low` still costs
   > ~<X+2000> tokens per message — the ecosystem is the dominant cost, not
   > your response. Use `/moltbloat:profile lean` to make `/effort low` truly lean.

   ## Recommendations
   - Items consuming >5% of context with low/no usage should be reviewed
   - Consider disabling language rules you don't actively use
   - MCP tools are the hidden cost — each registered tool consumes ~350 tokens
   - Use `/moltbloat:profile lean` to cut costs for simple tasks
   - For long sessions, `/compact` at ~60% context to maintain quality
   - Run `/moltbloat:usage` to see which costly components you actually use
   - Run `/moltbloat:audit` for full redundancy analysis
   ```

4. **Done**

   This skill is read-only. No modifications are made.

</Steps>
