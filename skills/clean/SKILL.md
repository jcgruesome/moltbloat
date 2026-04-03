---
name: clean
description: Interactive cleanup — review audit findings and selectively remove bloat with confirmation before each action
level: 3
---

<Purpose>
Act on findings from `/moltbloat:audit`. Walk through each finding interactively, explain what it is, and offer to fix it — with explicit user confirmation before any destructive action.
</Purpose>

<Use_When>
- User wants to clean up their Claude Code ecosystem
- User says "clean", "cleanup", "remove bloat", "fix findings"
- After running `/moltbloat:audit` and seeing findings they want to address
</Use_When>

<Do_Not_Use_When>
- User just wants to see what's wrong — use `/moltbloat:audit`
- User only wants token cost info — use `/moltbloat:token-budget`
</Do_Not_Use_When>

<Safety>
- NEVER delete or modify anything without explicit user confirmation
- NEVER auto-fix multiple findings at once — present each individually
- ALWAYS explain what will change and what the impact is
- ALWAYS offer to skip any finding
- For plugin uninstalls, prefer `claude plugin remove` over manual deletion
- Back up configs before modifying settings files
</Safety>

<Steps>

1. **Run the audit first**

   If no recent audit results are available in the conversation, run the `/moltbloat:audit` skill first to collect findings. If audit results are already present from an earlier invocation in this session, use those.

2. **Present the cleanup menu**

   Show the user a numbered list of all findings from the audit, grouped by severity:

   ```
   # Moltbloat Cleanup

   Found X issues to review. I'll walk through each one — you decide what to fix.

   ## HIGH (act on these)
   1. [Plugin] ralph-loop superseded by OMC native ralph
   2. [Plugin] Old vercel superseded by vercel-plugin
   3. ...

   ## MEDIUM (worth considering)
   4. [MCP] filesystem server redundant with native tools
   5. [MCP] memory server redundant with claude-mem
   6. ...

   ## LOW (optional cleanup)
   7. [Plugin] linear — disabled, no skills, likely unused
   8. [Plugin] slack — disabled, no skills
   9. ...

   Reply with numbers to fix (e.g., "1, 2, 4") or "all high", "all", or "skip".
   ```

3. **Process each selected finding**

   For each finding the user selects, present the specific action and ask for confirmation.

   ### Plugin removal
   ```
   ## Finding 1: ralph-loop plugin superseded by OMC

   **What**: The `ralph-loop` plugin (v1.0.0) provides an iterative loop feature.
   **Why remove**: oh-my-claudecode includes a native `ralph` skill that is more
   integrated and actively maintained. Having both creates ambiguity about which runs.
   **Action**: Uninstall ralph-loop plugin
   **Command**: `claude plugin remove ralph-loop`
   **Risk**: None — OMC's ralph is the canonical implementation

   Proceed? (yes/no/skip)
   ```

   If user confirms, run the uninstall command. If it fails, report the error and move on.

   ### MCP server removal
   ```
   ## Finding 4: filesystem MCP redundant with native tools

   **What**: MCP server `filesystem` (@modelcontextprotocol/server-filesystem)
   registered in ~/.claude/mcp-configs/mcp-servers.json
   **Why remove**: Claude Code has native Read, Write, Edit, Glob, and Grep tools
   that are faster and better integrated. The filesystem MCP adds ~350 tokens of
   tool definitions for no additional capability.
   **Action**: Remove `filesystem` entry from mcp-servers.json
   **Risk**: None — native tools are superior

   Proceed? (yes/no/skip)
   ```

   If user confirms:
   1. Read the current mcp-servers.json
   2. Back up to mcp-servers.json.bak
   3. Remove the specific entry
   4. Write the updated file
   5. Confirm the change

   ### Disabled plugin cleanup
   ```
   ## Finding 7: linear plugin — disabled, unused

   **What**: `linear` plugin is installed but disabled. No skills, MCP only.
   **Last updated**: <date>
   **Action**: Uninstall to reduce clutter
   **Risk**: If you need Linear integration later, you can reinstall

   Proceed? (yes/no/skip)
   ```

   ### Agent dedup
   ```
   ## Finding N: Duplicate agent — architect.md

   **What**: `architect.md` exists in both ~/.claude/agents/ (local) and
   oh-my-claudecode plugin (plugin-provided).
   **Comparison**: Local version is a generic template. OMC version has model
   routing, tool restrictions, and investigation protocols.
   **Action**: Remove local ~/.claude/agents/architect.md (OMC version is superior)
   **Risk**: Low — OMC agent is more capable. Remove only if you haven't customized the local version.

   Proceed? (yes/no/skip)
   ```

   Before removing a local agent, read both versions and confirm the plugin version is indeed more capable. If the local version has custom modifications, warn the user.

   ### Stale cache cleanup
   ```
   ## Finding N: Old plugin cache — X MB recoverable

   **What**: Plugin cache directories for old versions consuming X MB
   **Action**: Remove old version caches (keeps current versions)
   **Risk**: Cannot roll back to previous plugin versions after removal

   Proceed? (yes/no/skip)
   ```

4. **Generate cleanup report**

   After processing all selected findings:

   ```
   # Cleanup Complete

   ## Actions Taken
   - Uninstalled ralph-loop plugin
   - Removed filesystem MCP from mcp-servers.json
   - ...

   ## Skipped
   - linear plugin (user chose to keep)
   - ...

   ## Disk Space Recovered
   ~X MB

   ## Estimated Token Savings
   ~X tokens per session

   ## Next Steps
   - Run `/moltbloat:audit` again to verify clean state
   - Run `/moltbloat:token-budget` to see updated context costs
   ```

5. **Done**

</Steps>
