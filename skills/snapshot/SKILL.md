---
name: snapshot
description: Save ecosystem baseline and detect drift — tracks what changed since last audit
level: 2
---

<Purpose>
Capture the current state of the Claude Code ecosystem as a JSON baseline. On subsequent runs, diff against the previous baseline to show what changed — new plugins, removed MCPs, token cost delta, resolved/new findings.
</Purpose>

<Use_When>
- User says "snapshot", "baseline", "save state", "what changed"
- After running `/moltbloat:clean` to record the new clean state
- Periodically to track ecosystem drift
</Use_When>

<Do_Not_Use_When>
- User wants a full audit — use `/moltbloat:audit`
- User wants to clean up — use `/moltbloat:clean`
</Do_Not_Use_When>

<Steps>

1. **Check for existing baseline**

   ```bash
   cat ~/.moltbloat/baseline.json 2>/dev/null
   ```

   If a baseline exists, load it for comparison. If not, this is the first snapshot.

2. **Collect current state**

   Build a JSON object with the current ecosystem state. Run these in parallel:

   **2a. Plugins**
   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   ```
   Extract: name, version, enabled/disabled for each plugin.

   **2b. MCP servers**
   Count MCP servers from settings and plugin configs:
   ```bash
   # From global settings
   cat ~/.claude/settings.json 2>/dev/null | grep -c '"mcpServers"' || echo 0
   # From plugin MCP configs
   find ~/.claude/plugins/cache -name ".mcp.json" -type f 2>/dev/null | wc -l
   ```

   **2c. Skills count**
   ```bash
   find ~/.claude/plugins/cache -path "*/skills/*/SKILL.md" -type f 2>/dev/null | wc -l
   ```

   **2d. Agents count**
   ```bash
   ls ~/.claude/agents/*.md 2>/dev/null | wc -l
   ```

   **2e. Rules**
   ```bash
   ls -d ~/.claude/rules/*/ 2>/dev/null | xargs -I{} basename {}
   ```

   **2f. Disk usage**
   ```bash
   du -sm ~/.claude/plugins/ 2>/dev/null | awk '{print $1}'
   du -sm ~/.claude/projects/ 2>/dev/null | awk '{print $1}'
   du -sm ~/.claude/ 2>/dev/null | awk '{print $1}'
   ```

   **2g. Token cost estimate**
   ```bash
   # Total bytes of context-loaded content
   total=0
   for f in ~/.claude/CLAUDE.md; do [ -f "$f" ] && total=$((total + $(wc -c < "$f"))); done
   find ~/.claude/rules -name "*.md" -type f -exec cat {} + 2>/dev/null | wc -c
   ```

3. **Build the snapshot JSON**

   Construct a JSON object (using a heredoc or jq if available) with this structure:

   ```json
   {
     "timestamp": "2026-04-03T15:30:00Z",
     "version": "0.2.0",
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

4. **If previous baseline exists, compute diff**

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
   - Plugin: vercel-plugin@0.24.0 (enabled)
   - Plugin: moltbloat@0.1.0 (enabled)

   ## Removed Since Last Snapshot
   - (none)

   ## Recommendations
   - Token cost increased 10% — run `/moltbloat:token-budget` for details
   - 1 new disabled plugin — consider uninstalling if unused
   ```

5. **Save the new baseline**

   ```bash
   mkdir -p ~/.moltbloat
   ```

   Write the JSON snapshot to `~/.moltbloat/baseline.json`.

   Also append a one-line summary to `~/.moltbloat/history.log`:
   ```
   2026-04-03T15:30:00Z | plugins=20 skills=71 mcps=27 tokens=~37325 disk=967MB
   ```

6. **Output confirmation**

   ```
   Snapshot saved to ~/.moltbloat/baseline.json
   History appended to ~/.moltbloat/history.log (X entries total)
   ```

   If this was the first snapshot:
   ```
   First baseline recorded. Run `/moltbloat:snapshot` again later to see drift.
   ```

</Steps>
