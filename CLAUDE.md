# moltbloat

Claude Code ecosystem auditor plugin. Scans ~/.claude/ for bloat, redundancy, stale configs, and token waste. Tracks what you actually use, manages profiles, and shows real dollar costs.

## Skills

Run `/moltbloat:help` for the full command reference.

### Core
- `/moltbloat:help` — Show all available commands
- `/moltbloat:audit` — Full ecosystem scan with severity-rated findings, health score (0-100), compatibility checking, and usage-based recommendations
- `/moltbloat:audit --json` — Export audit results as JSON for CI integration
- `/moltbloat:token-budget` — Context window cost analysis with dollar estimates (Opus/Sonnet/Haiku)
- `/moltbloat:clean` — Interactive cleanup with confirmation before each action
- `/moltbloat:clean --dry-run` — Preview cleanup actions without making changes
- `/moltbloat:doctor` — Self-diagnostic for installation health and dependencies

### Intelligence
- `/moltbloat:changelog` — Diff current ecosystem against your last snapshot to see what changed
- `/moltbloat:depends` — Dependency graph showing what each plugin provides and blast radius of removal
- `/moltbloat:why <plugin>` — Quick lookup: what does this plugin give me, overlaps, token cost, keep/remove verdict
- `/moltbloat:usage` — What you actually use vs what's installed (requires tracking data)

### Management
- `/moltbloat:profile` — Switch between ecosystem configs (lean/full/frontend/backend/custom)
- `/moltbloat:profile suggest` — Intelligent profile creation based on usage + audit data
- `/moltbloat:snapshot` — Save ecosystem baseline, detect drift on future runs
- `/moltbloat:snapshot --export <path>` — Export snapshot JSON to file
- `/moltbloat:team-report` — Aggregate findings across team members for standardization

## Hooks

- **PostToolUse**: Silently tracks tool/skill/agent/MCP invocations to `~/.moltbloat/usage.jsonl`
- **Stop**: Reminds if ecosystem snapshot is >30 days old

## Data Files

- `~/.moltbloat/usage.jsonl` — Usage tracking data (created automatically by PostToolUse hook)
- `~/.moltbloat/usage.jsonl.bak` — Backup created before usage compaction
- `~/.moltbloat/baseline.json` — Ecosystem snapshot (created by `/moltbloat:snapshot`)
- `~/.moltbloat/history.log` — One-line snapshot summaries over time (appended by `/moltbloat:snapshot`)
- `~/.moltbloat/profiles/*.json` — Saved profiles (created by `/moltbloat:profile`)
- `~/.moltbloat/config.json` — Configuration file with thresholds and defaults (edit directly)

## Design Principles

- Read-only by default. Only `/moltbloat:clean` and `/moltbloat:profile apply` modify state.
- All checks are dynamic and structural — no hardcoded plugin names or curated opinion lists.
- Reports are actionable — every finding has a specific fix action.
- Usage tracking is silent and lightweight (typically <50ms; hard timeout of 2s).
- Dollar costs make token waste tangible.
- Configurable thresholds — edit `~/.moltbloat/config.json` to customize.
- Merged functionality over many small skills — 12 focused skills instead of 15 scattered ones.
