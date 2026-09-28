---
name: token-budget
description: Analyze context window cost of installed plugins, rules, CLAUDE.md, hooks, and MCP tool definitions
level: 2
---

<Purpose>
Measure how much of your context window is consumed by the Claude Code ecosystem — plugins, rules, CLAUDE.md files, hook outputs, and MCP tool definitions. Identifies the biggest token consumers so you can make informed decisions about what to keep.
</Purpose>

<Use_When>
- User wants to know what's eating their context window
- User says "token budget", "context cost", "token waste", "context window"
- After installing new plugins and wanting to see the impact
- When hitting context limits during long sessions
</Use_When>

<Do_Not_Use_When>
- User wants a full ecosystem audit — use `/moltbloat:audit`
- User wants to remove things — use `/moltbloat:clean`
</Do_Not_Use_When>

**Paths:** `~/.claude` means the active Claude config dir (`$CLAUDE_CONFIG_DIR` if set); `~/.moltbloat` means moltbloat's data dir for it (`scripts/paths.py moltbloat-home`).

<Steps>

1. **Announce**

   Tell the user:
   > Analyzing context window cost of your Claude Code ecosystem...

2. **Load configuration**

   Get cost rates and estimation factors from config:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get costs
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get estimates
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.token_warning
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.context_ledger_samples
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init-config.py" --get thresholds.context_ledger_max_sessions
   ```

   Use these values for calculations:
   - Cost rates: `costs.models`, a per-model table (input, output, cache read per 1M tokens). The cost step below reads it through `cache-cost.py --model`.
   - Context window: `costs.context_windows` is a per-model map (fable_5_1, opus_5_5, sonnet_5: 1,000,000; haiku_4_5: 200,000). `costs.context_window_tokens` (default: 1,000,000) is the flat fallback shared by Opus 5.5, Sonnet 5, and Fable 5.1.
   - Token estimates: tokens_per_byte (default: 0.25), tokens_per_skill, tokens_per_mcp_tool, tokens_per_agent
   - Daily messages: messages_per_day (default: 200)

   **Which model's window to use**: if the user has stated which model they're on this session, use that model's entry from `context_windows`. Otherwise ask, or default to the shared 1,000,000-token window (Opus 5.5 / Sonnet 5 / Fable 5.1) unless the user has named Haiku, since Haiku 4.5 is the one model with a materially different (200,000-token) window. Never divide by 1,000,000 for a Haiku 4.5 user: it silently understates their real percentage by 5x.

3. **Measure each context source**

   For each category below, measure the byte size of all files that get injected into context. Use `wc -c` for accuracy. Estimate tokens using `tokens_per_byte` from config (default: 0.25, i.e., bytes / 4).

   Run all measurements in parallel.

   **2.0 Measured context ledger (run first)**

   Claude Code records what it injected at session start in the transcripts.
   Measure that directly, scoping the instruction-file rows to this project
   so a CLAUDE.md or rules file from a different project on the machine
   never gets added into this one's total:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/context-ledger.py" --json \
     --samples <context_ledger_samples> --max-sessions <context_ledger_max_sessions> \
     --tokens-per-byte <tokens_per_byte> \
     --project "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   ```

   - Exit 0: use `sources.*.median_tokens` for every source it reports
     (skill listing, deferred tool names, MCP server instructions, agent
     listing, SessionStart hook context, and each instruction file). These
     replace the estimates in 2a, 2d, 2e, 2f, and 2g for those sources.
     Any instruction file under a `rules/` directory that the ledger
     reports replaces the corresponding est. Rules row from 2b entirely;
     it is not added on top of the estimate.
   - If `format_errors` is non-empty: tell the user which records could not
     be parsed (quote each entry) and mark the affected rows "partial" in
     the budget table, since the ledger's numbers for those sources may
     undercount.
   - Sources in `missing`: fall back to the estimate for that source only,
     and mark its row "est.", except `hook_context` and `mcp_instructions`,
     which have no estimator in 2a-2g. For those two, when they're in
     `missing`, show "not present in transcripts" and exclude them from
     TOTAL entirely. Never show 0 or an invented number for them.
   - Any non-zero exit: tell the user the ledger is unavailable and quote
     stderr verbatim, then use estimates for every row marked est.

   The 2a to 2g measurements below still run: they supply rows the ledger
   does not cover (rules not seen loaded) and the fallbacks above.
   Per-plugin cost comes from the ledger's attribution (`by_server`,
   `skill_listing.by_owner`, `hook_context.by_owner`), shown under "Where
   the ledger points".

   **2a. CLAUDE.md files**
   These are always loaded into context:
   ```bash
   # Global
   wc -c "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/CLAUDE.md 2>/dev/null
   # Project-level (for current project)
   wc -c ./CLAUDE.md 2>/dev/null
   wc -c ./.claude/CLAUDE.md 2>/dev/null
   ```

   **2b. Rules**
   All `.md` files in `~/.claude/rules/` are loaded:
   ```bash
   find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/rules -name "*.md" -type f -exec cat {} + 2>/dev/null | wc -c
   ```
   Also measure per-directory to show breakdown:
   ```bash
   for dir in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/rules/*/; do
     name=$(basename "$dir")
     size=$(find "$dir" -name "*.md" -type f -exec cat {} + 2>/dev/null | wc -c)
     echo "$name: $size bytes"
   done
   ```

   **2c. Plugin CLAUDE.md and AGENTS.md: not counted**
   A plugin's own `CLAUDE.md` or `AGENTS.md` in `~/.claude/plugins/cache/`
   is not loaded into your session. The ledger's `instructions` records list every instruction
   file a session actually loaded, and plugin-cache files do not appear
   there. Do not add them to the budget. What a plugin does inject (skill
   listing entries, MCP tools and instructions, SessionStart hook output)
   is already measured per plugin by the ledger.

   **2d. MCP tool definitions**
   Each MCP server registers tools that consume context. Count the number of MCP tools visible in the current session by checking deferred tools:
   ```bash
   # Count MCP tool entries from plugin configs
   for mcp_file in $(find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache -name ".mcp.json" -type f 2>/dev/null); do
     plugin=$(echo "$mcp_file" | sed 's|.*/cache/[^/]*/\([^/]*\)/.*|\1|')
     echo "$plugin: $mcp_file"
   done
   ```
   Note: Each MCP tool definition is approximately 200-500 tokens for the name + description + parameter schema. Only used when the ledger reports `deferred_tools` missing. With deferred tools, only names are in context until a tool is loaded, so this estimate overstates cost; label it est.

   **2e. Skill metadata**
   Skills are listed in system reminders. Each skill listing is roughly one line (~100 chars = ~25 tokens):
   ```bash
   # Count total skills across all plugins
   total=0
   for plugin_dir in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/*/*/skills/*/; do
     total=$((total + 1))
   done 2>/dev/null
   echo "Total skills: $total"
   ```
   Estimate: `skill_count * 25` tokens for the skill listing in system reminders.

   **2f. Hook injection**
   Hooks inject `<system-reminder>` content. Measure hook definitions:
   ```bash
   find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" -name "hooks.json" -type f 2>/dev/null -exec wc -c {} +
   ```
   Note: Hook *output* varies per invocation and can't be pre-measured. Flag hooks that run on every tool call as potentially expensive.

   **2g. Agent definitions**
   Local agents are registered and their descriptions consume context:
   ```bash
   for f in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/agents/*.md; do
     name=$(basename "$f" .md)
     size=$(wc -c < "$f")
     echo "$name: $size bytes"
   done 2>/dev/null
   ```

4. **Build the budget table**

   Calculate totals and percentages against the active model's actual context window from `costs.context_windows` (Opus 5.5, Sonnet 5, and Fable 5.1 are all 1,000,000 tokens; Haiku 4.5 is 200,000; a fixed byte total is 5x more of Haiku's window than of the others', so getting this denominator right matters). Every "% of window" figure below must use this same window size, not a hardcoded 1M.

   Output in this format:

   ```
   # Moltbloat Token Budget

   **Claude config**: <config dir from `paths.py config-dir`> (moltbloat data: <`paths.py moltbloat-home`>)
   **Model**: <model in use, or "Opus 5.5 / Sonnet 5 / Fable 5.1 (assumed)" if unstated>
   **Context window**: <window for that model, e.g. 1,000,000 tokens, or 200,000 tokens for Haiku 4.5>
   **Total ecosystem cost**: ~X tokens (Y% of window)

   ## Breakdown by Source

   | Source | Bytes | ~Tokens | % of Window | Measured? | Notes |
   |--------|-------|---------|-------------|-----------|-------|
   | CLAUDE.md (global) | X | X | X% | measured (N) / est. | Always loaded |
   | CLAUDE.md (project) | X | X | X% | measured (N) / est. | Per-project |
   | Rules (common) | X | X | X% | est. | Always loaded |
   | Rules (typescript) | X | X | X% | est. | Language-specific |
   | Rules (python) | X | X | X% | est. | Language-specific |
   | ... | ... | ... | ... | ... | ... |
   <one row per other file in `sources.instructions.files` not already
   covered above, e.g. an AutoMem `MEMORY.md` or an ancestor-directory
   `CLAUDE.md`>
   | Skill listing (N skills, newest session) | - | X | X% | measured (N) / est. | In context every turn |
   | Deferred tool names (N names) | - | X | X% | measured (N) / est. | Names only; schemas load on use |
   | MCP server instructions | - | X | X% | measured (N) / est. | Per-server instruction blocks |
   | Agent listing | - | X | X% | measured (N) / est. | Agent types and descriptions |
   | SessionStart hook context | - | X | X% | measured (N) / est. | Injected once per session |
   | **TOTAL** | **X** | **X** | **X%** | | |

   **Note**: "Measured?" is `measured (N sessions)` using the ledger row's
   `samples` count when the ledger reports that source, or `est.` when the
   source is in `missing` and the row falls back to the 2a to 2g estimate.
   For CLAUDE.md (global) and CLAUDE.md (project), check whether
   `sources.instructions.files` includes that exact path: if it does, use
   that file's `median_tokens` and mark `measured (N)`; if not, keep the 2a
   byte-count estimate and mark `est.`. Add one further row for every other
   file `sources.instructions.files` reports that isn't CLAUDE.md (global)
   or (project) (an AutoMem `MEMORY.md`, an ancestor-directory `CLAUDE.md`,
   and so on); those rows are always `measured (N)` since they only appear
   when the ledger actually found the file.

   ## Top 5 Token Consumers
   1. <source> — X tokens (Y%)
   2. <source> — X tokens (Y%)
   3. ...

   ## Where the ledger points

   - Top 5 servers by deferred-name chars and by MCP instruction chars
     (from `by_server`), top 5 plugins by skill listing chars
     (`skill_listing.by_owner`, newest session), and hook context by owner
     (`hook_context.by_owner`), each named so the user can disable it.
   - If `sources.skill_listing.dropped` is non-empty (newest session):
     split it by `reason` rather than reporting every entry the same way.
     For entries with `reason == "has_description"`: "N skills are listed
     by name only; the description exists on disk but Claude never sees
     it:" then the names. Suggest disabling unused skill-heavy plugins
     (see `/moltbloat:usage`). For entries with `reason ==
     "source_not_found"`, list them separately: "N skills are listed by
     name only; their description could not be verified locally:" then the
     names. Do not call this second group dropped, since there is no local
     source confirming they ever had one.
   - Top 5 plugins by `plugin_costs[*].total_tokens`: each plugin's
     measured always-on context per session, split into skill listing,
     deferred tool names, MCP instructions, and hook output.
   - If `hook_context.unparsed_outputs` > 0: note that some SessionStart
     hooks print non-JSON output, which is not counted as context.

   ## Cost in Dollars

   Show both the uncached ceiling and the realistic steady-state price once
   Anthropic's prompt cache is warm. Ecosystem content (CLAUDE.md, rules,
   skill listings, MCP tool defs) is static within a session, exactly what
   prompt caching targets: turn 1 pays the cache-write rate (~1.25x base,
   writing the content to cache), every later turn in that session reads the
   cache instead at that model's cache-read rate (0.1x input on most models,
   0.05x on Opus 5.5, 0.025x on Fable 5.1). Pricing every message at full
   rate, as this skill used to, overstates steady-state cost 5-10x for any
   session past one turn. Pure API-level prompt-caching economics on input
   tokens, unrelated to Claude Code's own context-window auto-compaction.

   Rates come from `costs.models` (per 1M input tokens: Fable 5.1 $10.00,
   Opus 5.5 $4.00, Sonnet 5 $2.00, Haiku 4.5 $1.00, each with its own
   cache-read rate) and `costs.cache_write_multiplier` (default 1.25).

   Run once per model with `scripts/cache-cost.py --model` (computes the
   uncached ceiling, turn-1 write cost, turn-2+ read cost, a session-blended
   average, and daily/monthly cost) rather than doing the arithmetic in
   prose. Model ids: `claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5`,
   `claude-haiku-4-5`:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cache-cost.py" \
     --tokens <total_tokens> --model <model id> \
     --messages-per-day <messages_per_day> --json
   ```
   Exit 2 means that model has no rate in `costs.models`; show its row as
   "no rate configured" rather than a number.

   | Model | Turn 1 (uncached ceiling) | Turn 2+ (cache read, steady state) | Per Day (200 msgs) | Per Month |
   |-------|---------------------------|-------------------------------------|---------------------|-----------|
   | Fable 5.1 | $<uncached_cost> | $<cached_turn_cost> | $<daily_cost> | $<monthly_cost> |
   | Opus 5.5 | $<uncached_cost> | $<cached_turn_cost> | $<daily_cost> | $<monthly_cost> |
   | Sonnet 5 | $<uncached_cost> | $<cached_turn_cost> | $<daily_cost> | $<monthly_cost> |
   | Haiku 4.5 | $<uncached_cost> | $<cached_turn_cost> | $<daily_cost> | $<monthly_cost> |

   **Note**: "Turn 1" is the honest worst case (caching off, or a fresh
   session). "Turn 2+" is the realistic steady state once ecosystem content
   is cached. Both are FIXED overhead, the ecosystem tax on every message
   regardless of what you're doing; actual message content and tool results
   are on top of this.

   **Label these as estimates, not a bill.** They multiply token counts by
   list prices from config. They leave out output tokens, tool results,
   conversation history, and any discounts, so say so in the report. The
   provider's usage report is the source of truth for what was spent.

   ## Context Pressure

   Calculate what percentage of the context window is consumed by ecosystem overhead alone (before any user messages, tool results, or conversation history). Divide by the active model's actual window from `costs.context_windows`, not a flat 1M. For a Haiku 4.5 user this denominator is 200,000, so the same overhead reads as a 5x larger percentage than it would for Opus 5.5/Sonnet 5/Fable 5.1:

   ```
   Ecosystem overhead: ~<X> tokens (<Y>% of <window size> context window)
   Remaining for work: ~<Z> tokens
   ```

   The 3%/5% thresholds below are percentages of the *correct* per-model window, so they already scale correctly for Haiku 4.5 once the denominator is right (e.g. ~6K tokens is 3% of Haiku's 200K window, versus ~30K tokens being 3% of the shared 1M window).

   If overhead exceeds 3% of the active window:
   > **Context pressure: ELEVATED** — Your ecosystem consumes <Y>% of the context
   > window before you start working. For long sessions, you'll need to `/compact`
   > sooner. Consider `/moltbloat:profile lean` for extended work sessions.

   If overhead exceeds 5% of the active window:
   > **Context pressure: HIGH** — At <Y>% ecosystem overhead, you're losing
   > significant working context. This means more frequent `/compact` cycles.
   > Strongly recommend reviewing the top consumers above.

   ## Effort Setting Impact

   Show how `/effort` interacts with ecosystem overhead:

   ```
   Your ecosystem costs ~<X> tokens/message regardless of effort level.

   | Effort | Assumed response | Ecosystem as % of message |
   |--------|-----------------|--------------------------|
   | low    | ~2K tokens      | <X / (X+2000) * 100>%   |
   | medium | ~8K tokens      | <X / (X+8000) * 100>%   |
   | high   | ~20K tokens     | <X / (X+20000) * 100>%  |
   ```

   The response sizes are illustrative assumptions, not measurements; say so
   under the table.

   If ecosystem overhead is >30K tokens:
   > **Tip**: With <X> tokens of ecosystem overhead, `/effort low` still costs
   > ~<X+2000> tokens per message — the ecosystem is the dominant cost, not
   > your response. Use `/moltbloat:profile lean` to make `/effort low` truly lean.

   ## Recommendations

   Never state a saving (a percentage, a token count, or dollars) for
   removing or disabling something unless it comes from this report's own
   measured rows. "Disabling X removes its measured N tokens per session" is
   fine; "cut your overhead by 30-50%" is not.
   - Items consuming >5% of context with low/no usage should be reviewed
   - Consider disabling language rules you don't actively use
   - MCP tools are a hidden cost. If `deferred_tools` was measured, cite the
     measured figures: `deferred_tools.median_tokens` tokens across
     `deferred_tools.median_names` tool names, currently names-only in
     context until a tool is loaded, then its full schema counts too. Only
     when `deferred_tools` is in `missing` (est. path), fall back to the
     estimate: each registered tool consumes roughly 350 tokens.
   - Use `/moltbloat:profile lean` to cut costs for simple tasks
   - For long sessions, consider `/compact` before the window fills (a rule
     of thumb, not a measured threshold)
   - Run `/moltbloat:usage` to see which costly components you actually use
   - Run `/moltbloat:audit` for full redundancy analysis
   ```

5. **Done**

   This skill is read-only. No modifications are made.

</Steps>
