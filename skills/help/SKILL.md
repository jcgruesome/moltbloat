---
name: help
description: Show all available moltbloat commands with descriptions
level: 1
---

<Purpose>
Display all available moltbloat commands with brief descriptions so the user knows what's available.
</Purpose>

<Use_When>
- User runs `/moltbloat:help` or asks "what can moltbloat do"
- User is new to the plugin
</Use_When>

<Steps>

1. **Show the command reference**

   Output exactly:

   ```
   # moltbloat — Claude Code Ecosystem Auditor

   ## Commands

   ### Analyze
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:audit` | Full ecosystem scan — finds redundancy, collisions, staleness, and scores health (0-100) |
   | `/moltbloat:token-budget` | Context window cost analysis — shows what each plugin costs in tokens and dollars |
   | `/moltbloat:usage` | What you actually use vs what's installed (requires tracking data) |

   ### Investigate
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:why <plugin>` | Deep dive — what does this plugin give you, what overlaps, keep or remove? |
   | `/moltbloat:depends` | Dependency graph — what each plugin provides and the blast radius of removal |
   | `/moltbloat:compat` | Conflict detection — hook collisions, skill name shadowing, MCP tool overlaps |
   | `/moltbloat:changelog` | Diff current ecosystem against your last snapshot — see what changed |

   ### Act
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:clean` | Interactive cleanup — review findings and selectively remove bloat |
   | `/moltbloat:profile` | Switch ecosystem configs — lean, full, frontend, backend, or custom profiles |
   | `/moltbloat:snapshot` | Save current ecosystem as baseline for future drift detection |

   ### Team
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:team-report` | Aggregate ecosystem findings across team members for standardization |

   ---
   *Tip: Start with `/moltbloat:audit` for a full picture, then use `/moltbloat:why <plugin>` to investigate specific findings.*
   ```

2. **Done**

</Steps>
