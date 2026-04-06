---
name: audit
description: Full ecosystem audit with compatibility checking — scans plugins, MCPs, skills, agents, rules, and configs for bloat, redundancy, staleness, and conflicts
level: 3
---

<Purpose>
Audit the entire Claude Code ecosystem (~/.claude/) and produce a severity-rated report of bloat, redundancy, stale configs, conflicts, and actionable cleanup recommendations. Includes detailed compatibility checking for hook conflicts, skill shadowing, and MCP collisions. All checks are dynamic — no hardcoded plugin names or curated opinion lists.
</Purpose>

<Use_When>
- User wants to understand what's installed and whether it's all needed
- User says "audit", "bloat", "cleanup check", "what's installed", "ecosystem health", "conflicts", "compatibility"
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

2. **Load configuration**

   Load thresholds and scoring weights from config:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.token_warning
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.token_critical
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get health_score
   ```

3. **Collect inventory**

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
   for dir in ~/.claude/plugins/cache/*/*/skills/*/; do echo "$dir"; done 2>/dev/null
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

   ### Check 1: Skill Name Collisions (Detailed)
   Build a map of skill names to their source plugin using active install paths from `installed_plugins.json`:
   ```bash
   for plugin_dir in <active install paths>; do
     plugin=$(basename "$(dirname "$plugin_dir")")
     find "$plugin_dir/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | while read skill_dir; do
       skill=$(basename "$skill_dir")
       echo "$skill|$plugin"
     done
   done 2>/dev/null | sort
   ```

   Find duplicates: `cut -d'|' -f1 | sort | uniq -d`

   For each collision, include in findings:
   ```
   | Skill Name | Plugin A | Plugin B | Risk |
   ```

   **Impact**: When invoking `/<skill>`, ambiguous which version runs (last loaded wins).
   **Fix**: Disable one plugin or use fully-qualified names: `/plugin-a:skill` vs `/plugin-b:skill`

   Severity:
   - CRITICAL if 5+ collisions between same two plugins (wholesale duplicate)
   - HIGH if individual collisions between different plugins

   ### Check 2: Duplicate MCP Servers
   Check if the same underlying MCP server is loaded from both global config AND a plugin, or from multiple plugins.

   Compare MCP server names and npm package names across all sources. Flag duplicates.
   - CRITICAL if same MCP is loaded from 2+ sources (causes tool name conflicts)

   ### Check 3: Agent Name Collisions (Detailed)
   Compare agents across sources:
   ```bash
   # Local agents
   ls ~/.claude/agents/*.md 2>/dev/null | xargs -I{} basename {} .md | sort > /tmp/local_agents.txt
   
   # Plugin agents (from active install paths only)
   for plugin_dir in <active install paths>; do
     find "$plugin_dir/agents" -name "*.md" -type f 2>/dev/null | xargs -I{} basename {} .md
   done | sort > /tmp/plugin_agents.txt
   
   # Find duplicates
   comm -12 /tmp/local_agents.txt /tmp/plugin_agents.txt
   ```

   For each duplicate, read first 5 lines of each version:
   - HIGH if identical (pure duplication)
   - MEDIUM if diverged (user customized — note but don't push removal)

   **Impact**: User maintaining two versions of same agent.
   **Fix**: Remove local copy if identical to plugin version.

   ### Check 4: Zero-Skill Plugins
   For each enabled plugin, count its skills, MCP servers, agents, hooks, and rules. Flag any enabled plugin providing none of these — it's doing nothing.
   - MEDIUM severity

   ### Check 5: Disabled Plugins Still Installed
   List all disabled plugins. These consume disk space and clutter the registry.
   - LOW severity — suggest uninstalling if unused for 30+ days (check lastUpdated)

   ### Check 6: Stale Cache Versions
   For each plugin, check if multiple versions exist in the cache directory. Only the active version (from `installed_plugins.json`) is needed — older versions are waste.
   - MEDIUM if stale versions total > 10 MB
   - LOW otherwise

   ### Check 7: Rules Without Matching Languages
   For the current working directory (or the user's Projects directory), check which programming languages are actually present:
   ```bash
   find ~/Projects -maxdepth 3 -name "*.go" -o -name "*.rs" -o -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" -o -name "*.kt" -o -name "*.swift" -o -name "*.php" -o -name "*.pl" -o -name "*.cpp" -o -name "*.c" -o -name "*.java" 2>/dev/null | sed 's/.*\.//' | sort | uniq -c | sort -rn
   ```
   Compare against installed rule directories in `~/.claude/rules/`. Flag rule sets for languages with 0 files in any project as LOW severity.

   ### Check 8: Stale Project Configs

   Get the stale threshold from config (default 1 MB):
   Check `~/.claude/projects/` for directories that don't correspond to any existing project path:
   ```bash
   for dir in ~/.claude/projects/*/; do
     dirname=$(basename "$dir")
     # Claude Code encodes paths by replacing / with -
     # Reconstruct: leading - becomes /, remaining - become /
     path=$(echo "$dirname" | sed 's/^-/\//' | sed 's/-/\//g')
     if [ ! -d "$path" ]; then
       size=$(du -sh "$dir" 2>/dev/null | cut -f1)
       echo "ORPHAN: $dirname ($size)"
     fi
   done
   ```
   Note: The `-` to `/` conversion is lossy — directory names containing hyphens will produce false paths. To reduce false positives, only flag directories where the reconstructed path clearly doesn't exist AND the directory is >1 MB (meaningful size, configurable via `thresholds.orphaned_config_min_mb`). Flag as LOW severity.

   ### Check 9: Large Caches
   Flag any single cache directory over 50MB. Flag total plugin cache over 500MB.

### Check 10: Hook Conflicts and Context Injection Load
   **Collect hook registrations from active plugins only:**
   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   # Extract installPath for each enabled plugin
   ```

   For each active plugin, read hooks:
   ```bash
   hooks_file="$plugin_dir/hooks/hooks.json"
   # Parse: hook type, matcher pattern
   ```

   **Detect hook conflicts:**
   Two plugins conflict when they register for:
   - Same hook type + same/overlapping matcher (e.g., both match "*" or "Write")

   Build conflict matrix:
   | Hook Type | Matcher | Plugins | Risk |
   
   Risk levels:
   - LOW: Multiple observers (usually fine)
   - MEDIUM: Multiple plugins injecting content (context bloat)
   - HIGH: Multiple plugins modifying tool behavior (can fight)

   **Context injection analysis:**
   Count plugins with hooks on high-frequency events:
   - UserPromptSubmit: fires every message
   - PreToolUse/PostToolUse: fires every tool call

   Estimate tokens per invocation:
   - PreToolUse/PostToolUse with output: ~100-500 tokens
   - PreToolUse/PostToolUse silent: ~0 tokens
   - UserPromptSubmit: ~200-2,000 tokens

   Include in report:
   ```
   ## Context Injection Load
   Per-message injection: ~X tokens from hooks
   Over 200 messages: ~Y tokens
   ```

### Check 11: MCP Tool Collisions
   Collect MCP servers from all sources:
   ```bash
   # From active plugin install paths
   for plugin_dir in <active install paths>; do
     mcp_file="$plugin_dir/.mcp.json"
     [ -f "$mcp_file" ] && cat "$mcp_file"
   done
   
   # From global config
   cat ~/.claude/settings.json 2>/dev/null | grep -A100 '"mcpServers"'
   ```

   Flag if same MCP server name appears from multiple sources (e.g., playwright from both global config AND plugin).
   - CRITICAL: Same MCP loaded from 2+ sources (tool name conflicts)

4. **Classify findings**

   Assign severity to each finding:

   | Severity | Criteria |
   |----------|----------|
   | **CRITICAL** | Active conflict — two things fighting for the same job, causing errors or unpredictable behavior |
   | **HIGH** | Clear redundancy — something is fully superseded and should be removed |
   | **MEDIUM** | Waste — consuming resources (disk, tokens, context) for no benefit |
   | **LOW** | Cleanup opportunity — not harmful but clutters the ecosystem |

6. **Generate report**

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
   | 1 | <description of finding> | <source> | <recommended action> |
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

7. **Calculate health score**

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
   ## Health Score: 47/100

   ██████████████░░░░░░░░░░░░░░░░ 47/100

   Breakdown:
     Base score:              100
     HIGH findings (×2):       -20
     MEDIUM findings (×3):     -15
     LOW findings (×4):         -8
     Token cost > 5%:           -5
     No baseline snapshot:      -5
     ─────────────────────────
     Final:                      47
   ```

   Use the actual deductions. The bar is `Math.round(score / 100 * 30)` filled blocks out of 30.

   Score interpretation:
   - 90-100: Pristine — minimal bloat
   - 70-89: Healthy — some cleanup opportunities
   - 50-69: Bloated — significant redundancy
   - 0-49: Critical — major cleanup needed

8. **Done**

   Do NOT take any action. This skill is read-only. Direct the user to `/moltbloat:clean` if they want to act on findings.

</Steps>
