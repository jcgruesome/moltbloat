---
name: depends
description: Dependency graph — show what each plugin provides and the blast radius of removing it
level: 2
---

<Purpose>
Map the dependency graph of the Claude Code ecosystem. For any plugin, show exactly what it contributes (skills, agents, MCPs, hooks, commands) and what would break or be lost if it were removed. Answers "what do I lose if I disable X?"
</Purpose>

<Use_When>
- User says "depends", "dependency", "what does X give me", "blast radius", "what if I remove"
- Before removing a plugin via `/moltbloat:clean`
- When deciding between overlapping plugins
</Use_When>

<Do_Not_Use_When>
- User wants a full audit — use `/moltbloat:audit`
- User wants a quick single-plugin lookup — use `/moltbloat:why`
</Do_Not_Use_When>

<Steps>

1. **Determine scope**

   Check if the user specified a plugin name. If yes, analyze just that plugin. If no, build the full graph for all enabled plugins.

2. **Inventory each plugin's contributions**

   For each enabled plugin, scan its cached directory to catalog what it provides:

   ```bash
   PLUGIN_DIR=~/.claude/plugins/cache/<marketplace>/<plugin>/<version>
   ```

   **Skills:**
   ```bash
   find "$PLUGIN_DIR/skills" -name "SKILL.md" -type f 2>/dev/null | while read f; do
     dir=$(dirname "$f")
     name=$(basename "$dir")
     echo "skill: $name"
   done
   ```

   **Agents:**
   ```bash
   find "$PLUGIN_DIR/agents" -name "*.md" -type f 2>/dev/null | while read f; do
     name=$(basename "$f" .md)
     echo "agent: $name"
   done
   ```

   **MCP servers:**
   ```bash
   cat "$PLUGIN_DIR/.mcp.json" 2>/dev/null
   ```
   Parse the JSON to list MCP server names and their tool counts.

   **Hooks:**
   ```bash
   cat "$PLUGIN_DIR/hooks/hooks.json" 2>/dev/null
   ```
   List hook types (PreToolUse, PostToolUse, Stop, etc.) and what they trigger.

   **Commands:**
   ```bash
   find "$PLUGIN_DIR/commands" -name "*.md" -type f 2>/dev/null | while read f; do
     name=$(basename "$f" .md)
     echo "command: $name"
   done
   ```

   **CLAUDE.md instructions:**
   ```bash
   wc -c "$PLUGIN_DIR/CLAUDE.md" 2>/dev/null
   wc -c "$PLUGIN_DIR/AGENTS.md" 2>/dev/null
   ```

3. **Detect cross-plugin dependencies**

   Build a grep pattern dynamically from all installed plugin names, then check if any plugin's skills or hooks reference another plugin:
   ```bash
   # Build pattern from all installed plugin names (excluding the current one)
   pattern=$(cat ~/.claude/plugins/installed_plugins.json 2>/dev/null | grep -oE '"[^"]+@[^"]+' | sed 's/^"//' | cut -d'@' -f1 | grep -v "<current_plugin>" | paste -sd'|' -)
   grep -rE "$pattern" "$PLUGIN_DIR/skills/" "$PLUGIN_DIR/hooks/" 2>/dev/null
   ```

4. **Build the dependency table**

   For a single plugin query:

   ```
   # Moltbloat Dependency Report: <plugin-name>

   ## Provides

   | Type | Count | Items |
   |------|-------|-------|
   | Skills | <N> | <list top skill names> |
   | Agents | <N> | <list agent names> |
   | MCP servers | <N> | <list server names and tool categories> |
   | MCP tools | ~<N> | <list tool name samples> |
   | Hooks | <N> | <list hook types registered> |
   | Commands | <N> | <list or "—"> |
   | CLAUDE.md | <X> KB (~<Y> tokens) | <description> |

   ## Blast Radius if Removed

   **You would lose:**
   <list each category with counts and notable items>

   **Other plugins affected:**
   <list any plugins that reference this one, or "None">

   **Overlaps with other installed plugins:**
   <list detected skill/agent/MCP overlaps with other plugins>

   ## Token Cost
   <breakdown by CLAUDE.md + MCP tools + skill listings>
   - **Total: ~<X> tokens (<Y>% of context window)**
   ```

   For a full graph:

   ```
   # Moltbloat Full Dependency Graph

   | Plugin | Skills | Agents | MCPs | Tools | Hooks | Tokens |
   |--------|--------|--------|------|-------|-------|--------|
   <one row per installed plugin with actual counts>
   | **TOTAL** | **X** | **X** | **X** | **X** | **X** | **~X** |

   ## Cross-Plugin Dependencies
   <list any detected references between plugins, or "None">

   ## Overlap Map
   <list detected agent/skill/MCP overlaps across all plugins>
   ```

5. **Done**

   This skill is read-only. Suggest `/moltbloat:clean` to act on findings or `/moltbloat:why <plugin>` for a quick single-plugin summary.

</Steps>
