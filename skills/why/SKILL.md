---
name: why
description: Quick lookup — what does a specific plugin give you, what overlaps, and what it costs
level: 1
---

<Purpose>
Fast, focused answer to "what does plugin X do and should I keep it?" Shows what the plugin provides, what overlaps with it, its token cost, and a keep/remove recommendation.
</Purpose>

<Use_When>
- User says "why <plugin>", "what does <plugin> do", "should I keep <plugin>", "do I need <plugin>"
- User is deciding between two plugins
- Quick check before installing or removing something
</Use_When>

<Do_Not_Use_When>
- User wants the full dependency graph — use `/moltbloat:depends`
- User wants a full audit — use `/moltbloat:audit`
</Do_Not_Use_When>

<Steps>

1. **Parse the plugin name**

   The user should provide a plugin name as an argument. If not, ask:
   > Which plugin? (e.g., `/moltbloat:why claude-mem`)

2. **Find the plugin**

   ```bash
   # Check if installed
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null | grep -i "<plugin_name>"
   ```

   If not found, tell the user it's not installed and stop.

   Find its cache directory:
   ```bash
   find ~/.claude/plugins/cache -maxdepth 2 -type d -name "<plugin_name>" 2>/dev/null
   ```

3. **Quick inventory**

   Count what it provides (run in parallel):

   ```bash
   # Skills
   find "$PLUGIN_DIR" -path "*/skills/*/SKILL.md" -type f 2>/dev/null | wc -l

   # Agents
   find "$PLUGIN_DIR" -path "*/agents/*.md" -type f 2>/dev/null | wc -l

   # MCP config
   cat "$PLUGIN_DIR/.mcp.json" 2>/dev/null

   # Hooks
   cat "$PLUGIN_DIR/hooks/hooks.json" 2>/dev/null | head -5

   # CLAUDE.md size
   wc -c "$PLUGIN_DIR/CLAUDE.md" 2>/dev/null

   # Total disk
   du -sh "$PLUGIN_DIR" 2>/dev/null
   ```

4. **Check for overlaps**

   Quick grep across other plugins for similar skill names:
   ```bash
   # Get this plugin's skill names
   skill_names=$(find "$PLUGIN_DIR/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | xargs -I{} basename {})

   # Check if any other plugin has same skill names
   for skill in $skill_names; do
     find ~/.claude/plugins/cache -path "*/skills/$skill/SKILL.md" -not -path "*/<plugin_name>/*" 2>/dev/null
   done
   ```

   Check for agent overlaps:
   ```bash
   for agent in $(find "$PLUGIN_DIR/agents" -name "*.md" -type f 2>/dev/null | xargs -I{} basename {} .md); do
     ls ~/.claude/agents/$agent.md 2>/dev/null
     find ~/.claude/plugins/cache -path "*/agents/$agent.md" -not -path "*/<plugin_name>/*" 2>/dev/null
   done
   ```

5. **Check superseded rules**

   ```bash
   cat ~/.claude/plugins/cache/moltbloat/moltbloat/*/data/superseded.json 2>/dev/null | grep -i "<plugin_name>"
   ```

6. **Output the card**

   Format as a compact card:

   ```
   # <plugin_name> @ <version>

   **Status**: enabled/disabled
   **Installed**: <date>
   **Disk**: X MB

   ## Provides
   - X skills (list top 5)
   - X agents
   - X MCP servers with ~Y tools
   - X hooks

   ## Token Cost
   ~X tokens per session (Y% of context window)

   ## Overlaps
   - Skill "foo" also in plugin-bar
   - Agent "architect" also in ~/.claude/agents/
   - (or "No overlaps detected")

   ## Superseded?
   - (yes/no + details from superseded.json if applicable)

   ## Verdict
   **KEEP** — core orchestration, no native replacement
   (or)
   **CONSIDER REMOVING** — superseded by native X, overlaps with Y
   (or)
   **REMOVE** — disabled, zero skills, no unique functionality
   ```

7. **Done**

</Steps>
