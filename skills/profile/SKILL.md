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

   If no subcommand, show `list`.

2. **For `list` — show available profiles**

   Check for saved profiles:
   ```bash
   ls ~/.moltbloat/profiles/*.json 2>/dev/null
   ```

   Always show the built-in profiles plus any custom ones:

   ```
   # Moltbloat Profiles

   ## Built-in
   | Profile | Plugins Enabled | Est. Token Cost | Best For |
   |---------|----------------|-----------------|----------|
   | lean | 2-3 (core only) | ~5,000 | Quick edits, simple tasks |
   | full | all enabled | ~40,000+ | Complex features, multi-file work |
   | frontend | web-focused | ~18,000 | React/Next.js/Vercel work |
   | backend | server-focused | ~15,000 | APIs, databases, infrastructure |

   ## Custom
   | Profile | Plugins | Created |
   |---------|---------|---------|
   | my-kotlin | 6 plugins | 2026-03-15 |

   ## Current State
   - Active profile: <name or "none (manual config)">
   - Enabled plugins: X
   - Est. token cost: ~Y

   Use `/moltbloat:profile apply <name>` to switch.
   ```

3. **For `create` — build a custom profile**

   Ask the user what they want enabled. Start by showing all installed plugins:

   ```bash
   cat ~/.claude/plugins/installed_plugins.json 2>/dev/null
   ```

   Present a checklist:
   ```
   Creating profile: <name>

   Select which plugins to ENABLE (all others will be disabled):

   ## Orchestration
   - [?] oh-my-claudecode (32 skills, 19 agents, ~16K tokens)
   - [?] superpowers (14 skills, ~2.8K tokens)

   ## Development
   - [?] everything-claude-code (108 skills, ~4.2K tokens)
   - [?] playwright (browser automation, ~8.7K tokens)
   - [?] vercel-plugin (40 skills, ~8.5K tokens)

   ## Data
   - [?] claude-mem (cross-session memory, ~3.1K tokens)
   - [?] supabase (database ops, ~2K tokens)

   ## Other
   - [?] moltbloat (this plugin — always recommended)
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

   For built-in profiles, use these defaults:

   **lean:**
   - Enable: oh-my-claudecode, moltbloat
   - Disable: everything else

   **full:**
   - Enable: everything currently installed

   **frontend:**
   - Enable: oh-my-claudecode, vercel-plugin, playwright, superpowers, moltbloat
   - Disable: supabase, language-specific plugins not related to TS/JS

   **backend:**
   - Enable: oh-my-claudecode, supabase, claude-mem, superpowers, moltbloat
   - Disable: playwright, vercel-plugin, frontend-design

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

   Based on 14 days of tracking, you actively use:
   - oh-my-claudecode (47 invocations)
   - vercel-plugin (23 invocations)
   - playwright (12 invocations)
   - superpowers (8 invocations)
   - moltbloat (5 invocations)

   These had zero usage and can be safely disabled:
   - everything-claude-code (0 invocations — saves ~4,200 tokens)
   - claude-mem (0 invocations — saves ~3,100 tokens)
   - ...

   Save as profile? (name it, or "skip")
   ```

7. **Done**

   Remind user to restart session for changes to take effect.

</Steps>
