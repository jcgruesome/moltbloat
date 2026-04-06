---
name: snapshot
description: Save ecosystem baseline, detect drift, and analyze trends — tracks what changed and visualizes growth over time
level: 2
---

<Purpose>
Capture the current state of the Claude Code ecosystem as a JSON baseline. On subsequent runs, diff against the previous baseline to show what changed. Also provides trend analysis over time when history exists.
</Purpose>

<Use_When>
- User says "snapshot", "baseline", "save state", "what changed"
- User says "trends", "history", "over time"
- After running `/moltbloat:clean` to record the new clean state
- Periodically to track ecosystem drift
</Use_When>

<Do_Not_Use_When>
- User wants a full audit — use `/moltbloat:audit`
- User wants to clean up — use `/moltbloat:clean`
</Do_Not_Use_When>

<Steps>

1. **Parse subcommand and flags**

   Check if user specified:
   - `/moltbloat:snapshot` — save baseline (default)
   - `/moltbloat:snapshot trends` — show trend analysis
   - `/moltbloat:snapshot --export <path>` — export snapshot to file
   - `/moltbloat:snapshot --json` — output snapshot JSON to stdout

2. **For "trends" — analyze history**

   Skip to step 8 if running in trends mode.

3. **Check for existing baseline (snapshot mode)**

   ```bash
   cat ~/.moltbloat/baseline.json 2>/dev/null
   ```

   If a baseline exists, load it for comparison. If not, this is the first snapshot.

4. **Collect current state**

   Build a JSON object with the current ecosystem state. Run these in parallel:

   **4a. Plugins**
   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   ```
   Extract: name, version, enabled/disabled for each plugin.

   **4b. MCP servers**
   Count MCP servers from settings and plugin configs:
   ```bash
   # From global settings
   cat ~/.claude/settings.json 2>/dev/null | grep -c '"mcpServers"' || echo 0
   # From plugin MCP configs
   find ~/.claude/plugins/cache -name ".mcp.json" -type f 2>/dev/null | wc -l
   ```

   **4c. Skills count**
   ```bash
   find ~/.claude/plugins/cache -path "*/skills/*/SKILL.md" -type f 2>/dev/null | wc -l
   ```

   **4d. Agents count**
   ```bash
   ls ~/.claude/agents/*.md 2>/dev/null | wc -l
   ```

   **4e. Rules**
   ```bash
   ls -d ~/.claude/rules/*/ 2>/dev/null | xargs -I{} basename {}
   ```

   **4f. Disk usage**
   ```bash
   du -sm ~/.claude/plugins/ 2>/dev/null | awk '{print $1}'
   du -sm ~/.claude/projects/ 2>/dev/null | awk '{print $1}'
   du -sm ~/.claude/ 2>/dev/null | awk '{print $1}'
   ```

   **4g. Token cost estimate**
   ```bash
   # Total bytes of context-loaded content
   total=0
   for f in ~/.claude/CLAUDE.md; do [ -f "$f" ] && total=$((total + $(wc -c < "$f"))); done
   find ~/.claude/rules -name "*.md" -type f -exec cat {} + 2>/dev/null | wc -c
   ```

5. **Build the snapshot JSON**

   Construct a JSON object (using a heredoc or jq if available) with this structure:

   ```json
   {
     "timestamp": "2026-04-03T15:30:00Z",
     "version": "<moltbloat version>",
     "plugins": {
       "total": 20,
       "enabled": 15,
       "disabled": 5,
       "list": ["plugin-a@1.0", "plugin-b@2.0"]
     },
     "mcpServers": {
       "total": 27,
       "sources": {"global": 5, "plugins": 22}
     },
     "skills": {"total": 71},
     "agents": {"local": 25, "pluginProvided": 19},
     "rules": {"directories": ["common", "typescript", "python"]},
     "disk": {
       "plugins_mb": 746,
       "projects_mb": 193,
       "total_mb": 967
     },
     "tokenEstimate": {
       "claudeMd": 1800,
       "rules": 5200,
       "pluginInstructions": 12000,
       "mcpTools": 9450,
       "skillListings": 1775,
       "agents": 7100,
       "total": 37325
     }
   }
   ```

6. **If previous baseline exists, compute diff**

   Compare each field and report changes:

   ```
   # Moltbloat Drift Report

   **Previous snapshot**: <previous timestamp>
   **Current snapshot**: <now>
   **Time since last snapshot**: X days

   ## Changes Detected

   | Category | Before | Now | Delta |
   |----------|--------|-----|-------|
   | Plugins (enabled) | 14 | 15 | +1 |
   | Plugins (disabled) | 4 | 5 | +1 |
   | MCP servers | 25 | 27 | +2 |
   | Skills | 68 | 71 | +3 |
   | Disk (total MB) | 920 | 967 | +47 |
   | Token cost (est.) | 34,000 | 37,325 | +3,325 |

   ## New Since Last Snapshot
   <list plugins in current but not in baseline>

   ## Removed Since Last Snapshot
   - (none)

   ## Recommendations
   - Token cost increased 10% — run `/moltbloat:token-budget` for details
   - 1 new disabled plugin — consider uninstalling if unused
   ```

7. **Save the new baseline and handle exports**

   ```bash
   mkdir -p ~/.moltbloat
   ```

   If `--export <path>` was specified:
   - Write JSON snapshot to the specified path
   - Do NOT update baseline.json (this is an export, not a new baseline)
   - Report: `Snapshot exported to <path>`
   - Stop here

   If `--json` was specified:
   - Output the JSON snapshot to stdout
   - Do NOT save to baseline.json
   - Stop here

   Otherwise (standard snapshot mode):
   - Write JSON snapshot to `~/.moltbloat/baseline.json`
   - Append one-line summary to `~/.moltbloat/history.log`:
     ```
     2026-04-03T15:30:00Z | plugins=20 skills=71 mcps=27 tokens=~37325 disk=967MB
     ```

   Output confirmation:
   ```
   Snapshot saved to ~/.moltbloat/baseline.json
   History appended to ~/.moltbloat/history.log (X entries total)
   ```

   If this was the first snapshot:
   ```
   First baseline recorded. Run `/moltbloat:snapshot trends` later to see trends.
   ```

   Stop here for snapshot mode.

8. **Trends mode — analyze history**

   ```bash
   wc -l ~/.moltbloat/history.log 2>/dev/null
   cat ~/.moltbloat/history.log 2>/dev/null
   ```

   If file doesn't exist or has < 2 entries:
   > Not enough historical data yet. Run `/moltbloat:snapshot` periodically (weekly or monthly) to build a trend history.

   Stop here if insufficient data.

9. **Parse history and calculate trends**

   Each line has the format:
   ```
   2026-04-03T15:30:00Z | plugins=20 skills=71 mcps=27 tokens=~37325 disk=967MB
   ```

   Extract metrics for trend analysis:
   - Plugin count over time
   - Token cost progression
   - Disk usage growth

   Calculate:
   - Total change (absolute and percentage)
   - Rate of change per month
   - Period of fastest growth

10. **Generate trend report**

    ```
    # Moltbloat Trends Report

    **Analysis period**: <first date> to <last date>
    **Snapshots available**: <count>

    ## Summary

    | Metric | Start | Current | Change | Rate/Month |
    |--------|-------|---------|--------|------------|
    | Plugins | X | Y | +/-Z | +/-N |
    | Token Cost | X | Y | +/-Z | +/-N |
    | Disk Usage | X MB | Y MB | +/-Z MB | +/-N MB |

    ## Token Cost Trend

    <ASCII sparkline showing progression>
    Example:
    ```
    40K ┤        ╭────╮
    35K ┤   ╭────╯    ╰────╮
    30K ┤───╯                ╰─── Current
        └────────────────────────
          Jan  Feb  Mar  Apr
    ```

    **Analysis**:
    - Token cost <increased/decreased> by X% since <first date>
    - Fastest growth: <date range> (+X tokens)
    - <if decreasing> Cleanup efforts are working — token cost down!
    - <if increasing> Growing at ~X tokens/month — consider `/moltbloat:profile lean`

    ## Recommendations

    Based on trend analysis:
    - <if growing> Your ecosystem is growing. Consider setting up profiles.
    - <if stable> Good stability — well managed.
    - <if shrinking> Excellent — you're keeping bloat down.
    - "At current rate, you'll reach 50K tokens by <projected date>"

    Run `/moltbloat:snapshot` regularly to maintain trend visibility.
    ```

11. **Done**

</Steps>
