#!/usr/bin/env python3
"""Measure what subagent delegation actually costs, from Claude Code transcripts.

Each subagent run is a transcript at
~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl with a
sibling agent-<id>.meta.json (agentType, model alias, description). This
script prices every run from its own recorded token usage:

- Streamed messages repeat the same message id; each id is counted once,
  taking the largest value of each usage field.
- Prices come from the per-model table in config (`costs.models`), matched
  by model id prefix. A model with no rate is reported as unpriced, never
  guessed.
- Spin-up cost is the first message's input-side cost: the price of giving
  a fresh subagent its context.
- A "mechanical on premium" candidate is a run on an Opus or Fable model
  whose tool calls were all read-only and whose final reply was short. Its
  saving is priced by re-costing the same measured tokens on the suggested
  cheaper model, never against zero. Token counts could differ on another
  model, so this is an estimate and is labeled one.

Also inventories agent definitions (user, project, plugin) and flags
unpinned agents (no `model:`, or `model: inherit`) that have real spend.

Usage:
  python3 delegation-cost.py [--since DAYS|all] [--project DIR] [--projects-dir DIR]
                             [--config-dir DIR] [--rates-json FILE]
                             [--instructions FILE,FILE,...] [--json]

--instructions: instruction files to check for prose that names an agent
and a model tier its `model:` pin contradicts. Rates default to
`costs.models` in moltbloat config; --rates-json overrides (tests).
"""
import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
CONFIG_DIR = os.path.expanduser("~/.claude")

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.0
PREMIUM_FAMILIES = ("opus", "fable")
SUGGESTED_MODEL = {"opus": "claude-sonnet-5", "fable": "claude-sonnet-5"}
SHORT_REPLY_CHARS = 2000

READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "LS", "NotebookRead", "WebFetch", "WebSearch", "ToolSearch",
                   "SubagentHandback"}
READ_ONLY_BASH = {"ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "file", "stat", "du", "tree", "pwd",
                  "echo", "printf", "true", "which", "date"}
READ_ONLY_GIT = {"log", "diff", "show", "status", "blame", "rev-parse", "branch"}
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                "output_tokens", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")


def load_rates():
    """Per-model rates from moltbloat config (`costs.models`), read-only."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("init_config", os.path.join(HERE, "init-config.py"))
    ic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ic)
    rates = (ic.load_config().get("costs") or {}).get("models")
    if not rates:
        raise KeyError("costs.models missing from moltbloat config")
    return rates


def rates_for(model, rates):
    """Rate entry for the longest matching model-id prefix, or None."""
    best = None
    for prefix in rates:
        if model and model.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return rates[best] if best else None


def family(model):
    for fam in ("fable", "opus", "sonnet", "haiku"):
        if model and fam in model:
            return fam
    return "unknown"


def price(tokens, rate):
    """Dollar cost of one usage dict under a rate entry."""
    per = lambda n, r: n * r / 1_000_000
    w5 = tokens.get("ephemeral_5m_input_tokens", 0)
    w1 = tokens.get("ephemeral_1h_input_tokens", 0)
    other_write = max(tokens.get("cache_creation_input_tokens", 0) - w5 - w1, 0)
    return (per(tokens.get("input_tokens", 0), rate["input"])
            + per(w5 + other_write, rate["input"] * CACHE_WRITE_5M)
            + per(w1, rate["input"] * CACHE_WRITE_1H)
            + per(tokens.get("cache_read_input_tokens", 0), rate["cache_read"])
            + per(tokens.get("output_tokens", 0), rate["output"]))


def _flat_usage(usage):
    out = {k: int(usage.get(k) or 0) for k in USAGE_FIELDS[:4]}
    cc = usage.get("cache_creation") or {}
    out["ephemeral_5m_input_tokens"] = int(cc.get("ephemeral_5m_input_tokens") or 0)
    out["ephemeral_1h_input_tokens"] = int(cc.get("ephemeral_1h_input_tokens") or 0)
    return out


HARMLESS_REDIRECT_RE = re.compile(r"\s*(2>/dev/null|2>&1|>/dev/null)")


def _bash_read_only(cmd):
    """True if every segment of a pipeline / && / ; chain is a read-only
    command. Any remaining redirect or command substitution fails it."""
    cmd = HARMLESS_REDIRECT_RE.sub("", cmd or "")
    # Quoted arguments (e.g. grep -E "a|b") must not be split as pipes.
    cmd = re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", "ARG", cmd)
    if not cmd.strip() or any(tok in cmd for tok in (">", "$(", "`")):
        return False
    for seg in re.split(r"\|\||&&|;|\|", cmd):
        words = seg.strip().split()
        if not words:
            continue
        if words[0] == "cd":
            continue
        if words[0] == "git":
            if not (len(words) > 1 and words[1] in READ_ONLY_GIT):
                return False
        elif words[0] == "sed":
            if "-n" not in words or "-i" in words:
                return False
        elif words[0] not in READ_ONLY_BASH:
            return False
    return True


def parse_run(path):
    """One subagent run: deduped per-model usage, tools, first/last message."""
    messages = {}  # message id -> {model, usage, order}
    tools, last_text, first_ts = [], "", None
    order = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"assistant"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message") or {}
            first_ts = first_ts or obj.get("timestamp")
            usage = msg.get("usage")
            mid = msg.get("id")
            if usage and mid and msg.get("model") != "<synthetic>":
                flat = _flat_usage(usage)
                if mid in messages:
                    prev = messages[mid]["usage"]
                    messages[mid]["usage"] = {k: max(prev[k], flat[k]) for k in flat}
                else:
                    messages[mid] = {"model": msg.get("model"), "usage": flat, "order": order}
                    order += 1
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tools.append((block.get("name"), (block.get("input") or {}).get("command")))
                elif block.get("type") == "text" and block.get("text"):
                    last_text = block["text"]
    return {"messages": sorted(messages.values(), key=lambda m: m["order"]),
            "tools": tools, "last_text": last_text, "first_ts": first_ts}


def read_only_run(tools):
    if not tools:
        return True
    for name, cmd in tools:
        if name == "Bash":
            if not _bash_read_only(cmd):
                return False
        elif name not in READ_ONLY_TOOLS:
            return False
    return True


def load_meta(path):
    meta_path = path[:-len(".jsonl")] + ".meta.json"
    if not os.path.isfile(meta_path):
        return {}, None
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f), None
    except ValueError as e:
        return {}, f"{meta_path}: unparseable ({e})"


def find_runs(projects_dir, project=None):
    pattern = os.path.join(projects_dir, "*", "*", "subagents", "agent-*.jsonl")
    runs = glob.glob(pattern)
    if project:
        enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(project))
        runs = [r for r in runs if os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(r)))).startswith(enc)]
    return runs


def _parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def agent_inventory(config_dir, project=None):
    """Agent definitions: {name: {source, path, model}} (model None = inherits)."""
    dirs = [("user", os.path.join(config_dir, "agents"))]
    if project:
        dirs.append(("project", os.path.join(project, ".claude", "agents")))
    manifest = os.path.join(config_dir, "plugins", "installed_plugins.json")
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            for key, entries in (json.load(f).get("plugins") or {}).items():
                for entry in entries or []:
                    if (entry or {}).get("installPath"):
                        dirs.append((f"plugin:{key.split('@', 1)[0]}", os.path.join(entry["installPath"], "agents")))
    inv = {}
    for source, d in dirs:
        for p in sorted(glob.glob(os.path.join(d, "*.md"))):
            with open(p, encoding="utf-8", errors="replace") as f:
                fm = _parse_frontmatter(f.read())
            name = fm.get("name") or os.path.splitext(os.path.basename(p))[0]
            model = fm.get("model") or None
            if model == "inherit":
                model = None
            key = name if source in ("user", "project") else f"{source.split(':', 1)[1]}:{name}"
            inv.setdefault(key, {"source": source, "path": p, "model": model})
    return inv


def analyze(runs, rates, since_days=None, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=since_days) if since_days is not None else None
    groups, unpriced, errors, candidates, spinups = {}, {}, [], [], {}
    total_cost, scanned = 0.0, 0
    for path in runs:
        run = parse_run(path)
        if not run["messages"]:
            continue
        if cutoff and run["first_ts"]:
            try:
                ts = datetime.fromisoformat(run["first_ts"].replace("Z", "+00:00"))
            except ValueError:
                ts = None
            if ts and ts < cutoff:
                continue
        scanned += 1
        meta, err = load_meta(path)
        if err:
            errors.append(err)
        agent_type = meta.get("agentType") or "unknown"
        run_cost, priced_all = 0.0, True
        models = set()
        for m in run["messages"]:
            model = m["model"] or "unknown"
            models.add(model)
            rate = rates_for(model, rates)
            if rate is None:
                priced_all = False
                u = unpriced.setdefault(model, {"messages": 0, "output_tokens": 0})
                u["messages"] += 1
                u["output_tokens"] += m["usage"]["output_tokens"]
                continue
            run_cost += price(m["usage"], rate)
        main_model = max(models, key=lambda x: sum(1 for m in run["messages"] if (m["model"] or "unknown") == x))
        fam = family(main_model)
        g = groups.setdefault((agent_type, main_model), {"runs": 0, "cost": 0.0, "output_tokens": 0,
                                                        "input_side_tokens": 0, "unpriced_runs": 0})
        g["runs"] += 1
        g["cost"] += run_cost
        g["unpriced_runs"] += 0 if priced_all else 1
        for m in run["messages"]:
            u = m["usage"]
            g["output_tokens"] += u["output_tokens"]
            g["input_side_tokens"] += u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"]
        total_cost += run_cost
        first = run["messages"][0]
        rate = rates_for(first["model"], rates)
        if rate:
            spin = dict(first["usage"], output_tokens=0)
            spinups.setdefault(agent_type, []).append(price(spin, rate))
        if fam in PREMIUM_FAMILIES and priced_all and read_only_run(run["tools"]) and len(run["last_text"]) <= SHORT_REPLY_CHARS:
            alt_model = SUGGESTED_MODEL[fam]
            alt_rate = rates_for(alt_model, rates)
            alt_cost = sum(price(m["usage"], alt_rate) for m in run["messages"])
            candidates.append({"run": path, "agent_type": agent_type, "model": main_model,
                               "description": meta.get("description", ""), "cost": run_cost,
                               "suggested_model": alt_model, "cost_on_suggested": alt_cost,
                               "estimated_saving": run_cost - alt_cost})
    by_group = [{"agent_type": k[0], "model": k[1], **v} for k, v in groups.items()]
    by_group.sort(key=lambda x: -x["cost"])
    candidates.sort(key=lambda x: -x["estimated_saving"])
    return {"generated_at": now.isoformat().replace("+00:00", "Z"), "since_days": since_days,
            "runs_scanned": scanned, "total_cost": total_cost, "by_agent_type_model": by_group,
            "spin_up": {k: {"runs": len(v), "median_cost": statistics.median(v)} for k, v in spinups.items()},
            "mechanical_on_premium": candidates, "unpriced_models": unpriced, "errors": errors}


def unpinned_findings(result, inventory):
    """Agents without a model pin, ranked by measured spend."""
    spend, mix = {}, {}
    for g in result["by_agent_type_model"]:
        spend[g["agent_type"]] = spend.get(g["agent_type"], 0.0) + g["cost"]
        mix.setdefault(g["agent_type"], []).append((g["model"], g["runs"]))
    out = []
    for name, a in inventory.items():
        if a["model"]:
            continue
        bare = name.split(":")[-1]
        key = name if name in spend else bare
        cost = spend.get(key, 0.0)
        models = ", ".join(f"{m} x{n}" for m, n in sorted(mix.get(key, []), key=lambda x: -x[1]))
        out.append({"type": "unpinned_agent", "agent": name, "path": a["path"], "spend": cost,
                    "model_mix": mix.get(key, []), "severity": "MEDIUM" if cost > 0 else "LOW",
                    "message": (f"`{name}` has no `model:` pin, so its model is whatever each caller or the session picks"
                                + (f"; measured spend ${cost:,.2f} across {models}." if cost > 0 else "; no measured runs."))})
    out.sort(key=lambda f: -f["spend"])
    return out


TIER_RE = re.compile(r"\b(haiku|sonnet|opus|fable)\b", re.IGNORECASE)


def prose_conflicts(instruction_paths, inventory):
    """Lines naming an agent and a model tier that disagree with its pin."""
    out = []
    for p in instruction_paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        for n, line in enumerate(lines, 1):
            tiers = {t.lower() for t in TIER_RE.findall(line)}
            if len(tiers) != 1:
                continue  # zero tiers, or several (a routing table) is ambiguous
            tier = tiers.pop()
            for name, a in inventory.items():
                bare = name.split(":")[-1]
                if not re.search(r"(?<![\w-])" + re.escape(bare) + r"(?![\w-])", line):
                    continue
                pinned = (a["model"] or "").lower()
                if tier in pinned:
                    continue
                out.append({"type": "delegation_prose_conflict", "severity": "MEDIUM", "file": p, "line": n,
                            "agent": name,
                            "message": (f"Line names `{bare}` with {tier}, but its definition "
                                        + (f"pins `model: {a['model']}`." if a["model"] else "has no model pin (inherits the session model).")
                                        + f" Prose does not change the model; set `model:` in {a['path']}.")})
    return out


def render_markdown(result, unpinned, conflicts):
    L = ["# Delegation Cost", "",
         f"Subagent runs: {result['runs_scanned']}" + (f" (last {result['since_days']} days)" if result["since_days"] else ""),
         f"Measured spend: ${result['total_cost']:,.2f} (list prices; see Honest numbers)", "",
         "| Agent type | Model | Runs | Spend | Output tokens |", "|---|---|---|---|---|"]
    for g in result["by_agent_type_model"][:15]:
        L.append(f"| {g['agent_type']} | {g['model']} | {g['runs']} | ${g['cost']:,.2f} | {g['output_tokens']:,} |")
    if result["spin_up"]:
        L += ["", "## Spin-up cost (first message, per run)", "", "| Agent type | Runs | Median |", "|---|---|---|"]
        for k, v in sorted(result["spin_up"].items(), key=lambda kv: -kv[1]["median_cost"]):
            L.append(f"| {k} | {v['runs']} | ${v['median_cost']:.3f} |")
    c = result["mechanical_on_premium"]
    if not c:
        L += ["", "## Read-only runs on Opus/Fable", "",
              "None: no Opus or Fable run in this window was both read-only and short-replied."]
    else:
        total = sum(x["estimated_saving"] for x in c)
        L += ["", f"## Read-only runs on Opus/Fable ({len(c)} candidates)", "",
              f"Re-pricing their measured tokens on the suggested model would have cost ${total:,.2f} less "
              "(an estimate: another model may use different token counts).", ""]
        for x in c[:10]:
            L.append(f"- {x['agent_type']} on {x['model']}: ${x['cost']:.2f} -> ~${x['cost_on_suggested']:.2f} on {x['suggested_model']} ({x['description'][:60]})")
    if unpinned:
        L += ["", "## Unpinned agents", ""] + [f"- [{f['severity']}] {f['message']} ({f['path']})" for f in unpinned]
    if conflicts:
        L += ["", "## Prose vs model pin", ""] + [f"- {f['file']}:{f['line']}: {f['message']}" for f in conflicts]
    if result["unpriced_models"]:
        L += ["", "Unpriced (no rate in config): " + ", ".join(f"{k} ({v['messages']} messages)" for k, v in result["unpriced_models"].items())]
    if result["errors"]:
        L += ["", "## Unparseable files", ""] + [f"- {e}" for e in result["errors"]]
    return "\n".join(L)


def main(argv):
    opts = {"--since": "30", "--project": None, "--projects-dir": PROJECTS_DIR,
            "--config-dir": CONFIG_DIR, "--rates-json": None, "--instructions": None}
    as_json, args, i = False, argv[1:], 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a in opts:
            i += 1
            if i >= len(args):
                sys.stderr.write(f"error: {a} requires a value\n")
                return 2
            opts[a] = args[i]
        else:
            sys.stderr.write(f"error: unknown argument {a}\n")
            return 2
        i += 1
    try:
        since = None if opts["--since"] == "all" else int(opts["--since"])
    except ValueError:
        sys.stderr.write("error: --since must be a number of days or 'all'\n")
        return 2
    if not os.path.isdir(opts["--projects-dir"]):
        sys.stderr.write(f"error: projects dir not found: {opts['--projects-dir']}\n")
        return 1
    if opts["--rates-json"]:
        with open(opts["--rates-json"], encoding="utf-8") as f:
            rates = json.load(f)
    else:
        rates = load_rates()
    runs = find_runs(opts["--projects-dir"], opts["--project"])
    result = analyze(runs, rates, since_days=since)
    inventory = agent_inventory(opts["--config-dir"], opts["--project"])
    unpinned = unpinned_findings(result, inventory)
    paths = [p for p in (opts["--instructions"] or "").split(",") if p]
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        sys.stderr.write(f"error: instruction file not found: {missing[0]}\n")
        return 1
    conflicts = prose_conflicts(paths, inventory)
    if as_json:
        print(json.dumps({**result, "inventory": inventory, "unpinned_agents": unpinned,
                          "prose_conflicts": conflicts}, indent=2))
    else:
        print(render_markdown(result, unpinned, conflicts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
