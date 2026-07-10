// deep-audit-workflow.js — canonical Workflow script for /moltbloat:audit --deep.
//
// Launch via the Workflow tool with args:
//   {
//     factsPath:  "/abs/path/to/recon-facts.md",   // output of scripts/deep-recon.py (required)
//     configDir:  "/abs/path/to/.claude",           // audited config dir (required)
//     depth:      "standard" | "thorough",          // thorough = more verify votes + 3rd ideation lens
//     ideation:   true | false                      // default true
//   }
// Returns { audits, ideas, stats } — the caller assembles the report artifact
// from this JSON using skills/audit/report-template.html.
//
// This script contains NO user-specific facts: all ground truth comes from the
// recon FACTS file, which every agent Reads itself.

export const meta = {
  name: 'moltbloat-deep-audit',
  description: 'Multi-agent forensic audit of a Claude Code config: 7 scoped auditors, adversarial verification, ideation',
  phases: [
    { title: 'Audit', detail: '7 parallel auditors over config surfaces' },
    { title: 'Verify', detail: 'adversarial verification of high-severity findings' },
    { title: 'Ideate', detail: 'improvement lenses over the verified digest' },
  ],
}

if (!args || !args.factsPath || !args.configDir) {
  throw new Error('deep-audit-workflow requires args.factsPath and args.configDir (run scripts/deep-recon.py first)')
}
const DEPTH = args.depth === 'thorough' ? 'thorough' : 'standard'
const IDEATION = args.ideation !== false

const AUDIT_SCHEMA = {
  type: 'object', required: ['summary', 'findings'], additionalProperties: false,
  properties: {
    summary: { type: 'string', description: '2-3 sentence overall assessment of this surface' },
    findings: { type: 'array', maxItems: 10, items: {
      type: 'object', required: ['severity', 'title', 'detail', 'recommendation'], additionalProperties: false,
      properties: {
        severity: { enum: ['high', 'medium', 'low'] },
        title: { type: 'string' },
        detail: { type: 'string', description: 'what is wrong, <=60 words' },
        evidence: { type: 'array', items: { type: 'string' }, description: 'exact file paths and quotes' },
        recommendation: { type: 'string', description: 'concrete fix with real paths/commands, <=50 words' },
        token_impact: { type: 'string', description: 'rough per-session token cost if estimable, else empty' },
      },
    } },
  },
}

const VERDICT_SCHEMA = {
  type: 'object', required: ['verdict', 'note'], additionalProperties: false,
  properties: {
    verdict: { enum: ['CONFIRMED', 'REFUTED', 'PARTIAL'] },
    note: { type: 'string', description: '<=40 words: what you checked and what you found' },
  },
}

const IDEA_SCHEMA = {
  type: 'object', required: ['ideas'], additionalProperties: false,
  properties: { ideas: { type: 'array', maxItems: 5, items: {
    type: 'object', required: ['title', 'description', 'implementation', 'payoff'], additionalProperties: false,
    properties: {
      title: { type: 'string' },
      description: { type: 'string', description: 'the idea, <=80 words' },
      implementation: { type: 'string', description: 'first steps with real paths/commands, <=80 words' },
      payoff: { type: 'string', description: '<=30 words' },
      risk: { type: 'string', description: '<=25 words' },
    },
  } } },
}

const PREAMBLE = `You are one auditor in a multi-agent forensic audit of a Claude Code configuration at ${args.configDir}. FIRST ACTION: Read ${args.factsPath} — it holds deterministic ground truth (sizes, inventories, phantom references, duplicate MCP servers, usage counts) so you investigate rather than re-derive inventory. Then read the actual files in your scope; cite exact paths and verbatim quotes as evidence. Report only findings that materially confuse the model or waste tokens — be severe but fair. The user's real usage data (skill_usage_top / skill_usage_zero_or_one in FACTS) is the oracle for what earns its keep. Max 10 findings ranked by severity.\n\nYOUR SCOPE: `

const SCOPES = [
  { key: 'claude-md', prompt: `The instruction files injected into every session: CLAUDE.md (and AGENTS.md if present) plus any loose .md files at the config root. Hunt for: (1) instructions referencing plugins/agents/skills/scripts that are disabled or don't exist (cross-check FACTS phantom_refs and plugins_disabled); (2) internal contradictions — two model policies, conflicting completion gates, duplicate rules; (3) content that belongs in a project, not global scope; (4) stale blocks injected by uninstalled tools; (5) dead backup files. Estimate token cost per section vs its value given usage data.` },
  { key: 'rules', prompt: `The rules/ tree (if present) — every file here is injected into EVERY session. Hunt for: (1) documentation-for-humans (install guides, contributor docs) riding in model context; (2) rules duplicating CLAUDE.md or on-demand skills; (3) unsatisfiable mandates (coverage thresholds, checklists that can't apply to this user's actual work) — these train the model to ignore ALL rules; (4) rules referencing phantom agents/tools; (5) contradictions between rules files. Propose the minimal high-signal survivor set. If no rules/ dir exists, say so and return zero findings.` },
  { key: 'settings', prompt: `settings.json and the state file (path in FACTS). Hunt for: (1) permissions.allow one-off session junk (FACTS lists suspects — verify and extend); (2) hooks config: empty stubs, or hooks pointing at missing scripts; (3) model pins with premium suffixes; (4) plugin enable/disable state contradicting other config; (5) stale project entries pointing at deleted paths (FACTS lists them); (6) plaintext secrets ANYWHERE in these files (report the key name, never the value); (7) env flags for features that no longer exist. Do NOT modify anything.` },
  { key: 'mcp-plugins', prompt: `The MCP + plugin surface as a token-cost problem. Using FACTS plugin_surface, state.global/project servers, and duplicate_server_names: (1) duplicate or overlapping servers (same server registered twice, MCP duplicating native tools like filesystem-vs-Read, connectors exposing identical tool sets); (2) per-plugin cost vs usage — plugins whose skills/tools inject large listings with zero-or-one lifetime uses (cross-check skill_usage); (3) auth-stub servers exposing only authenticate tools; (4) plugin cache bloat (stale versions, temp clone dirs). Recommend a global-vs-per-project split with expected token savings.` },
  { key: 'skills-commands', prompt: `Local skills/ and commands/ dirs (inventory in FACTS). Hunt for: (1) skills/commands referencing dead infrastructure (missing scripts — FACTS phantom_refs — nonexistent agents, uninstalled plugin namespaces); (2) overlap clusters — multiple skills/commands doing the same job (planning, review, session-saving, TDD); count the doors the model must arbitrate between; (3) leftovers from uninstalled frameworks (compare mtimes and content against plugin caches); (4) usage-based keep/archive split using skill_usage data. Cite exact paths.` },
  { key: 'hooks-hygiene', prompt: `Hooks + background machinery + disk hygiene. (1) What actually executes per session/tool-call: hooks in settings.json AND plugin-provided hooks (check plugins cache hooks.json files for enabled plugins) — what does each inject and cost? (2) Orphaned hook scripts on disk that nothing references. (3) Statusline: what does it run, does it reference dead tools? (4) Disk: using FACTS disk breakdown, identify what is safely reclaimable (old transcripts, stale plugin versions, caches) with exact commands and expected reclaim. Do NOT delete anything.` },
  { key: 'memory-systems', prompt: `Memory/persistence systems (FACTS memory_systems). Enumerate every system present: native project memory dirs, memory plugins (claude-mem etc.), session-save skills, loose learnings/notes files, framework state dirs. For each: is it accumulating data or an empty shell? Do any double-inject the same knowledge per session? Do any run background LLM calls (check for observer processes/models in their settings)? Are there knowledge files that NOTHING reads (orphaned learnings)? Design the single-source-of-truth consolidation.` },
]

log(`Deep audit: 7 auditors (${DEPTH} depth) over ${args.configDir}`)

const VOTES = DEPTH === 'thorough' ? 3 : 1

const audits = await pipeline(
  SCOPES,
  s => agent(PREAMBLE + s.prompt, { label: `audit:${s.key}`, phase: 'Audit', schema: AUDIT_SCHEMA }),
  async (res, s) => {
    if (!res) return null
    const highs = (res.findings || []).filter(f => f.severity === 'high').slice(0, 3)
    const verdicts = await parallel(highs.map(f => () =>
      parallel(Array.from({ length: VOTES }, (_, v) => () =>
        agent(
          `Adversarially verify this claim about the Claude Code config at ${args.configDir}. Read the cited files yourself; try to REFUTE it. If evidence paths don't exist or quotes are wrong, verdict REFUTED. If directionally right but a detail is off, PARTIAL. Ground truth FACTS: Read ${args.factsPath}.\n\nCLAIM: ${JSON.stringify(f)}`,
          { label: `verify:${s.key}:${v}`, phase: 'Verify', schema: VERDICT_SCHEMA }
        )))
        .then(votes => {
          const ok = votes.filter(Boolean)
          const confirmed = ok.filter(x => x.verdict === 'CONFIRMED').length
          const refuted = ok.filter(x => x.verdict === 'REFUTED').length
          const verdict = refuted > ok.length / 2 ? 'REFUTED' : confirmed > ok.length / 2 ? 'CONFIRMED' : 'PARTIAL'
          return { title: f.title, verdict, notes: ok.map(x => x.note) }
        })
    ))
    return { key: s.key, summary: res.summary, findings: res.findings, verdicts: verdicts.filter(Boolean) }
  }
)

const okAudits = audits.filter(Boolean)
const digest = JSON.stringify({
  findings: okAudits.flatMap(a => (a.findings || []).map(f => ({
    area: a.key, sev: f.severity, title: f.title, rec: f.recommendation,
    verified: (a.verdicts || []).find(v => v.title === f.title)?.verdict || null,
  }))),
}).slice(0, 24000)

let ideas = []
if (IDEATION) {
  const LENSES = [
    { key: 'token-economics', prompt: 'You are a ruthless token-economics engineer. Propose up to 5 NON-OBVIOUS interventions purely about cost/speed for this config: cache-stable prefixes, lazy loading, per-project scoping, measuring $/session, killing double-injection. Build ON the audit digest, do not restate it. Implementable this week with real paths/commands.' },
    { key: 'self-improving', prompt: 'You are a systems designer obsessed with feedback loops. Propose up to 5 ideas making this config SELF-improving: friction-capture hooks, scheduled drift re-audits, config-as-code with lint gates, usage telemetry driving auto-archival, golden-task evals gating config changes. Concrete, this-week implementable.' },
    ...(DEPTH === 'thorough' ? [{ key: 'radical-rethink', prompt: 'You are a contrarian architect. Propose up to 5 RADICAL simplifications the user would never think of: config bankruptcy rebuilds, replacing static rules with just-in-time skills, zero global capabilities with bootstrap-derived per-project config, TTL-based decay quarantine. Each: what to delete, what replaces it, migration path.' }] : []),
  ]
  const r = await parallel(LENSES.map(l => () =>
    agent(`${l.prompt}\n\nThe config lives at ${args.configDir}; ground truth FACTS at ${args.factsPath} (Read it first).\n\nAUDIT DIGEST:\n${digest}`,
      { label: `ideate:${l.key}`, phase: 'Ideate', schema: IDEA_SCHEMA, effort: 'high' })))
  ideas = LENSES.map((l, i) => ({ lens: l.key, ideas: r[i] ? r[i].ideas : [] }))
}

return {
  audits: okAudits,
  ideas,
  stats: {
    scopes_completed: okAudits.length,
    total_findings: okAudits.reduce((n, a) => n + (a.findings || []).length, 0),
    highs_confirmed: okAudits.reduce((n, a) => n + (a.verdicts || []).filter(v => v.verdict === 'CONFIRMED').length, 0),
    highs_refuted: okAudits.reduce((n, a) => n + (a.verdicts || []).filter(v => v.verdict === 'REFUTED').length, 0),
    depth: DEPTH,
  },
}
