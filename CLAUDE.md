# moltbloat

Claude Code ecosystem auditor plugin. Scans ~/.claude/ for bloat, redundancy, stale configs, and token waste. Tracks what you actually use, manages profiles, and shows real dollar costs.

## Skills

### Core
- `/moltbloat:audit` — Full ecosystem scan with severity-rated findings and health score (0-100)
- `/moltbloat:token-budget` — Context window cost analysis with dollar estimates (Opus/Sonnet/Haiku)
- `/moltbloat:clean` — Interactive cleanup with confirmation before each action

### Intelligence
- `/moltbloat:changelog` — Release-aware deprecation checks against `data/superseded.json`
- `/moltbloat:depends` — Dependency graph showing what each plugin provides and blast radius of removal
- `/moltbloat:why <plugin>` — Quick lookup: what does this plugin give me, overlaps, token cost, keep/remove verdict
- `/moltbloat:compat` — Detect plugin conflicts: hook collisions, skill shadowing, MCP tool overlaps
- `/moltbloat:usage` — What you actually use vs what's installed (requires tracking data)

### Management
- `/moltbloat:profile` — Switch between ecosystem configs (lean/full/frontend/backend/custom)
- `/moltbloat:snapshot` — Save ecosystem baseline, detect drift on future runs
- `/moltbloat:team-report` — Aggregate findings across team members for standardization

## Hooks

- **PostToolUse**: Silently tracks tool/skill/agent/MCP invocations to `~/.moltbloat/usage.jsonl`
- **Stop**: Reminds if ecosystem snapshot is >30 days old

## Data Files

- `data/superseded.json` — Curated rules mapping plugins/MCPs to native Claude Code replacements
- `~/.moltbloat/usage.jsonl` — Usage tracking data (created automatically)
- `~/.moltbloat/baseline.json` — Ecosystem snapshot (created by `/moltbloat:snapshot`)
- `~/.moltbloat/profiles/*.json` — Saved profiles (created by `/moltbloat:profile`)

## Design Principles

- Read-only by default. Only `/moltbloat:clean` and `/moltbloat:profile apply` modify state.
- Deterministic checks with concrete rules, not vague heuristics.
- Reports are actionable — every finding has a specific fix action.
- Usage tracking is silent and lightweight (<50ms per tool call).
- Dollar costs make token waste tangible.
