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
   # Team Plugin Matrix (<N> members)

   | Plugin | <Member 1> | <Member 2> | ... | Coverage |
   |--------|------------|------------|-----|----------|
   <one row per plugin found across any member's snapshot>
   ```

4. **Identify standardization opportunities**

   ```
   ## Recommendations

   ### Adopt Team-Wide (80%+ already use)
   <list plugins with 80%+ coverage — suggest remaining members install>

   ### Flagged by Multiple Members
   <list any plugins/MCPs that appear in multiple members' audit findings>

   ### Inconsistencies
   <list version mismatches, plugins some members have and others don't>

   ### Token Budget Comparison
   | Member | Est. Tokens | vs. Average |
   |--------|-------------|-------------|
   <one row per member with their token estimate and delta from average>
   | **Average** | **<X>** | — |
   ```

5. **Generate recommended baseline**

   Based on the analysis, suggest a standard plugin set. All recommendations are derived from the team data — no hardcoded plugin lists:

   ```
   ## Recommended Team Baseline

   ### Required (100% team adoption)
   <list plugins installed by all team members>

   ### Recommended (80%+ adoption — stragglers should install)
   <list plugins used by most but not all>

   ### Optional (below 80% — team should decide)
   <list plugins with mixed adoption>

   ### Flagged by Audit (team members report redundancy)
   <list any plugins/MCPs that multiple members' audits flagged as issues>

   ### Standard Rules
   <list rule directories present across majority of members>

   To generate an install script for new members:
   Save this as `team-setup.sh` in your config repo.
   ```

6. **Done**

</Steps>
