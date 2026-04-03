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

3. **Cross-reference with installed inventory**

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
   | 1 | autopilot | 47 | oh-my-claudecode |
   | 2 | ralph | 31 | oh-my-claudecode |
   | 3 | plan | 28 | superpowers |
   | ... | ... | ... | ... |

   ### Agents (X used / Y available)
   | Rank | Agent | Invocations |
   |------|-------|-------------|
   | 1 | code-reviewer | 62 |
   | 2 | Explore | 45 |
   | 3 | planner | 19 |
   | ... | ... | ... |

   ### MCP Tools (X servers used / Y configured)
   | Rank | Server | Invocations |
   |------|--------|-------------|
   | 1 | playwright | 34 |
   | 2 | figma-console | 22 |
   | ... | ... | ... |

   ## What You NEVER Use

   ### Installed but zero invocations in <N> days

   **Skills (X never used):**
   - kotlin-test, kotlin-review, kotlin-build (everything-claude-code)
   - perl-patterns, perl-testing (everything-claude-code)
   - cpp-build, cpp-review, cpp-test (everything-claude-code)
   - ...

   **Agents (X never used):**
   - chief-of-staff, database-reviewer, loop-operator
   - ...

   **MCP servers (X never called):**
   - memory, filesystem, sequential-thinking
   - ...

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

5. **Done**

   Read-only. The data keeps accumulating — run again later for updated insights.

</Steps>
