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
- User wants to see new commands after an update
</Use_When>

<Steps>

1. **Show the command reference**

   Output exactly:

   ```
   # moltbloat — Claude Code Ecosystem Auditor

   ## Analyze
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:audit` | Full ecosystem scan — finds redundancy, collisions, conflicts, staleness, and scores health (0-100) |
   | `/moltbloat:token-budget` | Context window cost analysis — shows what each plugin costs in tokens and dollars |
   | `/moltbloat:usage` | What you actually use vs what's installed, hook overhead, data compaction |

   ## Investigate
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:why <plugin>` | Deep dive — what does this plugin give you, what overlaps, keep or remove? |
   | `/moltbloat:depends` | Dependency graph — what each plugin provides and the blast radius of removal |
   | `/moltbloat:changelog` | Diff current ecosystem against your last snapshot — see what changed |

   ## Act
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:clean` | Interactive cleanup — review findings and selectively remove bloat |
   | `/moltbloat:clean --dry-run` | Preview cleanup actions without making changes |
   | `/moltbloat:profile` | Switch ecosystem configs, create/export/import profiles for team sharing |
   | `/moltbloat:snapshot` | Save current ecosystem as baseline for future drift detection |
   | `/moltbloat:snapshot trends` | Show historical trends and growth over time |

   ## System
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:doctor` | Self-diagnostic — check installation health, dependencies, and data integrity |

   ## Team
   | Command | Description |
   |---------|-------------|
   | `/moltbloat:team-report` | Aggregate ecosystem findings across team members for standardization |

   ---
   **Quick Start:**
   1. Run `/moltbloat:audit` for a full picture (includes compatibility checking)
   2. Run `/moltbloat:clean --dry-run` to preview cleanup
   3. Run `/moltbloat:clean` to remove bloat
   4. Run `/moltbloat:snapshot` to save clean state

   **Tip:** Run `/moltbloat:doctor` if you encounter any issues.

   **Configuration:**
   Edit `~/.moltbloat/config.json` to customize thresholds and defaults.
   ```

2. **Done**

</Steps>
