---
name: usage
description: Analyze what you actually use — mine Claude Code's native session history to show which tools, skills, agents, MCPs, and plugins are invoked vs just installed, with recency tiers and disable suggestions
level: 2
---

<Purpose>
Show what's actually being used versus what's just sitting there consuming context, and find bloat to disable. The **primary** data source is Claude Code's own session transcripts (`~/.claude/projects/**/*.jsonl`), mined retroactively by `scripts/parse-history.py` — so this works immediately, with no waiting for data to accumulate. moltbloat's own hook log (`~/.moltbloat/usage.jsonl`) is used as supplemental corroboration when present. Turns "maybe I should clean up" into "here's exactly what you're wasting, and here's the command to disable it."
</Purpose>

<Use_When>
- User says "usage", "what do I use", "what's unused", "am I using", "waste", "find bloat", "unused tools/mcps/plugins"
- When deciding what to remove or which profile to create
- Works from the first run — native history is mined retroactively
</Use_When>

<Do_Not_Use_When>
- `~/.claude/projects` is missing AND no hook data exists — there is nothing to analyze yet
- User wants a one-time structural audit — use `/moltbloat:audit`
</Do_Not_Use_When>

<Steps>

1. **Mine native Claude Code history (primary source)**

   Run the transcript miner. This walks `~/.claude/projects/**/*.jsonl` and returns a
   JSON aggregate of every tool, MCP server, skill, and subagent actually invoked, with
   `count`, `first_used`, `last_used`, and `sessions` per item:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parse-history.py" > /tmp/moltbloat-history.json
   # Optional: bound the scan to recent activity with --since <days>
   # python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parse-history.py" --since 90 > /tmp/moltbloat-history.json
   ```

   The output shape:
   ```json
   {
     "scanned": {"files": N, "lines": N, "tool_uses": N},
     "generated_at": "<UTC ISO>",
     "items": {
       "tool":  {"Bash": {"count": 8384, "first_used": "...", "last_used": "...", "sessions": 312}},
       "mcp":   {"plugin_figma_figma": {"count": 172, "plugin": "figma", "last_used": "...", ...}},
       "skill": {"moltbloat:audit": {...}},
       "agent": {"general-purpose": {...}}
     }
   }
   ```

   If the script exits non-zero because `~/.claude/projects` is missing, fall back to the
   hook-data-only flow (step 2) and note that native history was unavailable. If both are
   missing, tell the user there is nothing to analyze yet and stop.

   Read `first_used`/`last_used` across all items to establish the **tracking period**.

2. **Load supplemental hook data (optional corroboration)**

   If moltbloat's own hook log exists, fold its counts in. It never overrides transcript
   truth — it only corroborates and fills any gaps (e.g. very recent sessions):

   ```bash
   if [ -f ~/.moltbloat/usage.jsonl ] && [ "$(wc -l < ~/.moltbloat/usage.jsonl)" -gt 0 ]; then
     # Skill / agent / mcp / tool counts from the hook log
     grep '"type":"skill"' ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn
     grep '"type":"agent"' ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn
     grep '"type":"mcp"'   ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn
     grep '"type":"tool"'  ~/.moltbloat/usage.jsonl | grep -o '"name":"[^"]*"' | sort | uniq -c | sort -rn
   fi
   ```

   Merge rule: an item used in *either* source counts as used; `last_used` is the latest
   timestamp seen across both. Skip this step silently if no hook data exists.

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

   Cross-reference the **installed** inventory against the mined `items`. This is also
   what filters out parser noise: any historical name (e.g. legacy casing, `?`) that is
   not a currently-installed component is ignored — only installed items are classified.

   MCP server keys from the miner are normalized (`plugin_<plugin>_<server>`,
   `claude_ai_<server>`, or bare `<server>`); match them to installed servers by server
   name, and use the `plugin` field to attribute plugin-owned servers.

5. **Classify each installed item by recency tier**

   Read the staleness window from config (default 30 days):

   ```bash
   stale_days=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.stale_days 2>/dev/null || echo 30)
   ```

   For every installed skill, agent, and MCP server (and each plugin overall), assign:

   - **NEVER** — absent from the mined `items` entirely → strong remove candidate.
   - **STALE** — present, but `last_used` is older than `stale_days` → review candidate.
   - **ACTIVE** — `last_used` is within `stale_days` → keep.

   A **plugin** is NEVER-used only if *none* of its skills, agents, or MCP servers appear
   in history; STALE if its most recent contribution is older than `stale_days`.

6. **Generate the report**

   ```
   # Moltbloat Usage Report

   **Tracking period**: <first_used> to <last_used> (<N> days, from native history)
   **Sessions analyzed**: <scanned.files>   **Tool invocations**: <scanned.tool_uses>
   **Staleness window**: <stale_days> days
   <if hook data merged: **Supplemented by**: ~/.moltbloat/usage.jsonl (<N> entries)>

   ## What You Actively Use (used within <stale_days> days)

   ### Skills (X active / Y installed)
   | Rank | Skill | Invocations | Last used | Source Plugin |
   |------|-------|-------------|-----------|--------------|
   | 1 | <name> | <count> | <last_used date> | <plugin> |

   ### Agents (X active / Y available)
   | Rank | Agent | Invocations | Last used |
   |------|-------|-------------|-----------|
   | 1 | <name> | <count> | <last_used date> |

   ### MCP Servers (X active / Y configured)
   | Rank | Server | Invocations | Last used | Plugin |
   |------|--------|-------------|-----------|--------|
   | 1 | <name> | <count> | <last_used date> | <plugin> |

   ## Stale — used before, but not in <stale_days> days (review)

   | Item | Type | Last used | Days idle |
   |------|------|-----------|-----------|
   | <name> | skill/agent/mcp/plugin | <date> | <N> |

   ## Never Used — installed but zero invocations in all history (remove candidates)

   **Skills (X never used):** <list, grouped by source plugin>
   **Agents (X never used):** <list>
   **MCP servers (X never called):** <list>
   **Plugins fully idle (no skill/agent/mcp ever used):** <list>

   ## The Bottom Line

   **You actively use X% of what's installed.**
   - Skills: A active / B stale / C never  (of Y installed)
   - Agents: A active / B stale / C never  (of Y available)
   - MCP servers: A active / B stale / C never  (of Y configured)

   **Estimated wasted tokens**: ~X tokens/session on never-used components
   **Estimated wasted cost**: ~$<calculated> per message on dead weight

   ## Suggested Disable Commands (review before running — moltbloat never runs these)

   <For each NEVER/STALE item, print the exact action from the mapping below.>

   # Fully-idle plugins (no component ever used):
   claude plugin disable <plugin>        # frees its skills, agents, and MCP servers

   # Idle MCP servers owned by an otherwise-active plugin:
   #   disabling the plugin would remove still-used components — instead disconnect
   #   the server via /mcp, or remove it from the plugin's .mcp.json.

   # claude.ai connector MCPs (no owning plugin):
   #   disconnect via /mcp or your connector settings.

   # Never-used agents:
   #   ~/.claude/agents/<name>.md   (delete the file, or move it out of the agents dir)

   # Never-used skills:
   #   skills are not individually disablable — disable the owning plugin if ALL of its
   #   components are idle (see above), otherwise leave in place.

   ## Next Steps
   - Run `/moltbloat:clean` to interactively remove confirmed dead weight (confirms each action).
   - Consider `/moltbloat:profile suggest` to build a lean profile from this usage.
   ```

   **Granularity honesty:** never present a disable command that would remove a still-used
   component. Only suggest `claude plugin disable <plugin>` when *every* skill, agent, and
   MCP server from that plugin is NEVER or STALE. For an idle server inside an active
   plugin, recommend disconnecting the server, not disabling the plugin.

7. **Compact old usage data (auto or manual)**

   Check if the usage file has grown large enough to benefit from compaction:
   ```bash
   wc -l < ~/.moltbloat/usage.jsonl 2>/dev/null
   ```

   Get thresholds from config:
   ```bash
   compact_threshold=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.usage_compact_lines 2>/dev/null || echo 5000)
   auto_compact=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get defaults.auto_compact 2>/dev/null || echo true)
   ```

   **If auto_compact is enabled and threshold exceeded:**
   Automatically compact without prompting:
   > Usage log has <N> entries. Auto-compacting (config: defaults.auto_compact=true)...

   **If auto_compact is disabled and threshold exceeded:**
   Offer to compact:
   > Usage log has <N> entries. Compact old data to keep it fast?
   > Enable auto-compact in config to do this automatically.

   **Compaction process:**

   **7a.** Read all entries, split into recent (last 30 days) and old.

   **7b.** Aggregate old entries into daily summaries:
   ```json
   {"date":"<date>","type":"summary","skills":{"<name>":<count>},"agents":{"<name>":<count>},"mcps":{"<name>":<count>},"tools":{"<name>":<count>},"total":<count>}
   ```

   **7c.** Write compacted file:
   ```bash
   # Back up first
   cp ~/.moltbloat/usage.jsonl ~/.moltbloat/usage.jsonl.bak

   # Write: old summaries + recent raw entries
   cat <summaries> <recent_entries> > ~/.moltbloat/usage.jsonl.new
   mv ~/.moltbloat/usage.jsonl.new ~/.moltbloat/usage.jsonl
   ```

   **7d.** Report:
   ```
   Compacted: <old_count> raw entries → <summary_count> daily summaries
   Kept: <recent_count> recent entries (last 30 days)
   File size: <old_size> → <new_size>
   Backup: ~/.moltbloat/usage.jsonl.bak
   ```

   If auto_compact is disabled and user declines, skip silently.

8. **Done**

   Native history keeps growing as you work — run again later for updated insights.

</Steps>
