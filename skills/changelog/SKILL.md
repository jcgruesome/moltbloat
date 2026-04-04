---
name: changelog
description: Diff your ecosystem against a previous snapshot — see what changed, what was added, what was removed
level: 2
---

<Purpose>
Compare the current Claude Code ecosystem against a previous baseline snapshot (from `/moltbloat:snapshot`). Shows what plugins, MCPs, skills, agents, and rules were added, removed, upgraded, or downgraded since the last snapshot. Fully dynamic — no curated opinion lists.
</Purpose>

<Use_When>
- User says "changelog", "what changed", "diff", "what's new", "what's different"
- After a Claude Code version upgrade
- After installing or removing plugins
- To understand ecosystem drift over time
</Use_When>

<Do_Not_Use_When>
- User wants a full audit with health scoring — use `/moltbloat:audit`
- User wants to see what a specific plugin does — use `/moltbloat:why`
- No baseline exists yet — direct user to run `/moltbloat:snapshot` first
</Do_Not_Use_When>

<Steps>

1. **Load the baseline snapshot**

   ```bash
   cat ~/.moltbloat/baseline.json 2>/dev/null
   ```

   If no baseline exists, tell the user:
   > No baseline snapshot found. Run `/moltbloat:snapshot` to save the current state, then run `/moltbloat:changelog` after your next change to see a diff.

   Stop here if no baseline.

2. **Collect current state**

   Run these scans in parallel:

   **Plugins:**
   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   ```

   **Claude Code version:**
   ```bash
   claude --version 2>/dev/null || echo "unknown"
   ```

   **MCP servers:** Scan settings.json + plugin .mcp.json files.

   **Skills:** Count per plugin from cache directories.

   **Agents:** List from `~/.claude/agents/` and plugin cache.

   **Rules:** List from `~/.claude/rules/`.

3. **Diff current vs baseline**

   Compare each category:

   **Plugins:**
   - Added: in current but not in baseline
   - Removed: in baseline but not in current
   - Upgraded: same plugin, higher version
   - Downgraded: same plugin, lower version

   **MCP servers:**
   - Added/removed MCP server names

   **Skills:**
   - Net change in skill count per plugin
   - New skill names not in baseline
   - Removed skill names from baseline

   **Agents:**
   - Added/removed agent files

   **Rules:**
   - Added/removed rule files or directories

   **Claude Code version:**
   - Version change (upgrade/downgrade/same)

4. **Generate report**

   ```
   # Moltbloat Changelog

   **Baseline taken**: <timestamp from baseline.json>
   **Current scan**: <now>
   **Claude Code**: <old version> → <new version> (or "unchanged")

   ## Plugins

   | Change | Plugin | Details |
   |--------|--------|---------|
   | + Added | <name> | v<version>, installed <date> |
   | - Removed | <name> | was v<version> |
   | ↑ Upgraded | <name> | v<old> → v<new> |
   | ↓ Downgraded | <name> | v<old> → v<new> |

   (If no changes: "No plugin changes since baseline.")

   ## MCP Servers
   - Added: <list>
   - Removed: <list>
   (If no changes: "No MCP changes since baseline.")

   ## Skills
   - Total: <old count> → <new count> (<+/- delta>)
   - <list notable additions/removals if any>

   ## Agents
   - Added: <list>
   - Removed: <list>

   ## Rules
   - Added: <list>
   - Removed: <list>

   ## Summary
   - <N> total changes since baseline (<date>)
   - Run `/moltbloat:snapshot` to update the baseline to current state
   - Run `/moltbloat:audit` for a full health check
   ```

5. **Done**

   Read-only. Suggest `/moltbloat:snapshot` to update the baseline if the user is happy with the current state.

</Steps>
