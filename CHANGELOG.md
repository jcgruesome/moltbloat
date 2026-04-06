# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-04-04

### Added
- **Dry-run mode** for `/moltbloat:clean --dry-run` — preview cleanup without making changes
- **`/moltbloat:doctor`** — Self-diagnostic tool for installation health and dependency checking
- **`snapshot trends` subcommand** — Historical trend analysis via `/moltbloat:snapshot trends`
- **Config file support** (`~/.moltbloat/config.json`) — Customizable thresholds, cost rates, and defaults
- **Validation script** (`scripts/validate.sh`) — CI-friendly validation of plugin structure

### Changed
- **MERGED: `trends` → `snapshot`** — Trend analysis now a subcommand of snapshot (removes 1 skill)
- **MERGED: `compat` → `audit`** — Compatibility checking now part of full audit (removes 1 skill)
- **REMOVED: `config` skill** — Users edit `~/.moltbloat/config.json` directly (removes 1 skill)
- Updated `check-snapshot-age.py` to use configurable threshold from config
- Skills now load thresholds from config instead of hardcoded values
- Fixed step numbering in `skills/usage/SKILL.md`
- **Reduced skill count: 15 → 12** (20% reduction)

### Documentation
- Updated README.md with new commands and CI badge
- Updated CLAUDE.md with command reference
- Added this CHANGELOG.md
- Added CONTRIBUTING.md with bloat-prevention guidelines
- Added GitHub Actions CI workflow (`.github/workflows/ci.yml`)
- Added anti-bloat design principle to CLAUDE.md

## [0.4.0] - 2026-04-03

### Added
- Initial release with 11 core skills
- Full ecosystem audit with health scoring (0-100)
- Token budget analysis with dollar cost estimates
- Interactive cleanup with confirmation
- Plugin dependency graph and blast radius analysis
- Compatibility checking (hook/skill/MCP collisions)
- Usage tracking via PostToolUse hook
- Profile management (lean/full/frontend/backend/custom)
- Snapshot baseline management with drift detection
- Team report aggregation
- Changelog diff against baselines

### Features
- Silent usage tracking (<50ms, 2s timeout)
- Real dollar cost calculations (Opus/Sonnet/Haiku rates)
- Context pressure warnings at 3% and 5% thresholds
- Automatic data compaction for usage logs >5,000 lines
- Read-only by default (only clean/profile modify state)

## Future Considerations

Features being evaluated for potential inclusion:

- **Export to JSON** — Machine-readable audit output for CI integration
- **Scheduled snapshot reminders** — Weekly/monthly instead of just 30-day
- **Plugin ignore list** — Exclude specific plugins from audit findings
- **Backup/restore** — Full ecosystem backup and restore

These will only be added if they don't increase complexity disproportionately to their value.
