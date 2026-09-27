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
READ_ONLY_GIT = {"log", "diff", "show", "status", "blame", "rev-parse"}
GIT_BRANCH_LIST_FLAGS = {"-a", "-r", "-v", "-vv", "--list", "--all", "--remotes", "--show-current"}
FIND_WRITE_FLAGS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
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


DATE_SUFFIX_RE = re.compile(r"-\d{8}$")


def rates_for(model, rates):
    """Rate entry for `model`: an exact id, or an id plus a -YYYYMMDD date
    suffix. A newer model sharing a prefix (claude-opus-5-7 vs claude-opus-5)
    gets no rate rather than a guessed one."""
    if not model:
        return None
    if model in rates:
        return rates[model]
    base = DATE_SUFFIX_RE.sub("", model)
    return rates.get(base)


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


def _git_read_only(words):
    """words after `git`; skips -C <dir> and -c <k=v> global options."""
    i = 0
    while i < len(words) and words[i] in ("-C", "-c"):
        i += 2
    if i >= len(words):
        return False
    sub, rest = words[i], words[i + 1:]
    if any(w.startswith("--output") for w in rest):
        return False
    if sub == "branch":
        return all(w in GIT_BRANCH_LIST_FLAGS for w in rest)
    return sub in READ_ONLY_GIT


def _bash_read_only(cmd):
    """True if every segment of a command chain is a read-only command.

    Segments split on newlines, ;, &&, ||, |, and a lone &. Redirects,
    command substitution, and heredocs fail it; so do write-capable flags
    on otherwise read-only tools (find -delete/-exec, sed -i or a w
    command, git branch with a name, git diff --output).
    """
    raw = cmd or ""
    if re.search(r"\bsed\b[^\n;|&]*['\"](?:[^'\"]*[\s;{])?w\s", raw):
        return False  # sed script with a w (write file) command
    cmd = HARMLESS_REDIRECT_RE.sub("", raw)
    # Quoted arguments (e.g. grep -E "a|b") must not be split as pipes.
    cmd = re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", "ARG", cmd)
    if not cmd.strip() or any(tok in cmd for tok in (">", "$(", "`", "<<")):
        return False
    for seg in re.split(r"\n|\|\||&&|;|\||&", cmd):
        words = seg.strip().split()
        if not words or words[0] == "cd":
            continue
        head = words[0]
        if head == "git":
            if not _git_read_only(words[1:]):
                return False
        elif head == "sed":
            if "-n" not in words or any(w.startswith("-i") for w in words):
                return False
        elif head == "find":
            if any(w in FIND_WRITE_FLAGS for w in words):
                return False
        elif head not in READ_ONLY_BASH:
            return False
    return True


def parse_run(path):
    """One subagent run: deduped per-model usage, tools, first/last message."""
    messages = {}  # message id -> {model, usage, order}
    tools, last_text, first_ts, handback = [], "", None, None
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
                    inp = block.get("input") or {}
                    tools.append((block.get("name"), inp.get("command")))
                    # A subagent's reply is the SubagentHandback message when
                    # it ends with one, not its last text block.
                    handback = inp.get("message") if block.get("name") == "SubagentHandback" else None
                elif block.get("type") == "text" and block.get("text"):
                    last_text = block["text"]
                    handback = None
    return {"messages": sorted(messages.values(), key=lambda m: m["order"]),
            "tools": tools, "last_text": handback if handback is not None else last_text,
            "first_ts": first_ts}


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
    """Subagent transcripts, including workflow runs nested under
    subagents/workflows/wf_*/. With `project`, only that project's dir."""
    pattern = os.path.join(projects_dir, "*", "*", "subagents", "**", "agent-*.jsonl")
    runs = glob.glob(pattern, recursive=True)
    if project:
        enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(project))
        base = os.path.realpath(projects_dir)
        runs = [r for r in runs
                if os.path.relpath(os.path.realpath(r), base).split(os.sep)[0] == enc]
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
            v = re.sub(r"\s+#.*$", "", v.strip())
            out[k.strip()] = v.strip().strip("'\"")
    return out


def _enabled_plugins(config_dir, project):
    """enabledPlugins from user settings, overridden by project settings."""
    enabled = {}
    paths = [os.path.join(config_dir, "settings.json")]
    if project:
        paths += [os.path.join(project, ".claude", "settings.json"),
                  os.path.join(project, ".claude", "settings.local.json")]
    for p in paths:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                enabled.update(json.load(f).get("enabledPlugins") or {})
    return enabled


def _active_install(entries, project):
    """The manifest entry that applies here: a project-scoped install for
    this project wins, else the user-scoped one. Other projects' installs
    are ignored."""
    proj = os.path.realpath(project) if project else None
    user = None
    for e in entries or []:
        if not (e or {}).get("installPath"):
            continue
        if e.get("scope") == "project":
            if proj and e.get("projectPath") and os.path.realpath(e["projectPath"]) == proj:
                return e
        else:
            user = user or e
    return user


def agent_inventory(config_dir, project=None):
    """Agent definitions: {name: {source, path, model}} (model None = inherits).

    Plugin agents come only from enabled plugins, at the install that applies
    to `project`, keyed `plugin:name`.
    """
    dirs = [("user", os.path.join(config_dir, "agents"))]
    if project:
        dirs.append(("project", os.path.join(project, ".claude", "agents")))
    manifest = os.path.join(config_dir, "plugins", "installed_plugins.json")
    if os.path.isfile(manifest):
        enabled = _enabled_plugins(config_dir, project)
        with open(manifest, encoding="utf-8") as f:
            for key, entries in (json.load(f).get("plugins") or {}).items():
                if enabled.get(key) is not True:
                    continue
                entry = _active_install(entries, project)
                if entry:
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
        if cutoff:
            try:
                ts = datetime.fromisoformat((run["first_ts"] or "").replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
            if ts < cutoff:
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
        is_fork = agent_type == "fork" or meta.get("isFork")
        if not is_fork and fam in PREMIUM_FAMILIES and priced_all and read_only_run(run["tools"]) and len(run["last_text"]) <= SHORT_REPLY_CHARS:
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
        # Spend is keyed by the agentType a run recorded: bare names for user
        # and project agents, plugin:name for plugin agents. No cross-matching.
        key = name
        cost = spend.get(key, 0.0)
        models = ", ".join(f"{m} x{n}" for m, n in sorted(mix.get(key, []), key=lambda x: -x[1]))
        out.append({"type": "unpinned_agent", "agent": name, "path": a["path"], "spend": cost,
                    "model_mix": mix.get(key, []), "severity": "MEDIUM" if cost > 0 else "LOW",
                    "message": (f"`{name}` has no `model:` pin, so its model is whatever each caller or the session picks"
                                + (f"; measured spend ${cost:,.2f} across {models}." if cost > 0 else "; no measured runs."))})
    out.sort(key=lambda f: -f["spend"])
    return out


TIER_RE = re.compile(r"\b(haiku|sonnet|opus|fable)\b", re.IGNORECASE)
NEGATION_RE = re.compile(r"\b(never|not|don't|dont|avoid|no)\b", re.IGNORECASE)
FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")


def _names_agent(line, name):
    """The agent is named in backticks, or next to the word agent/subagent,
    so common words like "explore" in prose do not count."""
    e = re.escape(name)
    return bool(re.search(r"`" + e + r"`", line)
                or re.search(r"(?<![\w-])" + e + r"(?![\w-])\s+(sub)?agent\b", line, re.IGNORECASE)
                or re.search(r"\b(sub)?agent\s+`?" + e + r"(?![\w-])", line, re.IGNORECASE))


def prose_conflicts(instruction_paths, inventory):
    """Lines naming an agent and one model tier that its pin contradicts.

    Skips fenced code, negated lines, and lines naming several tiers (a
    routing table is ambiguous line by line). LOW until precision is shown.
    """
    out = []
    for p in instruction_paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        fence = None
        for n, line in enumerate(lines, 1):
            m = FENCE_LINE_RE.match(line)
            if m:
                fence = None if fence == m.group(1) else (fence or m.group(1))
                continue
            if fence or NEGATION_RE.search(line):
                continue
            tiers = {t.lower() for t in TIER_RE.findall(line)}
            if len(tiers) != 1:
                continue
            tier = tiers.pop()
            for name, a in inventory.items():
                if not _names_agent(line, name):
                    continue
                pinned = (a["model"] or "").lower()
                if tier in pinned:
                    continue
                if a["model"]:
                    detail = f"but its definition pins `model: {a['model']}`"
                else:
                    detail = "but it is unpinned, so it runs on whatever model the caller or session picks"
                out.append({"type": "delegation_prose_conflict", "severity": "LOW", "file": p, "line": n,
                            "agent": name,
                            "message": (f"Line asks for `{name}` on {tier}, {detail}. Prose does not change "
                                        f"the model; set `model:` in {a['path']}.")})
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
