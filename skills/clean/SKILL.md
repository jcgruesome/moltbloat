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

   ## CRITICAL (fix these)
   1. [Skills] 30+ skill name collisions between <plugin-a> and <plugin-b>
   2. ...

   ## HIGH (act on these)
   3. [Agents] 25 local agents duplicate <plugin> agents
   4. ...

   ## MEDIUM (worth considering)
   5. [Plugin] <name> — 0 skills, 0 MCP servers, 0 agents
   6. [Cache] Stale versions consuming X MB
   7. ...

   ## LOW (optional cleanup)
   8. [Plugin] <name> — disabled for 60+ days
   9. [Project] Orphaned config — X MB
   10. ...

   Reply with numbers to fix (e.g., "1, 3, 5") or "all high", "all", or "skip".
   ```

3. **Process each selected finding**

   For each finding the user selects, present the specific action and ask for confirmation.

   For each finding type, use the appropriate template. Replace all placeholders with actual values from the audit.

   ### Skill collision fix
   ```
   ## Finding N: <count> skill collisions between <plugin-a> and <plugin-b>

   **What**: Both plugins provide skills with the same names: <list names>
   **Why fix**: Only one version runs — you may not be getting the one you expect.
   **Action**: Uninstall whichever plugin provides less unique value. Run
   `/moltbloat:why <plugin>` on each to compare.
   **Risk**: Losing skills unique to the removed plugin

   Which plugin to remove? (<plugin-a> / <plugin-b> / skip)
   ```

   If user chooses, run the uninstall command. If it fails, report the error and move on.

   ### Agent dedup
   ```
   ## Finding N: Duplicate agent — <name>.md

   **What**: `<name>.md` exists in both ~/.claude/agents/ (local) and
   <plugin> (plugin-provided).
   **Comparison**: <read first 5 lines of each and summarize differences>
   **Action**: Remove local ~/.claude/agents/<name>.md
   **Risk**: Low if versions are identical. If the local version has custom
   modifications, those will be lost.

   Proceed? (yes/no/skip)
   ```

   Before removing a local agent, read both versions. If the local version has custom modifications, warn the user and recommend keeping it.

   ### Zero-skill plugin removal
   ```
   ## Finding N: <plugin> — no skills, no MCP, no agents

   **What**: Plugin is installed but provides nothing detectable.
   **Action**: Uninstall plugin
   **Command**: `claude plugin remove <plugin>`
   **Risk**: Plugin may provide hooks or rules not detected by this scan

   Proceed? (yes/no/skip)
   ```

   ### Disabled plugin cleanup
   ```
   ## Finding N: <plugin> — disabled for <X> days

   **What**: Plugin is installed but disabled. Last updated <date>.
   **Action**: Uninstall to reduce clutter
   **Risk**: If you need it later, you can reinstall

   Proceed? (yes/no/skip)
   ```

   ### Stale cache cleanup
   ```
   ## Finding N: Old plugin cache — X MB recoverable

   **What**: <count> old version cache directories consuming X MB total
   **Action**: Remove old version caches (keeps current active versions)
   **Risk**: Cannot roll back to previous plugin versions after removal

   Proceed? (yes/no/skip)
   ```

   ### Orphaned project config
   ```
   ## Finding N: Orphaned project config — X MB

   **What**: Project config at <path> doesn't map to an existing project directory
   **Action**: Delete the orphaned config directory
   **Risk**: Loss of project-specific memory and settings for a project that no longer exists

   Proceed? (yes/no/skip)
   ```

4. **Generate cleanup report**

   After processing all selected findings:

   ```
   # Cleanup Complete

   ## Actions Taken
   - <list each action performed with specific names>
   - ...

   ## Skipped
   - <list each finding the user chose to skip>
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
