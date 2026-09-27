# Instruction audit, measured context ledger, and delegation cost

Date: 2026-09-25
Status: draft, awaiting review
Lane: `feat/instruction-audit`

## Goal

Make moltbloat catch the waste that newer models (Opus 5.5 and later) expose:
instructions written for older models, duplicated or drifted instruction files,
context injected by plugins that no check measures today, and subagent
delegation that costs more than it saves. Findings stay report-only in
`/moltbloat:audit`, `/moltbloat:token-budget`, and `/moltbloat:usage`. Rewrites
are proposed as diffs and applied only by `/moltbloat:clean` after per-change
confirmation.

## Grounding (sources)

- Newer models are more responsive to system prompts; emphatic wording written
  for older models ("CRITICAL: You MUST") now over-triggers. Use normal
  phrasing. <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices.md>
- Opus 5.5 defaults to `medium` effort. <https://platform.claude.com/docs/en/about-claude/models/choosing-a-model.md>
- Opus 5 guidance warns against overusing subagent delegation.
  <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5.md>
- CLAUDE.md: target under 200 lines; `@imports` up to 4 hops; `.claude/rules/`
  with `paths:` frontmatter loads conditionally; nested CLAUDE.md loads lazily;
  `AGENTS.md` is read natively. <https://code.claude.com/docs/en/memory.md>
- `TaskOutput` tool removed (Claude Code 2.1.274 to 2.1.282, Sep 2026).
  <https://code.claude.com/docs/en/changelog.md>

## Success criteria

1. On the author's machine, audit reports: the duplicated and drifted
   "Session wrap" sections and the `imported-from:` residue in
   `~/.claude/CLAUDE.md`; the SessionStart hook context per plugin; the skill
   listing dropping descriptions for the skills past its size budget; `executor`, `code-reviewer`, `verifier`
   having no `model:` pin.
2. `token-budget` reports measured per-session context by source, taken from
   transcripts, with estimates used only where no transcript data exists and
   labeled as such.
3. `clean` offers a unified diff for each instruction rewrite and a one-line
   frontmatter pin for each unpinned agent; nothing is written without a yes.
4. No hardcoded plugin, skill, server, or agent names in any check.
5. Every new script has a `test-*.py` suite and passes `scripts/validate.sh`.

## Components

Each unit is one script with one job, a `--json` mode, and a test file,
matching the existing `scripts/` pattern.

### 1. `scripts/context-ledger.py` (new): measured per-session context

Scans main-session transcripts newest first (excludes `subagents/`) and
extracts these attachment records, which Claude Code already writes. Not every
session records every type (observed: in the 10 newest sessions, `instructions`
and `hook_additional_context` appeared in 4, `skill_listing` in 10). So
sampling is per type: keep scanning until each type has
`context_ledger_samples` sessions (default 10) or `context_ledger_max_sessions`
(default 100) have been scanned, whichever comes first. Each row reports its
own sample count.

Only interactive sessions count by default: sessions whose `entrypoint` starts
with `sdk-` (automated runs, many spawned by plugins; 94 of the 104 newest
transcripts on the author's machine) are skipped and their counts reported,
with `--include-sdk` to measure them. The `*_delta` records arrive several
times per session (MCP servers connect late, entries are removed and re-added),
so they are measured as the union of added entries keyed by name, not the
first record.

| Attachment `type` | Field used | Ledger row |
|---|---|---|
| `instructions` | `files[].path`, `.type`, `.content` length | one row per loaded instruction file |
| `skill_listing` | `content` length, `skillCount` | Skill listing |
| `deferred_tools_delta` | `addedNames` grouped by MCP server prefix | Deferred tool names, per server |
| `mcp_instructions_delta` | `addedBlocks` length per `addedNames` entry | MCP server instructions, per server |
| `agent_listing_delta` | `addedLines` length | Agent listing |
| `hook_success` with `hookEvent: SessionStart` | `stdout` parsed as JSON, then `hookSpecificOutput.additionalContext` length; `command` | Hook context, per hook command |
| `hook_additional_context` | `content` length | Hook context total |

Hook totals are never summed across both types. `hook_additional_context` is
the merged payload the model received, so it is the session total when
present; the per-command `hook_success` rows only break that total down by
source. Without it, the total is the sum of the per-command rows. A
`hook_success` whose `stdout` is not JSON, or has no
`hookSpecificOutput.additionalContext`, contributes 0 context (plain stdout
from SessionStart is not injected as additionalContext) and is counted in an
"unparsed hook output" tally so the assumption stays visible.

Output: per source, median chars and tokens per session (using
`estimates.tokens_per_byte`), plus the file paths that were actually loaded.
The median is over sessions where that type was present; sessions without it
are excluded, not counted as 0.

Hook attribution: transcripts record `command` unexpanded (literal
`${CLAUDE_PLUGIN_ROOT}/...`), so match it verbatim against the command strings
in every installed plugin's `hooks/hooks.json`, then `settings.json` hooks.
Unmatched commands are reported as "unattributed hook", not guessed.

Skill listing overflow: when the listing hits its size budget, the remaining
skills appear as a bare `- name` line with no description (observed: 134
skills, 29,999 chars, the tail listed name-only). Claude cannot route to a
skill by intent without its description. Detect structurally: parse the
listing, and for each bare-name entry whose SKILL.md has a non-empty
`description`, record it as `skill_description_dropped`. Report the count and
names, plus the plugins contributing the most listing chars. The budget value
itself is undocumented; report the observed length, not a claimed limit.

Rows are grouped per project where the source is per-project (project
CLAUDE.md, rules); user-level sources are aggregated across all sessions.

These attachment shapes are undocumented internals. If none of the recent
transcripts contain any known attachment type, the script exits non-zero with
"transcript format not recognized; context ledger unavailable" rather than
falling back silently. Missing individual types are reported as "not present in
transcripts", never zero.

### 2. `scripts/instruction-files.py` (new): collect what loads and how

Enumerates instruction files for the current project and labels each with a
load mode:

- always: `~/.claude/CLAUDE.md`, project `CLAUDE.md` / `.claude/CLAUDE.md`,
  `CLAUDE.local.md`, `AGENTS.md`, ancestor-directory CLAUDE.md files, rules
  without `paths:`
- path-scoped: rules with `paths:` frontmatter
- lazy: nested CLAUDE.md below the project root
- imported: targets of `@path` references, resolved up to 4 hops, skipping code
  spans and fenced blocks, with the importing file recorded

Cross-checks against the ledger's `instructions` records when available, so
the report can say "declared vs actually loaded" (for example, AGENTS.md
present but never seen loaded).

Consumers: `instruction-lint.py`, `claude-md-staleness.py` (Check 14 takes
these files in addition to the SKILL.md paths it already collects), and
`token-budget` step 2a/2b. SKILL.md files are not instruction files and are
not listed here.

### 3. `scripts/instruction-lint.py` (new): quality checks and rewrite diffs

Input: the file list from component 2, plus hook `additionalContext` text from
component 1 (linted but never rewritten, since it belongs to a plugin).

Checks (all structural):

| id | Detects | Severity |
|---|---|---|
| `emphasis_density` | all-caps imperatives (`MUST`, `NEVER`, `ALWAYS`, `IMPORTANT`, `CRITICAL`, `REQUIRED`, `ABSOLUTELY`), XML-style shout tags (`<EXTREMELY_IMPORTANT>`), per 100 prose lines, excluding code fences and blockquotes | LOW above threshold, MEDIUM above 2x |
| `duplicate_section` | two sections (split on headers, normalized) with body similarity >= 0.95, within or across files | MEDIUM |
| `drifted_duplicate` | same normalized heading or body similarity 0.6 to 0.95; shows the differing lines | HIGH (two versions of one instruction is a conflict) |
| `import_residue` | `<!-- imported-from: ... -->` markers left by `claude import` | LOW |
| `instruction_byte_budget` | an always-loaded instruction file over `thresholds.instruction_byte_budget` bytes; reports the file's measured tokens from the context ledger when available | LOW above budget, MEDIUM above 2x |
| `placeholder_marker` | `TODO`, `FIXME`, `TBD`, `XXX`, or "not implemented" in instruction prose (code fences and inline code excluded): unfinished text that loads every session | LOW |

Sections under 5 body lines are not compared, to avoid pairing short
unrelated sections. Comparison is bounded: exact duplicates are found by
hashing normalized bodies; fuzzy similarity runs only on pairs that share a
normalized heading or at least 3 of their 10 most frequent content words.
Scope is component 2's instruction files only (not SKILL.md), which keeps the
input to tens of sections.

The caps word list is a list of English emphasis words, not of plugin names, so
it does not break the "no curated opinion lists" principle.

`--suggest-rewrite <file>` emits a unified diff that:

- removes `imported-from` marker comments
- removes a section only when an earlier section of the same file has the
  same heading path (parent headings included) and an identical subtree
  (body plus every child section)

Revised 2026-09-26 after review: emphasis softening and cross-file removal
were dropped from the rewrite. Softening by pattern deleted placeholders
like `<YOUR_API_TOKEN>`, broke `**IMPORTANT:**` bold markup, and changed
file paths; cross-file removal deleted a shared section from both files
when each was rewritten against the other. Both stay as findings for the
user to act on. File paths joined the preserve list.

Drifted duplicates are never auto-merged. The diff leaves both, and `clean`
asks which version to keep (or to keep both).

Rewrite safety (adapted from caveman-compress, MIT, which does the same job
for memory files):

- **Preserve list, verified after the rewrite:** every fenced code block,
  inline code span, URL, file path, and `@import` line must be byte-identical
  before and after. If any differs, the rewrite for that file is discarded
  and the original is left untouched; the finding stays report-only.
- **Prose files only:** the rewriter refuses anything that is not Markdown
  (no `.json`, `.py`, `.js`, frontmatter-only files).
- **Backups out of the tree:** `~/.moltbloat/backups/<timestamp>/` (already
  the plan), never beside the file, so Claude Code never loads a backup as a
  live instruction file.

The byte-budget and placeholder checks follow caveman's `skills/compile.mjs`,
which fails its build when a skill exceeds `prompt_byte_budget` or ships
placeholder markers. moltbloat applies the same idea to a user's
instruction files as findings, not build failures.

### 4. `claude-md-staleness.py`: refresh deprecations

Add `TaskOutput` to `KNOWN_DEPRECATIONS`, bump `SNAPSHOT_DATE`. Add component
2's instruction files to its input; keep its existing SKILL.md collection
unchanged (dropping it would regress Check 14's deprecated and unknown skill
reference findings on SKILL.md).

### 5. Delegation cost: `scripts/delegation-cost.py`

Revised 2026-09-27: a separate script rather than an extension of
`parse-history.py`, which counts `tool_use` lines in main sessions; pricing
subagent runs from their usage records is a different job. Findings from
real data that shaped it: about half of assistant usage lines repeat a
message id while streaming (each id is counted once, taking the largest value
per field); 24% of `meta.json` files lack `model` and some say `inherit`, so
runs are grouped by the transcript's `message.model`; `<synthetic>` messages
are skipped. Prices come from a per-model table added to config
(`costs.models`, from the Claude API pricing reference cached 2026-06-24)
because Opus 5.5 ($4/$20, cache reads $0.20) and Fable 5.1 (cache reads
$0.25) do not fit the flat input rate and 0.1x cache-read multiplier used
elsewhere; a model with no rate is reported as unpriced.


Subagent runs live in `<session>/subagents/agent-<id>.jsonl` with a sibling
`agent-<id>.meta.json` holding `agentType`, `model`, `description`,
`spawnDepth`. Add a `delegation` block to the aggregate:

- per `agentType` x `model`: run count, input/output/cache-write/cache-read
  tokens (from `message.usage`), dollar cost via `costs.*` and the cache
  multipliers already in config. Price from each message's `message.model`
  (full id, e.g. `claude-sonnet-5`); `meta.json` `model` is only an alias
  (`sonnet`) and is used for grouping, not pricing
- first-turn cache write per run (the fixed cost of a fresh context), reported
  as "spin-up cost"
- `mechanical_on_premium`: runs on the top two tiers whose tool calls were all
  read-only (Read/Grep/Glob/read-only Bash) and whose final output was short;
  reported as candidates, not verdicts
- Any saving shown for moving work to a cheaper model compares against the
  realistic alternative (the same runs priced on the suggested tier, using
  their measured tokens), never against zero. caveman's eval harness
  (`evals/README.md`) documents why comparing against no alternative
  inflated its own earlier numbers.

Agent inventory: every agent definition in `~/.claude/agents/`, project
`.claude/agents/`, and enabled plugins, with its `model:` value or "inherits".

Surfaces:

- `/moltbloat:usage`: new "Delegation cost" section (spend by agent type and
  model, spin-up cost, mechanical-on-premium candidates)
- `/moltbloat:audit`: new finding `unpinned_agent` (agent has no `model:` and
  has real spend), ranked by spend; LOW if no spend
- `/moltbloat:audit`: new finding `delegation_prose_conflict`: instruction
  prose naming a model tier for an agent type that contradicts that agent's
  `model:` frontmatter (MEDIUM). Lives here, not in the lint, because it needs
  the agent inventory

### 6. Skills wiring

- `audit`: new Check 15 "Instruction quality" (components 2 and 3), plus
  `unpinned_agent`, `delegation_prose_conflict`, and
  `skill_description_dropped` (MEDIUM; fix: disable unused skill-heavy
  plugins, informed by `/moltbloat:usage`) findings. Check 7 suggests adding
  `paths:` frontmatter to unused-language rules as the first fix, before
  removal.
- `token-budget`: replaces estimated CLAUDE.md, rules, and MCP rows with
  ledger-measured rows when available; adds Skill listing, Deferred tool names,
  MCP instructions, Agent listing, and Hook context rows. Estimates remain for
  sources with no transcript data and are labeled "est.".
- `clean`: new action types "Instruction rewrite" (shows diff, confirm per
  file; drifted duplicates prompt for keep A / keep B / keep both) and "Pin
  agent model" (shows the one-line frontmatter change, confirm per agent;
  suggested tier from observed runs, user picks). Back up each file to
  `~/.moltbloat/backups/<timestamp>/` before writing.
- `audit`: new finding `repeated_hook_context`: a SessionStart hook that
  injects the same content in every sampled session (MEDIUM when over 1,000
  chars). Suggested fix, for the plugin's author or a local override: show
  one-time content once, behind a marker file, as caveman's
  `src/hooks/caveman-activate.js` does for its setup nudge. Needs the ledger
  to record a content hash per hook command per session (a small addition
  to component 1).
- `help`, `README.md`, `CLAUDE.md`: document the new checks, and add
  `~/.moltbloat/backups/` to the CLAUDE.md "Data Files" list.

## Config additions (`init-config.py` defaults)

```
thresholds.instruction_emphasis_per_100_lines: 3
thresholds.duplicate_section_similarity: 0.95
thresholds.drifted_section_similarity: 0.6
thresholds.instruction_byte_budget: 25000
thresholds.context_ledger_samples: 10
thresholds.context_ledger_max_sessions: 100
```

`instruction_byte_budget` defaults to 25,000 bytes, the size Claude Code's
memory docs give as the load limit for auto memory; it is a starting
default, not a measured optimum.

## Error handling

- Missing input paths: fail fast, non-zero exit (existing convention).
- Unrecognized transcript format: fail fast with a clear message (component 1).
- Malformed `meta.json` or frontmatter: report the file as unparseable in the
  output; do not skip it silently.
- Well-formed `meta.json` missing `model` (observed in about 19% of sampled
  subagent runs): group the run under the model alias derived from its
  messages' `message.model`; if the transcript has no model either, group it
  as "model unknown" and exclude it from `mechanical_on_premium`. Costs still
  use `message.model` when present.
- `clean` write failures: stop the run at the failing file; backups already
  taken remain.

## Testing

Per script, a `scripts/test-<name>.py` with fixture files built in temp dirs
(existing pattern). Cases:

- ledger: each attachment type, missing types, per-type sampling stops at
  the sample or session cap, median excludes absent sessions, hook totals not
  double-counted when both hook types exist, non-JSON hook stdout,
  unrecognized format exit,
  hook attribution matched and unmatched, bare-name skill entries detected
  only when SKILL.md has a description
- staleness: SKILL.md findings unchanged after the input switch (regression
  test on an existing fixture)
- instruction-files: `@import` chains (4-hop limit, cycles, imports inside code
  fences ignored), `paths:` parsing, AGENTS.md detection
- lint: emphasis counting excludes code and quotes; duplicate vs drifted
  thresholds; rewrite diff applies cleanly with `patch` and is idempotent
- parse-history delegation: meta join, cost math against config, mechanical
  classification
- `validate.sh` passes.

## Delivery slices (one lane and PR each)

1. Context ledger + token-budget wiring (components 1, 6 token-budget part)
2. Instruction files + lint + audit Check 15 + deprecation refresh
   (components 2, 3, 4)
3. Delegation cost + `unpinned_agent` + `delegation_prose_conflict`
   (component 5)
4. Clean actions for rewrites and agent pins (component 6 clean part)

Slice order is by value: 1 exposes the biggest measured cost; 4 depends on 2
and 3.

## Out of scope

- Writing delegation policy into user files (the tool measures and points at
  frontmatter; it does not prescribe a routing rule).
- Rewriting plugin-owned content (hook output, plugin SKILL.md): reported with
  the owning plugin so the user can disable or raise upstream.
- Effort-level checks: config key names for effort pins are not yet confirmed
  in docs; revisit when they are.

## Self-review

**Risks**

- Transcript attachment formats are internal and can change in any release.
  Mitigated by fail-fast detection and fixture tests; still, a format change
  breaks slice 1 until updated.
- Emphasis lint can flag intentional emphasis (safety rules). It is LOW/MEDIUM
  and rewrites need confirmation, but noisy findings erode trust; the threshold
  is configurable.
- Section similarity can pair unrelated short sections. Require a minimum body
  length (5 lines) before comparing.
- Hook attribution by command text can fail for hooks defined in
  `settings.json` rather than plugins; those appear as "unattributed" with the
  source settings file if found.

**Gaps**

- Only the current project's instruction files are linted; other projects'
  AGENTS.md files need a per-project run (or `team-report`).
- The skill listing budget is undocumented; detection relies on the observed
  bare-name format, which could change.
- Linting only sees text; it cannot tell whether an emphasized rule is
  actually over-triggering. Pairing lint findings with usage data (e.g. a
  shouted "always use skill X" plus X's invocation rate) is a possible later
  signal, not in this spec.
- `mechanical_on_premium` is a heuristic; wording must present candidates, not
  conclusions.

**Elevation**

- Measured context replaces estimates, which no comparable auditor does; the
  existing `tokens_per_mcp_tool: 350` estimate overstates deferred MCP tools,
  and the ledger corrects it.
- "Declared vs actually loaded" instruction files catches silent misconfig
  (an import that never resolves, an AGENTS.md that never loads).
- Spin-up cost per subagent makes the delegation trade-off concrete in dollars
  rather than argued in prose.
