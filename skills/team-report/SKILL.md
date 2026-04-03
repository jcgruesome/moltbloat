---
name: team-report
description: Aggregate ecosystem findings across team members for standardization
level: 3
---

<Purpose>
Collect and aggregate moltbloat snapshots from multiple team members to identify common issues, standardize the team's Claude Code setup, and recommend a shared baseline configuration.
</Purpose>

<Use_When>
- User says "team report", "team audit", "standardize", "compare setups"
- When onboarding new team members to establish a standard Claude setup
- When deciding which plugins should be team-standard vs optional
</Use_When>

<Do_Not_Use_When>
- User wants their own audit — use `/moltbloat:audit`
- Only one person uses Claude Code on the team
</Do_Not_Use_When>

<Steps>

1. **Collect snapshots**

   Ask the user how they want to provide team data. Options:

   **Option A: Shared directory**
   Team members export their snapshots to a shared location:
   ```bash
   # Each team member runs:
   cp ~/.moltbloat/baseline.json /shared/moltbloat/<username>.json
   ```
   Then read all files from that directory.

   **Option B: Paste mode**
   Team members share their `~/.moltbloat/baseline.json` contents. Read each one.

   **Option C: Git repo**
   If the team has a shared config repo, check for snapshot files:
   ```bash
   find <repo> -name "*.moltbloat.json" -type f 2>/dev/null
   ```

2. **Parse and aggregate**

   For each team member's snapshot, extract:
   - Plugins installed (name + version + enabled/disabled)
   - MCP servers configured
   - Skills count
   - Rules directories
   - Token cost estimate
   - Disk usage

3. **Compute commonality matrix**

   For each plugin, count how many team members have it installed:

   ```
   # Team Plugin Matrix (5 members)

   | Plugin | Alice | Bob | Carol | Dave | Eve | Coverage |
   |--------|-------|-----|-------|------|-----|----------|
   | oh-my-claudecode | Y | Y | Y | Y | Y | 100% |
   | everything-claude-code | Y | Y | Y | Y | N | 80% |
   | vercel-plugin | Y | Y | N | Y | Y | 80% |
   | claude-mem | Y | N | N | N | N | 20% |
   | playwright | Y | Y | Y | Y | Y | 100% |
   | filesystem (MCP) | Y | Y | Y | Y | Y | 100% |
   ```

4. **Identify standardization opportunities**

   ```
   ## Recommendations

   ### Adopt Team-Wide (80%+ already use)
   - oh-my-claudecode — all 5 members
   - playwright — all 5 members
   - everything-claude-code — 4/5 members (Eve should install)

   ### Remove Team-Wide (flagged as redundant by majority)
   - filesystem MCP — all 5 have it, all 5 don't need it (native tools)
   - memory MCP — 3/5 have it alongside claude-mem

   ### Inconsistencies
   - Bob has vercel-plugin 0.22.0, team standard is 0.24.0
   - Carol missing vercel-plugin entirely
   - Only Alice has claude-mem — team should decide: adopt or skip

   ### Token Budget Comparison
   | Member | Est. Tokens | vs. Average |
   |--------|-------------|-------------|
   | Alice | 42,000 | +15% above avg |
   | Bob | 35,000 | -4% |
   | Carol | 28,000 | -23% (fewest plugins) |
   | Dave | 38,000 | +4% |
   | Eve | 40,000 | +10% |
   | **Average** | **36,600** | — |
   ```

5. **Generate recommended baseline**

   Based on the analysis, suggest a standard plugin set:

   ```
   ## Recommended Team Baseline

   ### Required Plugins
   - oh-my-claudecode@4.9.1
   - everything-claude-code@1.8.0
   - vercel-plugin@0.24.0
   - playwright@latest
   - moltbloat@0.2.0

   ### Optional Plugins
   - claude-mem (for teams that want cross-session memory)
   - superpowers (for methodology enforcement)

   ### Remove Everywhere
   - filesystem MCP
   - memory MCP
   - sequential-thinking MCP
   - ralph-loop plugin

   ### Standard Rules
   - common/ (required)
   - typescript/ (if using TS)
   - python/ (if using Python)

   To generate an install script for new members:
   Save this as `team-setup.sh` in your config repo.
   ```

6. **Done**

</Steps>
