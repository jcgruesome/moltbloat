---
name: profile
description: Switch between ecosystem configurations — lean, full, frontend, backend, or custom profiles
level: 3
---

<Purpose>
Manage named profiles that enable/disable specific plugins and rule sets. Switch instantly between "lean" (minimal overhead for simple tasks) and "full" (everything enabled for complex work). Create custom profiles per project type.
</Purpose>

<Use_When>
- User says "profile", "switch to lean", "switch to full", "lightweight mode", "minimize plugins"
- Before starting a focused task that doesn't need the full ecosystem
- When context pressure is high and user wants to reduce overhead
- When setting up project-type-specific configurations
</Use_When>

<Do_Not_Use_When>
- User wants to permanently remove plugins — use `/moltbloat:clean`
- User wants to see what's installed — use `/moltbloat:audit`
</Do_Not_Use_When>

<Safety>
- Profiles only enable/disable plugins — they never uninstall anything
- The current state is always saved before switching so you can go back
- A "restore" command returns to the pre-profile state
</Safety>

<Steps>

1. **Parse the command**

   The user provides a subcommand:
   - `/moltbloat:profile list` — show available profiles
   - `/moltbloat:profile show <name>` — show what a profile enables/disables
   - `/moltbloat:profile create <name>` — create a new profile interactively
   - `/moltbloat:profile apply <name>` — switch to a profile
   - `/moltbloat:profile restore` — return to pre-switch state
   - `/moltbloat:profile auto` — suggest a profile based on usage data
   - `/moltbloat:profile export <name>` — export a profile to a shareable JSON file
   - `/moltbloat:profile import <path>` — import a profile from a file or URL

   If no subcommand, show `list`.

2. **For `list` — show available profiles**

   Check for saved profiles:
   ```bash
   ls ~/.moltbloat/profiles/*.json 2>/dev/null
   ```

   Always show the built-in profiles plus any custom ones. For built-in profiles, dynamically compute plugin counts and token estimates based on what's actually installed:

   ```
   # Moltbloat Profiles

   ## Built-in
   | Profile | Plugins Enabled | Est. Token Cost | Best For |
   |---------|----------------|-----------------|----------|
   | lean | <N> (core only) | ~<X> | Quick edits, simple tasks |
   | full | <N> (all) | ~<X> | Complex features, multi-file work |
   | frontend | <N> (web-related) | ~<X> | Frontend/UI work |
   | backend | <N> (server-related) | ~<X> | APIs, databases, infrastructure |

   ## Custom
   <list saved profiles from ~/.moltbloat/profiles/*.json>

   ## Current State
   - Active profile: <name or "none (manual config)">
   - Enabled plugins: <N>
   - Est. token cost: ~<X>

   Use `/moltbloat:profile apply <name>` to switch.
   ```

3. **For `create` — build a custom profile**

   Ask the user what they want enabled. Start by showing all installed plugins:

   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   ```

   Present a checklist of all installed plugins, dynamically grouped by what they provide:

   ```
   Creating profile: <name>

   Select which plugins to ENABLE (all others will be disabled):

   <For each installed plugin, show: name, skill count, agent count, MCP count, estimated token cost>
   <Group by rough category based on plugin description/keywords: orchestration, development, data, tooling, etc.>

   - [?] <plugin-name> (<N> skills, <M> agents, ~<X>K tokens)
   - [?] ...

   Reply with the names to enable, or "all except X, Y".
   ```

   Save the profile:
   ```json
   {
     "name": "<name>",
     "created": "2026-04-03T15:00:00Z",
     "description": "<user description>",
     "plugins": {
       "oh-my-claudecode": "enabled",
       "everything-claude-code": "disabled",
       "vercel-plugin": "enabled",
       "playwright": "enabled"
     }
   }
   ```

   Write to `~/.moltbloat/profiles/<name>.json`.

4. **For `apply` — switch to a profile**

   **4a. Save current state**
   ```bash
   # Capture current enabled/disabled state of all plugins
   cat ~/.claude/plugins/installed_plugins.json > ~/.moltbloat/profiles/_pre-switch-state.json
   ```

   **4b. Load the target profile**
   ```bash
   cat ~/.moltbloat/profiles/<name>.json
   ```

   For built-in profiles, dynamically categorize installed plugins:

   **lean:**
   - Enable: only moltbloat + the single plugin with the most skills (likely the user's primary orchestrator)
   - Disable: everything else

   **full:**
   - Enable: everything currently installed

   **frontend:**
   - Scan installed plugins for frontend-related keywords in their skills/descriptions (react, next, css, component, browser, playwright, design, UI, vercel, deploy)
   - Enable: matches + moltbloat
   - Disable: everything else

   **backend:**
   - Scan installed plugins for backend-related keywords in their skills/descriptions (database, api, server, sql, auth, docker, infrastructure, supabase, redis)
   - Enable: matches + moltbloat
   - Disable: everything else

   For any built-in profile, list the actual plugins that would be enabled/disabled before applying — let the user confirm.

   **4c. Apply changes**

   For each plugin that needs to change state:
   ```bash
   claude plugin disable <plugin-name> 2>&1
   # or
   claude plugin enable <plugin-name> 2>&1
   ```

   **4d. Report**
   ```
   Switched to profile: <name>

   Enabled: plugin-a, plugin-b, plugin-c
   Disabled: plugin-d, plugin-e

   Token savings: ~X tokens/session vs previous state
   Cost savings: ~$X.XX per message

   Restart your session for changes to take effect.
   Use `/moltbloat:profile restore` to return to previous state.
   ```

5. **For `restore` — return to pre-switch state**

   ```bash
   cat ~/.moltbloat/profiles/_pre-switch-state.json
   ```

   Re-enable/disable plugins to match the saved state. Confirm before applying.

6. **For `auto` — suggest based on usage**

   Read usage data:
   ```bash
   cat ~/.moltbloat/usage.jsonl 2>/dev/null
   ```

   If usage data exists, analyze which plugins have >0 invocations in the last 14 days. Suggest a profile that enables only those plugins.

   ```
   ## Auto-Generated Profile Based on Your Usage

   Based on <N> days of tracking, you actively use:
   <list each plugin with >0 invocations, sorted by count>

   These had zero usage and can be safely disabled:
   <list each plugin with 0 invocations and estimated token savings>

   Save as profile? (name it, or "skip")
   ```

7. **For `export` — share a profile**

   Export a profile as a portable JSON file that teammates can import:

   ```bash
   cat ~/.moltbloat/profiles/<name>.json 2>/dev/null
   ```

   If the profile doesn't exist, error and show available profiles.

   The exported file is the profile JSON with an added `exported` metadata block:
   ```json
   {
     "name": "<name>",
     "created": "<timestamp>",
     "exported": "<now>",
     "exportedBy": "<git user.name or 'unknown'>",
     "description": "<user description>",
     "plugins": {
       "<plugin-a>": "enabled",
       "<plugin-b>": "disabled"
     }
   }
   ```

   Write to the current directory as `<name>.moltbloat-profile.json`:
   ```bash
   # Get git user for attribution
   git config user.name 2>/dev/null || echo "unknown"
   ```

   Report:
   ```
   Exported profile "<name>" to ./<name>.moltbloat-profile.json
   Share this file with teammates or commit it to your config repo.
   They can import it with: /moltbloat:profile import <path>
   ```

8. **For `import` — load a shared profile**

   The user provides a file path. Read and validate:
   ```bash
   cat <path> 2>/dev/null
   ```

   Validate the JSON has at minimum a `name` and `plugins` object. If invalid, error with what's wrong.

   Show the user what the profile contains:
   ```
   Importing profile: "<name>"
   Created by: <exportedBy> on <created>

   This profile will:
     Enable:  <list plugins marked enabled>
     Disable: <list plugins marked disabled>
     Skip:    <list plugins in profile but not installed locally>

   Note: Plugins in the profile that aren't installed locally will be skipped.
   You may need to install them first.

   Save this profile? (yes / no)
   ```

   If confirmed, save to `~/.moltbloat/profiles/<name>.json` (stripping the `exported`/`exportedBy` metadata).

   Report:
   ```
   Profile "<name>" imported and saved.
   Apply it with: /moltbloat:profile apply <name>
   ```

9. **Done**

   Remind user to restart session for changes to take effect.

</Steps>
