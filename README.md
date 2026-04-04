# moltbloat

A Claude Code plugin that audits your ecosystem for bloat, redundancy, and token waste — with usage tracking, cost analysis, and ecosystem profiles.

## Install

```bash
# From GitHub marketplace
claude plugin marketplace add <repo-url>
claude plugin install moltbloat

# From local path
claude plugin marketplace add /path/to/moltbloat
claude plugin install moltbloat
```

## Usage

### Core — audit, understand costs, clean up
```
/moltbloat:help           # Show all available commands
/moltbloat:audit          # Full scan with health score (0-100)
/moltbloat:token-budget   # Context cost breakdown + dollar estimates
/moltbloat:clean          # Interactive cleanup with confirmation
```

### Intelligence — understand your ecosystem
```
/moltbloat:changelog      # Diff ecosystem against last snapshot
/moltbloat:depends        # Dependency graph + blast radius
/moltbloat:why <plugin>   # Quick "should I keep this?" card
/moltbloat:compat         # Detect hook conflicts + skill shadowing
/moltbloat:usage          # What you actually use vs what's installed
```

### Management — control your ecosystem
```
/moltbloat:profile list       # See available profiles
/moltbloat:profile apply lean # Switch to minimal config
/moltbloat:profile auto       # Auto-generate profile from usage data
/moltbloat:snapshot           # Save baseline, detect drift
/moltbloat:team-report        # Aggregate findings across team
```

## What makes this different

### Usage tracking
A silent PostToolUse hook logs every skill, agent, and MCP invocation. After a few sessions, `/moltbloat:usage` tells you exactly what you use vs what's just consuming context. No more guessing.

### Ecosystem profiles
Switch between `lean` (2-3 plugins, ~5K tokens) and `full` (everything, ~40K+ tokens) with one command. Or create custom profiles for frontend, backend, or project-specific work.

### Real dollar costs
Token-budget shows the actual dollar cost of your ecosystem overhead:
- Per message at Opus/Sonnet/Haiku rates
- Per day (assuming 200 messages)
- Per month

### Compatibility detection
Finds plugin conflicts before they cause mysterious behavior: hook collisions, skill name shadowing, duplicate MCP tools.

### Fully dynamic
All checks are structural — no hardcoded plugin names or curated opinion lists. The audit detects redundancy by analyzing what's actually installed and where things overlap, not by maintaining a database of "X replaces Y." The ecosystem evolves fast; moltbloat keeps up automatically.

## What it checks

- **Plugins**: disabled, zero-skill, stale cache versions
- **MCP servers**: duplicates of native features or other plugins
- **Skills**: cross-plugin overlap and name collisions
- **Agents**: local vs plugin-provided duplicates
- **Rules**: language sets that don't match project languages
- **Hooks**: conflicts, injection load, context bloat
- **Stale configs**: orphaned sessions, old caches, dead project refs
- **Token cost**: how much context each component consumes, in dollars
- **Usage**: what's actually invoked vs just installed

## Health Score

The audit produces a 0-100 health score:
- **90-100**: Pristine — minimal bloat
- **70-89**: Healthy — some cleanup opportunities
- **50-69**: Bloated — significant redundancy
- **0-49**: Critical — major cleanup needed

## Team Usage

1. Each member installs moltbloat
2. Each runs `/moltbloat:snapshot` to export their state
3. Share snapshots in a shared directory or config repo
4. Run `/moltbloat:team-report` to aggregate and standardize
