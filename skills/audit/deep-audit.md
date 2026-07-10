# /moltbloat:audit --deep — multi-agent forensic audit

Produces what the standard audit cannot: findings **adversarially verified** by
independent agents, a per-session token-waste ledger, outside-the-box
improvement ideas, and a polished shareable report artifact. Modeled on a
production audit that found ~17k wasted tokens/session in a real config by
fanning out 7 scoped auditors and re-verifying every high-severity claim.

Flags: `--thorough` (3 verify votes per finding + a third ideation lens),
`--no-ideas` (skip ideation), `--yes` (skip the cost confirmation).

## Principles

- **Recon is deterministic, judgment is delegated.** A script gathers ground
  truth; agents only investigate and judge. Never let agents re-derive inventory.
- **No unverified highs.** Every high-severity finding is attacked by an
  independent verifier before it reaches the report. Report REFUTED counts in
  the method footer — killed findings are evidence the process works.
- **Usage data is the oracle.** What the user actually invokes (skill usage,
  transcript history) decides what earns its keep — not opinions.
- **Read-only.** The audit changes nothing. Cleanup is a separate, explicit step.

## Procedure

### 1. Confirm cost (unless --yes)

Deep mode spawns 10-30 subagents (roughly 1-3M tokens; more with --thorough).
Ask the user to confirm before proceeding, stating those numbers. If they
decline, offer the standard `/moltbloat:audit` instead.

### 2. Recon (deterministic)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/deep-recon.py" > /tmp/moltbloat-deep/recon-facts.md
```

Create the output dir first (`mkdir -p /tmp/moltbloat-deep`), or use your
session scratchpad if one exists. Pass an explicit config dir as the first
argument when auditing a non-default location. Skim the FACTS output: if it is
mostly empty (fresh install), tell the user there is nothing to deep-audit and
stop.

If usage history exists, also capture the cost baseline now — it strengthens
the report's ledger and MUST happen before any later cleanup deletes
transcripts:

```bash
npx -y ccusage@latest daily --breakdown > /tmp/moltbloat-deep/cost-baseline.txt 2>&1 || true
```

### 3. Fan out (orchestrated)

**If a `Workflow` tool is available** (check your tool list), launch the
canonical script — do not rewrite it, do not inline your own facts:

```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/deep-audit-workflow.js",
  args: {
    factsPath: "/tmp/moltbloat-deep/recon-facts.md",
    configDir: "<the audited dir>",
    depth: "standard" | "thorough",
    ideation: true | false
  }
})
```

**If no Workflow tool exists**, degrade gracefully: dispatch the 7 auditor
scopes as parallel subagents (Agent/Task tool) using the scope prompts inside
`deep-audit-workflow.js` (read the file; the SCOPES array is the source of
truth), then verify each high-severity finding with one adversarial subagent
each, then run the ideation lenses. If subagents are unavailable entirely,
work the scopes sequentially yourself in one context and say so in the report's
method footer — findings are then self-reviewed, not independently verified,
and the report must not claim otherwise.

While the fleet runs, do not idle-poll; you will be notified on completion.

### 4. Assemble the report artifact

Build the report from `report-template.html` in this skill's directory —
follow the ASSEMBLY RULES comment at the top of that file. Content rules:

- **Headline names the root cause**, not a generic title. Most configs have
  one story told seven ways (a half-uninstalled framework, an accretion of
  plugins, a memory system duplicating itself) — find it and lead with it.
- **Ledger**: one row per waste source with midpoint token estimates from the
  auditors; total prominently. If token estimates are thin, say "unmeasured"
  rather than inventing numbers.
- **Findings**: only CONFIRMED/PARTIAL highs get cards (PARTIAL keeps a "warn"
  chip and one sentence on what was overstated). Mediums/lows compress into
  one paragraph per area. REFUTED findings appear only as a count in the footer.
- **Plan**: 3-6 passes ordered by leverage, each independently safe, with
  exact commands. Always include the safety callout: git-init the config
  first, capture the cost baseline before purging transcripts, and name any
  re-injection traps found (tools that rewrite CLAUDE.md on update).
- Publish via the Artifact tool if available; otherwise write the HTML file
  and tell the user its path.

### 5. Summarize in chat

End with: the one-sentence diagnosis, the headline numbers (tokens/session,
disk reclaimable, findings confirmed/refuted), the top 3 actions, and the
artifact link. Offer to execute the cleanup as a follow-up — never start it
unasked.

## Failure modes to avoid

| Trap | Rule |
|------|------|
| Agents inventing inventory | All counts come from recon FACTS; agents cite file evidence for judgments only |
| Plausible-but-wrong findings | No high finding ships unverified; default skeptical |
| Grep counts as usage | Tool names appear in system-prompt listings inside transcripts; count only `"name":"mcp__..."` invocation records |
| Cost estimates presented as measurements | Label estimates as estimates; the ccusage baseline is the only measurement |
| Report drowns in mediums | Cards for verified highs only; compress the rest |
| Auditing a fresh/empty config | Stop after recon and say there's nothing to audit |
