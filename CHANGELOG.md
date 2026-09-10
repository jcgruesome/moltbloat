# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.11.0] - 2026-09-10

### Added
- **`scripts/local-skills-scan.py`** — Claude Code now auto-loads skills from
  `.claude/skills/` directly (user-level `~/.claude/skills/` and nested
  per-project dirs), no marketplace or plugin install required. The audit's
  Check 1 (skill name collisions) previously only inventoried plugin skills
  and `~/.claude/commands/`, so a local `.claude/skills/` entry shadowing a
  plugin skill, or two local skill dirs sharing a name, went undetected.
  `/moltbloat:audit` now feeds this source into Check 1. Includes
  `scripts/test-local-skills-scan.py`, wired into `scripts/validate.sh`.

## [0.10.0] - 2026-09-10

### Added
- **CLAUDE.md / SKILL.md staleness and bloat check** — new Check 14 in
  `/moltbloat:audit` (`scripts/claude-md-staleness.py`). Flags references to
  Claude Code capabilities since renamed/removed/superseded (e.g.
  `/reload-plugins`, `keybindingFlavor`, `defaultMode: "bypassPermissions"`)
  via a small, dated snapshot table (`KNOWN_DEPRECATIONS`, 2026-09-10) built
  from docs.claude.com/code.claude.com research — documented as a snapshot
  needing periodic manual refresh, not a live feed. Also flags verbosity vs.
  Anthropic's ~200-line CLAUDE.md guidance, low header density, and
  `/plugin:skill` references matching no installed skill. Read-only, no
  duplication of the existing `phantom_refs`/skill-collision checks. New
  tests: `scripts/test-claude-md-staleness.py`.

### Changed
- CI's total-size gate raised again, 230KB/180KB (hard/soft) to 260KB/210KB —
  two feature PRs landed the same day and the prior bump had no headroom left
  for the second one after trimming both new files as far as reasonable.

## [0.9.0] - 2026-09-10

### Added
- **Claude.ai connector overlap detection** — new audit Check 13 (standard and
  `--deep`) finds overlap between org-managed claude.ai connectors
  (`mcp__claude_ai_<Service>__*`, invisible to `settings.json`/`.claude.json`) and
  locally-installed plugins/MCPs, by mining the same session-transcript source
  `/moltbloat:usage` reads and matching tool-name suffixes structurally. New
  `scripts/connector-overlap.py` (with tests), a `claude_ai_connectors` recon fact
  in `deep-recon.py`, and two new config thresholds.

### Changed
- CI's total-size gate raised from 200KB/150KB (hard/soft) to 230KB/180KB — the
  repo was already at 196KB before this feature, leaving no headroom for it.

## [0.8.2] - 2026-07-10

### Fixed
- **Every Stop hook invocation failed with "Hook script appears to be missing"** —
  `hooks/hooks.json` wrapped `${CLAUDE_PLUGIN_ROOT}` in single quotes, which in bash
  disables variable expansion entirely. The env var was passed to `python3`/`bash` as
  a literal, unexpanded string, so `check-snapshot-age.py` and `track-usage.sh` could
  never be found — this had been broken since the hook was introduced in v0.3.0.
  Switched to double quotes so bash actually expands the path.

## [0.8.1] - 2026-07-10

### Fixed
- **Usage tracker silently logged every invocation as `"unknown"`** — `track-usage.sh`
  read tool name/input from env vars (`CLAUDE_TOOL_NAME`/`CLAUDE_TOOL_INPUT`) that
  Claude Code never sets; the PostToolUse hook payload arrives as JSON on stdin.
  Rewrote the script to parse stdin directly, with atomic file-locked writes and
  errors routed to `~/.moltbloat/errors.log` instead of failing silently. This had
  been degrading `/moltbloat:usage` data since the hook was introduced.

## [0.8.0] - 2026-07-10

### Added
- **`/moltbloat:audit --deep`** — multi-agent forensic audit: 7 scoped auditors,
  adversarial verification of every high-severity finding, ideation lenses, and a
  polished shareable HTML report with a token-waste ledger and phased cleanup plan.
  Flags: `--thorough`, `--no-ideas`, `--yes`. New support files: `scripts/deep-recon.py`
  (deterministic read-only ground truth), `scripts/deep-audit-workflow.js` (canonical
  orchestration, degrades gracefully without Workflow/subagents), and
  `skills/audit/{deep-audit.md,report-template.html}`.

### Removed
- Historical design spec from `docs/superpowers/specs/` (recoverable from git history).

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

## [0.7.1] - 2026-06-19

### Fixed
- **No more false-positive disable suggestions in `/moltbloat:usage`.** Plugins that provide value through surfaces the miner can't see — LSP providers (`*-lsp`), statuslines, hooks-only, and command-only plugins — were wrongly flagged as "never used" and recommended for disabling. The skill now computes an **observability** check: a plugin is judged from history only if it has a measurable surface (skill/agent/MCP) OR has any history attributed to it. Unobservable plugins are listed under a new "Not Observable From History (review manually)" section and never appear in disable suggestions.
- Slash commands that *are* logged via the `Skill` tool (e.g. `commit-commands:clean_gone`) are now correctly tiered by recency instead of being misclassified.

## [0.7.0] - 2026-06-19

### Added
- **Retroactive usage mining** — `/moltbloat:usage` now mines Claude Code's native session transcripts (`~/.claude/projects/**/*.jsonl`) as its primary data source, so it works immediately on the first run instead of waiting weeks for the hook log to accumulate.
- **`scripts/parse-history.py`** — streaming transcript miner that aggregates real tool, MCP server, skill, and subagent usage with per-item `count`, `first_used`, `last_used`, and `sessions`. Flags: `--since <days>`, `--json`. Fails fast if `~/.claude/projects` is missing.
- **Recency tiers** — every installed component is classified **ACTIVE** / **STALE** / **NEVER** against a configurable window (`thresholds.stale_days`, default 30), turning "unused" into a defensible, recency-aware verdict.
- **Disable suggestions** — never/stale MCPs, plugins, and agents are reported with the exact disable/disconnect command (read-only; moltbloat never runs them), with granularity safeguards so a still-used component is never recommended for removal.
- **`scripts/test-parse-history.py`** — fixture-based unit tests for the miner, wired into `scripts/validate.sh`.

### Changed
- **Config schema v1.2** — added `thresholds.stale_days` (default 30).
- moltbloat's own PostToolUse hook log (`usage.jsonl`) is now supplemental corroboration rather than the sole source.

## [0.6.1] - 2026-06-18

### Changed
- **RENAMED: `/moltbloat:doctor` → `/moltbloat:diagnose`** — The `doctor` skill collided with Claude Code's built-in `/doctor` command. Its generic "doctor"/"diagnose" trigger words caused the plugin's self-diagnostic to hijack the built-in diagnostic. The skill is renamed and its triggers scoped to moltbloat-specific phrases only.

## [0.6.0] - TBD

### Added
- **Export to JSON** — `audit --json`, `audit --export <path>`, `snapshot --export <path>`
- **Auto-compact** — Usage data automatically compacts when threshold exceeded (configurable)
- **Ignored findings** — Config option to dismiss false positives (`ignored_findings` array)
- **Smart duplicate detection** — Semantic analysis of plugin overlap beyond exact name matches
- **Usage-based recommendations** — Cross-references audit findings with actual usage data
- **`/moltbloat:profile suggest`** — Intelligent profile creation combining usage + audit data

### Changed
- **Config schema v1.1** — Added `ignored_findings`, `export` settings
- **Usage skill** — Supports automatic compaction (config: `defaults.auto_compact`)
- **Audit skill** — Enhanced with usage data cross-reference and smarter duplicate detection
- **Profile skill** — New `suggest` subcommand for one-click optimization

## Future Considerations

Features being evaluated for potential inclusion:

- **Scheduled snapshot reminders** — Weekly/monthly instead of just 30-day
- **Plugin recommendation** — "Teams working on similar projects also use: X, Y"
- **Budget alerts** — Warn when token overhead exceeds a threshold
- **Backup/restore** — Full ecosystem backup and restore

These will only be added if they don't increase complexity disproportionately to their value.
