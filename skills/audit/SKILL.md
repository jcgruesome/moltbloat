---
name: audit
description: Full ecosystem audit — scans plugins, MCPs, skills, agents, rules, and configs for bloat, redundancy, and staleness
level: 3
---

<Purpose>
Audit the entire Claude Code ecosystem (~/.claude/) and produce a severity-rated report of bloat, redundancy, stale configs, superseded plugins, and actionable cleanup recommendations.
</Purpose>

<Use_When>
- User wants to understand what's installed and whether it's all needed
- User says "audit", "bloat", "cleanup check", "what's installed", "ecosystem health"
- After installing new plugins or upgrading Claude Code
- Periodically (monthly) to catch drift
</Use_When>

<Do_Not_Use_When>
- User wants to actually remove things — use `/moltbloat:clean` instead
- User only wants token cost info — use `/moltbloat:token-budget` instead
</Do_Not_Use_When>

<Steps>

1. **Announce the audit**

   Tell the user:
   > Running full ecosystem audit on `~/.claude/`...

2. **Collect inventory**

   Run these scans in parallel using Bash/Read/Grep/Glob. Capture all results before analyzing.

   **2a. Plugins**
   ```bash
   cat ~/.claude/plugins/installed_plugins.json
   ```
   Parse the JSON. For each plugin, record: name, version, scope, enabled/disabled, lastUpdated.

   **2b. MCP Servers**
   Search for MCP configurations:
   ```bash
   cat ~/.claude/settings.json  # check mcpServers key
   cat ~/.claude/settings.local.json 2>/dev/null  # check mcpServers key
   ```
   Also check each installed plugin for `.mcp.json`:
   ```bash
   find ~/.claude/plugins/cache -name ".mcp.json" -type f 2>/dev/null
   ```
   Build a combined list of all MCP servers with their source (global config vs plugin).

   **2c. Skills**
   Count skills per plugin:
   ```bash
   for dir in ~/.claude/plugins/marketplaces/*/skills/*/; do echo "$dir"; done 2>/dev/null
   ```
   Also check for local skills:
   ```bash
   ls ~/.claude/commands/ 2>/dev/null
   ```

   **2d. Agents**
   ```bash
   ls ~/.claude/agents/*.md 2>/dev/null
   ```
   And plugin-provided agents:
   ```bash
   find ~/.claude/plugins/cache -path "*/agents/*.md" -type f 2>/dev/null
   ```

   **2e. Rules**
   ```bash
   find ~/.claude/rules -name "*.md" -type f 2>/dev/null
   ```

   **2f. Projects**
   ```bash
   du -sh ~/.claude/projects/*/ 2>/dev/null | sort -rh
   ```

   **2g. Stale data**
   ```bash
   du -sh ~/.claude/plugins/cache/*/*/*/ 2>/dev/null | sort -rh | head -20
   ```

3. **Run redundancy checks**

   Apply these deterministic rules against the collected inventory. Each check produces a finding or passes silently.

   ### Check 1: Superseded Plugins
   Flag if BOTH of these are installed:
   - `vercel` (old) AND `vercel-plugin` (new) → old is superseded
   - `ralph-loop` AND `oh-my-claudecode` (which has native ralph skill) → ralph-loop is superseded
   - `claude-hud` AND `oh-my-claudecode` (which has native HUD) → claude-hud may be superseded

   General rule: if a plugin has 0 skills AND another installed plugin provides equivalent functionality, flag it.

   ### Check 2: Zero-Skill Plugins
   For each enabled plugin, count its skills. Flag any enabled plugin with 0 skills that also has no MCP servers configured — it's doing nothing.

   ### Check 3: Disabled Plugins Still Installed
   List all disabled plugins. These consume disk space and clutter the registry. Flag as LOW severity — suggest uninstalling if unused for 30+ days (check lastUpdated).

   ### Check 4: MCP Redundancy with Native Features
   Flag these specific MCPs as redundant:
   - `filesystem` MCP → Claude Code has native Read/Write/Glob/Grep
   - `memory` MCP (generic @modelcontextprotocol/server-memory) when `claude-mem` plugin is also installed → claude-mem is a superset
   - Any MCP named `sequential-thinking` → Claude has native extended thinking

   ### Check 5: Duplicate MCP Servers
   Check if the same underlying MCP server is loaded from both global config AND a plugin. Common case: `playwright` in mcp-servers.json AND as a plugin.

   Compare MCP server names and npm package names across all sources. Flag duplicates.

   ### Check 6: Agent Overlap
   Compare agent filenames in `~/.claude/agents/` against agents provided by installed plugins. If the same agent name exists in both places, flag it — the user is maintaining two versions.

   Read the first 5 lines of each duplicate pair to check if they're identical or diverged.

   ### Check 7: Skill Name Collisions
   Build a map of skill names across all plugins. If two plugins provide a skill with the same name, flag it — the user may not know which one runs.

   ### Check 8: Rules Without Matching Languages
   For the current working directory (or the user's Projects directory), check which programming languages are actually present:
   ```bash
   find ~/Projects -maxdepth 3 -name "*.go" -o -name "*.rs" -o -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" -o -name "*.kt" -o -name "*.swift" -o -name "*.php" -o -name "*.pl" -o -name "*.cpp" -o -name "*.c" -o -name "*.java" 2>/dev/null | sed 's/.*\.//' | sort | uniq -c | sort -rn
   ```
   Compare against installed rule directories in `~/.claude/rules/`. Flag rule sets for languages with 0 files in any project as LOW severity.

   ### Check 9: Stale Project Configs
   Check `~/.claude/projects/` for directories that don't correspond to any existing project path:
   ```bash
   for dir in ~/.claude/projects/*/; do
     # Decode the directory name back to a path
     path=$(basename "$dir" | sed 's/-/\//g')
     # Check if original path exists
   done
   ```
   Flag orphaned project configs.

   ### Check 10: Large Caches
   Flag any single cache directory over 50MB. Flag total plugin cache over 500MB.

4. **Classify findings**

   Assign severity to each finding:

   | Severity | Criteria |
   |----------|----------|
   | **CRITICAL** | Active conflict — two things fighting for the same job, causing errors or unpredictable behavior |
   | **HIGH** | Clear redundancy — something is fully superseded and should be removed |
   | **MEDIUM** | Waste — consuming resources (disk, tokens, context) for no benefit |
   | **LOW** | Cleanup opportunity — not harmful but clutters the ecosystem |

5. **Generate report**

   Output the report in this exact format:

   ```
   # Moltbloat Ecosystem Audit

   **Scanned**: <timestamp>
   **Claude Code version**: <version from `claude --version` if available>
   **Total plugins**: X enabled, Y disabled
   **Total MCP servers**: Z
   **Total skills**: N across M plugins
   **Total agents**: A local + B plugin-provided
   **Ecosystem disk usage**: X MB

   ## Findings

   ### CRITICAL (X)
   <findings or "None">

   ### HIGH (X)
   | # | Finding | Source | Action |
   |---|---------|--------|--------|
   | 1 | `ralph-loop` plugin superseded by OMC native ralph | Plugins | Uninstall ralph-loop |
   | 2 | ... | ... | ... |

   ### MEDIUM (X)
   | # | Finding | Source | Action |
   |---|---------|--------|--------|
   | 1 | ... | ... | ... |

   ### LOW (X)
   | # | Finding | Source | Action |
   |---|---------|--------|--------|
   | 1 | ... | ... | ... |

   ## Health Score: XX/100

   <score breakdown>

   ## Summary
   - X findings total (C critical, H high, M medium, L low)
   - Estimated recoverable disk space: X MB
   - Run `/moltbloat:clean` to address findings interactively
   - Run `/moltbloat:token-budget` to see context window impact
   - Run `/moltbloat:snapshot` to save this state as a baseline
   ```

6. **Calculate health score**

   Start at 100 and deduct points based on findings:

   | Finding Severity | Points Deducted (each) |
   |-----------------|----------------------|
   | CRITICAL | -15 |
   | HIGH | -10 |
   | MEDIUM | -5 |
   | LOW | -2 |

   Additional deductions:
   - Token cost > 5% of context window: -5
   - Token cost > 10% of context window: -10
   - Disk usage > 1 GB: -3
   - More than 5 disabled plugins: -3
   - No baseline snapshot exists: -5

   Floor at 0. Display with a visual indicator:

   ```
   ## Health Score: 72/100

   ████████████████████░░░░░░░░░░ 72/100

   Breakdown:
     Base score:              100
     HIGH findings (×2):       -20
     MEDIUM findings (×3):     -15
     LOW findings (×4):         -8
     Token cost > 5%:           -5
     No baseline snapshot:      -5
     ─────────────────────────
     Final:                     47... wait, 72? Let me recalc
   ```

   Use the actual deductions. The bar is `Math.round(score / 100 * 30)` filled blocks out of 30.

   Score interpretation:
   - 90-100: Pristine — minimal bloat
   - 70-89: Healthy — some cleanup opportunities
   - 50-69: Bloated — significant redundancy
   - 0-49: Critical — major cleanup needed

7. **Done**

   Do NOT take any action. This skill is read-only. Direct the user to `/moltbloat:clean` if they want to act on findings.

</Steps>
