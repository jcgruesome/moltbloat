---
name: compat
description: Detect plugin conflicts — hook collisions, skill name shadowing, MCP tool overlaps
level: 2
---

<Purpose>
Scan all installed plugins for conflicts that cause unpredictable behavior: hooks fighting over the same events, skills with the same name from different plugins (only one runs), and MCP tools with colliding names. Catches problems at audit time instead of when things break mysteriously.
</Purpose>

<Use_When>
- User says "compat", "compatibility", "conflicts", "why isn't X working"
- After installing a new plugin
- When experiencing weird behavior or skills not running as expected
</Use_When>

<Do_Not_Use_When>
- User wants a full audit — use `/moltbloat:audit` (which should call this check too)
- User wants to see what a plugin provides — use `/moltbloat:why`
</Do_Not_Use_When>

<Steps>

1. **Collect all plugin hook registrations**

   First, get the active install paths from the plugin registry (to avoid scanning stale cache versions):
   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   ```
   Extract the `installPath` for each plugin entry. Only scan those directories.

   For each active plugin directory, read its hooks:
   ```bash
   for plugin_dir in <active install paths>; do
     hooks_file="$plugin_dir/hooks/hooks.json"
     if [ -f "$hooks_file" ]; then
       plugin=$(basename "$(dirname "$plugin_dir")")
       echo "=== $plugin ==="
       cat "$hooks_file"
     fi
   done 2>/dev/null
   ```

   Parse each hooks.json to extract: hook type (PreToolUse, PostToolUse, Stop, etc.) and matcher patterns.

2. **Detect hook conflicts**

   Two plugins conflict when they both register hooks for:
   - Same hook type (e.g., both have PostToolUse)
   - Same or overlapping matcher (e.g., both match "*" or both match "Write")

   This doesn't always cause problems, but hooks that modify behavior (not just observe) can fight.

   Build a conflict matrix dynamically from the collected hook data:
   ```
   ## Hook Overlap Matrix

   | Hook Type | Matcher | Plugins | Conflict Risk |
   |-----------|---------|---------|---------------|
   <one row per hook type+matcher combination where 2+ plugins overlap>
   ```

   Risk levels:
   - **LOW**: Multiple observers on the same event (common, usually fine)
   - **MEDIUM**: Multiple plugins injecting content on the same event (can bloat context)
   - **HIGH**: Multiple plugins modifying tool behavior on the same matcher

3. **Detect skill name shadowing**

   Build a map of all skill names to their source plugin. Use only active install paths from `installed_plugins.json` (not stale cache versions):
   ```bash
   for plugin_dir in <active install paths>; do
     plugin=$(basename "$(dirname "$plugin_dir")")
     find "$plugin_dir/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | while read skill_dir; do
       skill=$(basename "$skill_dir")
       echo "$skill|$plugin"
     done
   done 2>/dev/null | sort
   ```

   Find skill names that appear in multiple plugins:
   ```bash
   # ... | cut -d'|' -f1 | sort | uniq -d
   ```

   For each collision:
   ```
   ## Skill Name Collisions

   | Skill Name | Plugin A | Plugin B | Which Runs? |
   |------------|----------|----------|-------------|
   <one row per collision, populated from actual data>

   **Impact**: When you invoke `/<skill>`, it's ambiguous which plugin's version runs.
   The plugin loaded last typically wins, but this is not guaranteed.

   **Fix options**:
   - Disable one of the conflicting plugins
   - Use fully-qualified names: `/plugin-a:skill` vs `/plugin-b:skill`
   ```

4. **Detect MCP tool collisions**

   Collect all MCP server names and their tools. Only check active plugin install paths (from `installed_plugins.json`), not stale cache versions:
   ```bash
   for plugin_dir in <active install paths>; do
     mcp_file="$plugin_dir/.mcp.json"
     if [ -f "$mcp_file" ]; then
       plugin=$(basename "$(dirname "$plugin_dir")")
       echo "=== $plugin ==="
       cat "$mcp_file"
     fi
   done
   ```

   Also check global MCP config:
   ```bash
   cat ~/.claude/settings.json 2>/dev/null  # mcpServers section
   ```

   Flag if the same MCP server name appears from multiple sources (e.g., playwright from both global config and plugin).

5. **Detect agent name collisions**

   ```bash
   # Local agents
   ls ~/.claude/agents/*.md 2>/dev/null | xargs -I{} basename {} .md | sort > /tmp/local_agents.txt

   # Plugin agents
   find ~/.claude/plugins/cache -path "*/agents/*.md" -type f 2>/dev/null | xargs -I{} basename {} .md | sort > /tmp/plugin_agents.txt

   # Find duplicates
   comm -12 /tmp/local_agents.txt /tmp/plugin_agents.txt
   ```

6. **Context injection analysis**

   Count how many plugins inject content on UserPromptSubmit and PreToolUse — these fire frequently and compound. List each plugin that has hooks on these events, with estimated token cost per invocation:

   ```
   ## Context Injection Load

   Every time you submit a prompt:
   <for each plugin with UserPromptSubmit hooks, list: name, hook description, estimated token output>

   Every tool call:
   <for each plugin with PreToolUse/PostToolUse hooks, list: name, hook description, whether it produces output>

   **Estimated per-message injection**: ~<X> tokens from hooks alone
   **Over 200 messages**: ~<Y> tokens just from hook injections
   ```

7. **Generate report**

   ```
   # Moltbloat Compatibility Report

   ## Summary
   - Hook overlaps: X (Y medium/high risk)
   - Skill name collisions: X
   - MCP tool collisions: X
   - Agent name collisions: X
   - Hook injection load: ~X tokens/message

   ## CRITICAL Conflicts
   (list any HIGH risk items)

   ## Warnings
   (list MEDIUM risk items)

   ## Info
   (list LOW risk observations)

   ## Recommendations
   - Use fully-qualified skill names when conflicts exist: `/plugin:skill`
   - Consider disabling duplicate MCP sources
   - Hook injection load of X tokens/message costs ~$Y/day
   ```

8. **Done**

   Read-only. Direct to `/moltbloat:clean` or `/moltbloat:profile` for action.

</Steps>
