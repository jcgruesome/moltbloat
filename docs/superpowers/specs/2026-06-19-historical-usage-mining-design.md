# Historical Usage Mining — Design

**Date:** 2026-06-19
**Status:** Approved
**Affects:** `skills/usage/SKILL.md`, new `scripts/parse-history.py`, `scripts/init-config.py` (config schema), `scripts/validate.sh`

## Problem

moltbloat's `usage` skill identifies unused skills/agents/MCPs/plugins, but it only
reads moltbloat's *own* PostToolUse hook data (`~/.moltbloat/usage.jsonl`). That data
only accumulates *after* moltbloat is installed and needs weeks before it is meaningful.
New users get "come back in a few days" instead of answers.

Claude Code already records every session as a transcript under
`~/.claude/projects/**/*.jsonl`. Each `assistant` line carries `tool_use` blocks and a
per-line ISO-8601 `timestamp`. This is a rich, retroactive record of real tool, MCP,
skill, and subagent usage — available immediately, no waiting.

## Goal

Make `/moltbloat:usage` mine native Claude Code transcripts as its **primary** data
source to identify bloat (unused MCPs, plugins, skills, agents) immediately, with
recency-aware recommendations and exact disable commands. Hook data becomes supplemental
corroboration.

## Decisions (locked during brainstorming)

1. **Placement:** Extend the existing `usage` skill (not a new skill). Aligns with
   moltbloat's "merged functionality over many small skills" principle. Single entry
   point: `/moltbloat:usage`.
2. **Action depth:** Report + suggest exact disable/remove commands. Read-only; never
   execute. Removal stays with `/moltbloat:clean`.
3. **Staleness model:** Tiered by recency — **NEVER** (absent from history) /
   **STALE** (`last_used` older than `stale_days`, default 30) / **ACTIVE** (used within
   the window). `stale_days` configurable via `config.json`.
4. **Scope:** Global aggregate across all projects' transcripts (no per-project
   breakdown).

## Components

### 1. `scripts/parse-history.py` (new)

Pure, dependency-free Python 3. Responsibilities:

- Recursively walk `~/.claude/projects/**/*.jsonl`, streaming line by line.
- For each `assistant` line, extract every `tool_use` content block.
- Categorize each invocation:
  - `mcp__<plugin>_<server>__<tool>` or `mcp__<server>__<tool>` → **mcp**, with
    normalized `server` and (when present) owning `plugin`.
  - `Skill` → **skill**, keyed by `input.skill`.
  - `Task` / `Agent` → **agent**, keyed by `input.subagent_type`.
  - everything else → **tool**, keyed by tool name.
- Per item, accumulate: `count`, `first_used`, `last_used` (max line `timestamp`),
  `sessions` (distinct transcript files).
- Emit one JSON object to stdout:
  ```json
  {
    "scanned": {"files": N, "lines": N, "tool_uses": N},
    "generated_at": "<UTC ISO>",
    "since_days": <int|null>,
    "items": {
      "tool":  {"Bash": {"count": 8384, "last_used": "...", "first_used": "...", "sessions": 312}, ...},
      "mcp":   {"plugin_figma_figma": {"count": 172, "plugin": "figma", ...}, ...},
      "skill": {"superpowers:writing-plans": {...}, ...},
      "agent": {"general-purpose": {...}, ...}
    }
  }
  ```
- Flags: `--since <days>` (skip lines older than N days, by `timestamp`), `--json`
  (default and only output form).
- **Fail fast** with a clear message and non-zero exit if `~/.claude/projects` is absent.
- Robust to malformed lines: skip unparseable lines; a line without `tool_use` is cheaply
  skipped via a substring guard before JSON parse.

### 2. `skills/usage/SKILL.md` (extended)

New early step, before the existing hook-data parse:

- Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parse-history.py"` and capture the JSON.
- Read `thresholds.stale_days` from config (default 30).
- Cross-reference parser `items` against the installed inventory (existing step 4 logic).
  This discards parser noise: any historical name that is not a currently-installed
  component is ignored.
- **Tier each installed item:**
  - **NEVER** — not present in parser output at all → strong remove candidate.
  - **STALE** — present, but `last_used` older than `stale_days` → review candidate.
  - **ACTIVE** — `last_used` within `stale_days` → keep.
- Merge hook data (`usage.jsonl`) where present: corroborates counts and fills any gaps;
  labeled as supplemental, never overrides transcript truth.
- Report additions:
  - Tracking period now derives from transcript `first_used`/`last_used` span.
  - A **Recency** view: per component, tier + last-used date + total count.
  - "What you NEVER use" becomes retroactive and immediate.
- Recommendations print exact disable commands (see mapping below), then the existing
  pointer to `/moltbloat:clean`.

Hook-data-only fallback: if `~/.claude/projects` is missing/empty, the skill falls back
to the existing hook-data flow unchanged.

### 3. Config

Add `thresholds.stale_days` (default 30) to the config schema in
`scripts/init-config.py`. Read via the existing `init-config.py --get` path.

## Recommendation → disable command mapping (report-only)

| Unused item | Suggested action printed |
|-------------|--------------------------|
| MCP server (plugin-owned) | `claude plugin disable <plugin>` |
| MCP server (claude.ai connector) | Note: disconnect via `/mcp` or connector settings |
| Plugin (no skills/agents/MCPs ever used) | `claude plugin disable <plugin>` |
| Agent | Print agent file path (e.g. `~/.claude/agents/<name>.md`) |
| Skill | Note owning plugin; skills are not individually disablable |

The skill is honest about granularity and never executes these commands.

## Data flow

```
~/.claude/projects/**/*.jsonl
        │  (parse-history.py: stream, categorize, timestamp)
        ▼
JSON aggregate {items: counts + first/last_used + sessions}
        │  (usage skill: merge hook data, cross-ref installed inventory)
        ▼
Tier classification (NEVER / STALE / ACTIVE per stale_days)
        ▼
Report + exact disable commands  →  pointer to /moltbloat:clean
```

## Error handling & edge cases

- Missing `~/.claude/projects` → parser fails fast; skill falls back to hook data.
- Malformed/empty transcript lines → skipped silently.
- Name noise (`?`, legacy casing, bare tool names mislabeled as skills) → filtered by
  cross-referencing the installed inventory.
- MCP normalization covers `plugin_<plugin>_<server>`, `claude_ai_<server>`, and bare
  `<server>` forms.
- ~1,681 files → streaming parse, ~6–7s observed; `--since` bounds the scan.
- All timestamps are UTC ISO-8601; recency age computed in UTC.

## Testing

`scripts/test-parse-history.py` (new): builds a small in-memory/temp fixture transcript
covering each category (tool, mcp with/without plugin, skill, agent), a malformed line,
and two timestamps, then asserts:

- correct per-category counts and keys,
- `last_used` reflects the max timestamp,
- `--since` excludes older lines,
- malformed lines are skipped without crashing.

Wired into `scripts/validate.sh` so CI runs it.

## Out of scope (YAGNI)

- Incremental caching of parse results (re-scan each run).
- Removing moltbloat's own tracking hook (kept as supplemental).
- Per-project usage breakdown.
