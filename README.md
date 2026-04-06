<div align="center">

```
    ███╗   ███╗ ██████╗ ██╗     ████████╗██████╗ ██╗      ██████╗  █████╗ ████████╗
    ████╗ ████║██╔═══██╗██║     ╚══██╔══╝██╔══██╗██║     ██╔═══██╗██╔══██╗╚══██╔══╝
    ██╔████╔██║██║   ██║██║        ██║   ██████╔╝██║     ██║   ██║███████║   ██║   
    ██║╚██╔╝██║██║   ██║██║        ██║   ██╔══██╗██║     ██║   ██║██╔══██║   ██║   
    ██║ ╚═╝ ██║╚██████╔╝███████╗   ██║   ██████╔╝███████╗╚██████╔╝██║  ██║   ██║   
    ╚═╝     ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   
```

**Audit your Claude Code ecosystem for bloat, redundancy, and token waste**

[![CI](https://github.com/jcgruesome/moltbloat/actions/workflows/ci.yml/badge.svg)](https://github.com/jcgruesome/moltbloat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-0.6.0-blue.svg)](https://github.com/jcgruesome/moltbloat/releases)

</div>

A Claude Code plugin that audits your ecosystem for bloat, redundancy, and token waste — with usage tracking, cost analysis, and ecosystem profiles.

## Install

```bash
# From GitHub marketplace
claude plugin marketplace add https://github.com/jcgruesome/moltbloat
claude plugin install moltbloat

# From local path
claude plugin marketplace add /path/to/moltbloat
claude plugin install moltbloat
```

## Usage

### Core — audit, understand costs, clean up
```
/moltbloat:help                   # Show all available commands
/moltbloat:audit                  # Full scan with health score (0-100), includes compatibility
/moltbloat:audit --json           # Export audit as JSON for CI integration
/moltbloat:audit --export <path>  # Save audit results to file
/moltbloat:token-budget           # Context cost breakdown + dollar estimates
/moltbloat:clean                  # Interactive cleanup with confirmation
/moltbloat:clean --dry-run        # Preview cleanup without making changes
/moltbloat:doctor                 # Self-diagnostic and health check
```

### Intelligence — understand your ecosystem
```
/moltbloat:changelog      # Diff ecosystem against last snapshot
/moltbloat:depends        # Dependency graph + blast radius
/moltbloat:why <plugin>   # Quick "should I keep this?" card
/moltbloat:usage          # What you actually use vs what's installed
```

### Management — control your ecosystem
```
/moltbloat:profile list            # See available profiles
/moltbloat:profile suggest         # Intelligent optimization based on usage + audit
/moltbloat:profile apply lean      # Switch to minimal config
/moltbloat:profile auto            # Auto-generate profile from usage data
/moltbloat:profile export <name>   # Share a profile as portable JSON
/moltbloat:profile import <path>   # Import a shared profile
/moltbloat:snapshot                # Save baseline, detect drift
/moltbloat:snapshot trends         # Show historical trends
/moltbloat:snapshot --export       # Export snapshot JSON
/moltbloat:team-report             # Aggregate findings across team
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
Finds plugin conflicts before they cause mysterious behavior: hook collisions, skill name shadowing, duplicate MCP tools. Smart duplicate detection identifies semantic overlaps (e.g., two Vercel deployment plugins) even with different names.

### Fully dynamic
All checks are structural — no hardcoded plugin names or curated opinion lists. The audit detects redundancy by analyzing what's actually installed and where things overlap, not by maintaining a database of "X replaces Y." The ecosystem evolves fast; moltbloat keeps up automatically.

### Usage-aware recommendations
Cross-references audit findings with actual usage data. A plugin with zero usage that duplicates another plugin's functionality gets flagged as high priority for removal. Usage tracking is silent and automatic.

### Smart cleanup
The `profile suggest` command analyzes your ecosystem + usage + audit findings to recommend an optimized profile. One command can reduce your token overhead by 30-50%.

### Configuration
Customize thresholds, costs, and defaults in `~/.moltbloat/config.json`:
- Token warning/critical thresholds
- Auto-compact usage data
- Ignored findings (false positives)
- Cost rates for new models

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
- **Semantic duplicates**: plugins with similar functionality (e.g., two Vercel plugins)
- **Usage correlation**: zero-usage plugins flagged for priority removal

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
