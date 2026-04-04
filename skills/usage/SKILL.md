---
name: usage
description: Analyze what you actually use — show which skills, agents, MCPs, and plugins are invoked vs just installed
level: 2
---

<Purpose>
Analyze usage data collected by the moltbloat tracking hook to show what's actually being used versus what's just sitting there consuming context. Turns "maybe I should clean up" into "here's exactly what you're wasting."
</Purpose>

<Use_When>
- User says "usage", "what do I use", "what's unused", "am I using", "waste"
- After running moltbloat for 1+ weeks to have meaningful data
- When deciding what to remove or which profile to create
</Use_When>

<Do_Not_Use_When>
- No usage data exists yet — tell user to wait a few days for data collection
- User wants a one-time audit — use `/moltbloat:audit`
</Do_Not_Use_When>

<Steps>

1. **Check for usage data**

   ```bash
   wc -l ~/.moltbloat/usage.jsonl 2>/dev/null
   ```

   If file doesn't exist or has < 10 entries:
   > Usage tracking is active but needs more data. Come back after a few sessions.
   > (X entries collected so far)

   Stop here if insufficient data.

2. **Parse usage data**

   Extract aggregated counts by type and name:

   ```bash
   # Total entries and date range
   head -1 ~/.moltbloat/usage.jsonl | grep -o '"date":"[^"]*"' | cut -d'"' -f4
   tail -1 ~/.moltbloat/usage.jsonl | grep -o '"date":"[^"]*"' | cut -d'"' -f4
   wc -l < ~/.moltbloat/usage.jsonl

   # Skill usage counts
   grep '"type":"skill"' ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn

   # Agent usage counts
   grep '"type":"agent"' ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn

   # MCP tool usage counts
   grep '"type":"mcp"' ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn

   # Core tool usage counts
   grep '"type":"tool"' ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn

   # Usage by day
   grep -o '"date":"[^"]*"' ~/.moltbloat/usage.jsonl | sort | uniq -c | sort -k2
   ```

3. **Estimate hook injection overhead**

   Count how many tool invocations were tracked (each one triggered the PostToolUse hook). Calculate the hook overhead:

   ```bash
   total_invocations=$(wc -l < ~/.moltbloat/usage.jsonl)
   unique_days=$(grep -o '"date":"[^"]*"' ~/.moltbloat/usage.jsonl | sort -u | wc -l)
   ```

   For each active plugin with hooks (from `installed_plugins.json`), read its `hooks/hooks.json` and count:
   - How many PreToolUse hooks fire per tool call
   - How many PostToolUse hooks fire per tool call
   - How many UserPromptSubmit hooks fire per message

   Estimate tokens per hook invocation based on hook type:
   - **PreToolUse/PostToolUse with output**: ~100-500 tokens per fire (system-reminder injection)
   - **PreToolUse/PostToolUse silent** (like moltbloat's tracker): ~0 tokens
   - **UserPromptSubmit**: ~200-2,000 tokens per fire (skill injection, best-practice suggestions)
   - **SessionStart**: one-time cost, ~500-5,000 tokens

   ```
   ## Hook Overhead

   | Plugin | Hook Type | Fires Per | Est. Tokens/Fire | Daily Total |
   |--------|-----------|-----------|-----------------|-------------|
   <one row per active hook, with estimated daily token cost based on actual invocation counts>

   **Estimated daily hook overhead**: ~<X> tokens
   **As % of total token budget**: <Y>%
   ```

   Note: These are estimates — actual hook output varies. Hooks that inject `<system-reminder>` tags are the costly ones.

4. **Cross-reference with installed inventory**

   Get the full list of installed skills, agents, and MCP servers:

   ```bash
   # All installed skills
   find ~/.claude/plugins/cache -path "*/skills/*/SKILL.md" -type f 2>/dev/null | sed 's|.*/skills/\([^/]*\)/.*|\1|' | sort -u

   # All installed agents
   ls ~/.claude/agents/*.md 2>/dev/null | xargs -I{} basename {} .md
   find ~/.claude/plugins/cache -path "*/agents/*.md" -type f 2>/dev/null | xargs -I{} basename {} .md | sort -u

   # All MCP servers
   find ~/.claude/plugins/cache -name ".mcp.json" -type f 2>/dev/null
   ```

   Compare: which installed items have ZERO usage entries?

4. **Generate the report**

   ```
   # Moltbloat Usage Report

   **Tracking period**: <first date> to <last date> (<N> days)
   **Total invocations**: <count>
   **Sessions tracked**: ~<unique dates>

   ## What You Actually Use

   ### Skills (X used / Y installed)
   | Rank | Skill | Invocations | Source Plugin |
   |------|-------|-------------|--------------|
   | 1 | <name> | <count> | <plugin> |
   | ... | ... | ... | ... |

   ### Agents (X used / Y available)
   | Rank | Agent | Invocations |
   |------|-------|-------------|
   | 1 | <name> | <count> |
   | ... | ... | ... |

   ### MCP Tools (X servers used / Y configured)
   | Rank | Server | Invocations |
   |------|--------|-------------|
   | 1 | <name> | <count> |
   | ... | ... | ... |

   ## What You NEVER Use

   ### Installed but zero invocations in <N> days

   **Skills (X never used):**
   <list skills with 0 invocations, grouped by source plugin>

   **Agents (X never used):**
   <list agents with 0 invocations>

   **MCP servers (X never called):**
   <list MCP servers with 0 invocations>

   ## The Bottom Line

   **You use X% of what's installed.**
   - X of Y skills (Z% idle)
   - X of Y agents (Z% idle)
   - X of Y MCP servers (Z% idle)

   **Estimated wasted tokens**: ~X tokens/session on unused components
   **Estimated wasted cost**: ~$X.XX per message on dead weight

   ## Recommendations
   - Consider creating a `/moltbloat:profile` based on your actual usage
   - These plugins could be disabled with no impact: <list>
   - Run `/moltbloat:clean` to remove confirmed dead weight
   ```

5. **Compact old usage data**

   Check if the usage file has grown large enough to benefit from compaction:
   ```bash
   wc -l < ~/.moltbloat/usage.jsonl 2>/dev/null
   ```

   If >5,000 lines, offer to compact:

   > Usage log has <N> entries. Compact old data to keep it fast?
   > This aggregates entries older than 30 days into daily summaries and
   > removes the raw lines. Recent data (last 30 days) stays untouched.

   If user confirms:

   **5a.** Read all entries, split into recent (last 30 days) and old.

   **5b.** Aggregate old entries into daily summaries:
   ```json
   {"date":"2026-03-01","type":"summary","skills":{"plan":12,"audit":3},"agents":{"code-reviewer":8},"mcps":{"playwright":5},"tools":{"Read":45,"Edit":22},"total":95}
   ```

   **5c.** Write compacted file:
   ```bash
   # Back up first
   cp ~/.moltbloat/usage.jsonl ~/.moltbloat/usage.jsonl.bak

   # Write: old summaries + recent raw entries
   cat <summaries> <recent_entries> > ~/.moltbloat/usage.jsonl.new
   mv ~/.moltbloat/usage.jsonl.new ~/.moltbloat/usage.jsonl
   ```

   **5d.** Report:
   ```
   Compacted: <old_count> raw entries → <summary_count> daily summaries
   Kept: <recent_count> recent entries (last 30 days)
   File size: <old_size> → <new_size>
   Backup: ~/.moltbloat/usage.jsonl.bak
   ```

   If user declines or <5,000 lines, skip silently.

6. **Done**

   The data keeps accumulating — run again later for updated insights.

</Steps>
