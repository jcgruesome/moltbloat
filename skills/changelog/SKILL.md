---
name: changelog
description: Release-aware deprecation — check installed plugins against known native Claude Code replacements
level: 2
---

<Purpose>
Cross-reference installed plugins and MCPs against a curated list of features that Claude Code now provides natively. When Claude ships a new feature that makes a plugin redundant, this skill flags it. Maintains a community-editable `superseded.json` rules file.
</Purpose>

<Use_When>
- User says "changelog", "what's native now", "deprecated", "superseded", "new in claude"
- After a Claude Code version upgrade
- When deciding whether to keep a plugin
</Use_When>

<Do_Not_Use_When>
- User wants a full audit — use `/moltbloat:audit`
- User wants to see what a plugin does — use `/moltbloat:why`
</Do_Not_Use_When>

<Steps>

1. **Load the superseded rules**

   Read the curated rules file from the plugin's data directory:
   ```bash
   cat ~/.claude/plugins/cache/moltbloat/moltbloat/*/data/superseded.json 2>/dev/null
   ```

   If not found, read from the source:
   ```bash
   cat /Users/james/Projects/moltbloat/data/superseded.json 2>/dev/null
   ```

   The rules file has this structure:
   ```json
   [
     {
       "name": "filesystem",
       "type": "mcp",
       "supersededBy": "native",
       "nativeFeature": "Read, Write, Edit, Glob, Grep tools",
       "sinceVersion": "1.0.0",
       "severity": "MEDIUM",
       "notes": "Claude Code has built-in file operations that are faster and better integrated"
     }
   ]
   ```

2. **Get current Claude Code version**

   ```bash
   claude --version 2>/dev/null || echo "unknown"
   ```

3. **Get installed plugins and MCPs**

   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   ```

   Build a list of all installed plugin names and MCP server names.

4. **Match against superseded rules**

   For each rule in superseded.json:
   - Check if the plugin/MCP is installed
   - Check if the Claude Code version is >= the `sinceVersion`
   - If both match, it's a finding

5. **Check for unknown plugins**

   For any installed plugin NOT in the superseded list, note it as "unreviewed" — the rules file doesn't have an opinion on it yet.

6. **Generate report**

   ```
   # Moltbloat Changelog Report

   **Claude Code version**: X.Y.Z
   **Superseded rules version**: <date of superseded.json>
   **Rules entries**: N

   ## Superseded (installed but now native)

   | Plugin/MCP | Native Replacement | Since | Severity | Action |
   |------------|-------------------|-------|----------|--------|
   | filesystem (MCP) | Read/Write/Edit/Glob/Grep | v1.0.0 | MEDIUM | Remove MCP |
   | memory (MCP) | claude-mem or native memory | v2.0.0 | MEDIUM | Remove if using claude-mem |
   | sequential-thinking (MCP) | Extended thinking | v1.5.0 | MEDIUM | Remove MCP |
   | ralph-loop (plugin) | OMC native ralph skill | OMC 4.0+ | HIGH | Uninstall plugin |

   ## Not Reviewed

   These plugins are installed but not in the superseded rules file:
   - oh-my-claudecode (orchestration — no native equivalent)
   - everything-claude-code (pattern library — no native equivalent)
   - ...

   ## How to Update Rules

   The superseded rules live in `data/superseded.json` in the moltbloat repo.
   To add a new rule:
   1. Edit `data/superseded.json`
   2. Add an entry with the plugin name, native replacement, and version
   3. Submit a PR to share with the team

   Run `/moltbloat:clean` to act on these findings.
   ```

7. **Done**

   Read-only. Direct to `/moltbloat:clean` for action.

</Steps>
