#!/usr/bin/env python3
"""deep-recon: deterministic read-only fact-gathering for /moltbloat:audit --deep.

Emits a FACTS document (markdown, or JSON with --json) — the shared ground truth
handed to every deep-audit subagent. Stdlib only.
Usage: deep-recon.py [CONFIG_DIR] [--json]; CONFIG_DIR defaults to $CLAUDE_CONFIG_DIR
then ~/.claude. State file (.claude.json) found in $HOME or inside CONFIG_DIR (fixtures).
"""
import json
import os
import re
import subprocess
import sys

def run(argv):
    """Run a command without a shell (paths are user input — no injection surface)."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:
        return f"<error: {e}>"


def du_mb(path):
    out = run(["du", "-sm", path])
    first = out.split("\t")[0] if out else ""
    return int(first) if first.isdigit() else out


def load_json(path):
    with open(path) as f:
        return json.load(f)


def collect(config_dir, state_path):
    facts = {"config_dir": config_dir, "state_file": state_path, "errors": []}

    def section(name, fn):
        try:
            facts[name] = fn()
        except Exception as e:
            facts["errors"].append(f"{name}: {e}")
            facts[name] = None

    def du_top():
        entries = []
        for e in os.listdir(config_dir):
            p = os.path.join(config_dir, e)
            if os.path.isdir(p):
                entries.append((du_mb(p), e))
        entries.sort(key=lambda x: -(x[0] if isinstance(x[0], int) else 0))
        return {"total_mb": du_mb(config_dir),
                "top": [f"{mb}M\t{name}" for mb, name in entries[:12]]}

    section("disk", du_top)

    def injected_files():
        # Files loaded into every session: CLAUDE.md + rules tree
        out = []
        for rel in ["CLAUDE.md", "AGENTS.md"]:
            p = os.path.join(config_dir, rel)
            if os.path.isfile(p):
                out.append({"file": rel, "bytes": os.path.getsize(p)})
        rules = os.path.join(config_dir, "rules")
        if os.path.isdir(rules):
            for root, _, files in os.walk(rules):
                for f in files:
                    if f.endswith(".md"):
                        p = os.path.join(root, f)
                        out.append({"file": os.path.relpath(p, config_dir), "bytes": os.path.getsize(p)})
        out.append({"file": "TOTAL", "bytes": sum(x["bytes"] for x in out)})
        return out

    section("injected_files", injected_files)

    def settings():
        p = os.path.join(config_dir, "settings.json")
        if not os.path.isfile(p):
            return {"missing": True}
        d = load_json(p)
        allow = (d.get("permissions") or {}).get("allow") or []
        # one-off heuristic: line-number seds, pids, literal exit-echo, tmp scripts
        oneoff = [a for a in allow if re.search(
            r"(sed -i.*\d+s/|sed -n '\d|ps -p \d|echo \"?EXIT|\d{4,}|/tmp/|expect -c|pkill|awk 'NR)", a)]
        plugins = d.get("enabledPlugins") or {}
        hooks = d.get("hooks") or {}
        empty_hooks = [k for k, v in hooks.items() if isinstance(v, list) and not v]
        return {
            "permissions_allow_count": len(allow),
            "permissions_oneoff_suspects": oneoff[:20],
            "plugins_enabled": sorted(k for k, v in plugins.items() if v),
            "plugins_disabled": sorted(k for k, v in plugins.items() if not v),
            "hook_events_configured": {k: len(v) for k, v in hooks.items() if v},
            "hook_events_empty": empty_hooks,
            "model": d.get("model"),
            "env": d.get("env"),
            "statusline": (d.get("statusLine") or {}).get("command"),
            "cleanupPeriodDays": d.get("cleanupPeriodDays"),
        }

    section("settings", settings)

    def dirs_inventory():
        inv = {}
        for kind in ["skills", "commands", "agents", "hooks"]:
            p = os.path.join(config_dir, kind)
            if not os.path.isdir(p):
                inv[kind] = None
                continue
            entries = sorted(os.listdir(p))
            entries = [e for e in entries if not e.startswith(".")]
            inv[kind] = {"count": len(entries), "names": entries[:80]}
        return inv

    section("local_inventory", dirs_inventory)

    def phantom_refs():
        """Names referenced in CLAUDE.md/rules/commands that don't exist in agents/ or as scripts."""
        agents_dir = os.path.join(config_dir, "agents")
        existing_agents = set()
        if os.path.isdir(agents_dir):
            existing_agents = {os.path.splitext(f)[0] for f in os.listdir(agents_dir)}
        hits = []
        scan = []
        for rel in ["CLAUDE.md"]:
            p = os.path.join(config_dir, rel)
            if os.path.isfile(p):
                scan.append(p)
        for sub in ["rules", "commands", "skills"]:
            d = os.path.join(config_dir, sub)
            if os.path.isdir(d):
                for root, _, files in os.walk(d):
                    scan.extend(os.path.join(root, f) for f in files if f.endswith(".md"))
        agent_pat = re.compile(r"`([a-z][a-z0-9-]{2,30})`\s+agent|\*\*([a-z][a-z0-9-]{2,30})\*\*\s+agent", re.I)
        script_pat = re.compile(r"(?:node|python3?|bash|sh)\s+((?:[.~/][^\s`\"')]+)?scripts/[^\s`\"')]+)")
        for p in scan:
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in agent_pat.finditer(text):
                name = (m.group(1) or m.group(2) or "").lower()
                if name and name not in existing_agents:
                    hits.append({"file": os.path.relpath(p, config_dir), "missing_agent": name})
            for m in script_pat.finditer(text):
                sp = os.path.expanduser(m.group(1))
                candidates = [sp, os.path.join(config_dir, sp), os.path.join(os.path.dirname(p), sp)]
                if not any(os.path.exists(c) for c in candidates):
                    hits.append({"file": os.path.relpath(p, config_dir), "missing_script": m.group(1)})
        deduped = []
        for h in hits:
            if h not in deduped:
                deduped.append(h)
        return deduped[:40]

    section("phantom_refs", phantom_refs)

    def state():
        if not os.path.isfile(state_path):
            return {"missing": True}
        d = load_json(state_path)
        gm = d.get("mcpServers") or {}
        projects = d.get("projects") or {}
        proj_servers = {}
        dead_projects = []
        for path, v in projects.items():
            ms = (v or {}).get("mcpServers") or {}
            if ms:
                proj_servers[path] = sorted(ms.keys())
            if not os.path.isdir(path):
                dead_projects.append(path)
        # duplicate server names across scopes
        seen = {name: ["(global)"] for name in gm}
        for path, names in proj_servers.items():
            for n in names:
                seen.setdefault(n, []).append(path)
        dupes = {n: scopes for n, scopes in seen.items() if len(scopes) > 1}
        usage = d.get("skillUsage") or {}

        def count(v):
            return v.get("usageCount", 0) if isinstance(v, dict) else (v if isinstance(v, int) else 0)

        ranked = sorted(((k, count(v)) for k, v in usage.items()), key=lambda x: -x[1])
        return {
            "global_mcp_servers": sorted(gm.keys()),
            "project_mcp_servers": proj_servers,
            "duplicate_server_names": dupes,
            "project_count": len(projects),
            "dead_project_paths": dead_projects[:20],
            "skill_usage_top": ranked[:15],
            "skill_usage_zero_or_one": [k for k, c in ranked if c <= 1][:40],
            "skill_usage_tracked": len(ranked),
        }

    section("state", state)

    def plugin_surface():
        cache = os.path.join(config_dir, "plugins", "cache")
        if not os.path.isdir(cache):
            return None
        out = []
        for market in sorted(os.listdir(cache)):
            mdir = os.path.join(cache, market)
            if not os.path.isdir(mdir):
                continue
            for plugin in sorted(os.listdir(mdir)):
                pdir = os.path.join(mdir, plugin)
                if not os.path.isdir(pdir):
                    continue
                versions = [v for v in os.listdir(pdir) if os.path.isdir(os.path.join(pdir, v))]
                skills = commands = agents = 0
                for v in versions:
                    vd = os.path.join(pdir, v)
                    sd = os.path.join(vd, "skills")
                    cd = os.path.join(vd, "commands")
                    ad = os.path.join(vd, "agents")
                    skills = max(skills, len(os.listdir(sd))) if os.path.isdir(sd) else skills
                    commands = max(commands, len(os.listdir(cd))) if os.path.isdir(cd) else commands
                    agents = max(agents, len(os.listdir(ad))) if os.path.isdir(ad) else agents
                out.append({"plugin": f"{plugin}@{market}", "versions_cached": len(versions),
                            "skills": skills, "commands": commands, "agents": agents})
        return sorted(out, key=lambda x: -(x["skills"] + x["commands"]))[:40]

    section("plugin_surface", plugin_surface)

    def claude_ai_connectors():
        # claude.ai connectors never touch local config; only transcripts see them.
        # Reuse connector-overlap.py so the matching logic lives in one place.
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "connector-overlap.py")
        projects_dir = os.path.join(config_dir, "projects")
        if not os.path.isdir(projects_dir) or not os.path.isfile(script):
            return None
        out = run([sys.executable, script, projects_dir, "--json"])
        try:
            return json.loads(out)
        except (json.JSONDecodeError, ValueError):
            return {"error": out[:500]}

    section("claude_ai_connectors", claude_ai_connectors)

    def memory_systems():
        out = {}
        proj = os.path.join(config_dir, "projects")
        mem_dirs = []
        if os.path.isdir(proj):
            for d in os.listdir(proj):
                md = os.path.join(proj, d, "memory")
                if os.path.isdir(md) and os.listdir(md):
                    mem_dirs.append({"project": d, "files": len(os.listdir(md))})
        out["native_memory_dirs"] = mem_dirs[:15]
        home = os.path.expanduser("~")
        for alt, label in [(os.path.join(home, ".claude-mem"), "claude-mem"),
                           (os.path.join(config_dir, "sessions"), "sessions_dir")]:
            if os.path.isdir(alt):
                out[label] = {"present": True, "size_mb": du_mb(alt)}
        loose = [f for f in os.listdir(config_dir)
                 if f.endswith(".md") and re.search(r"learn|memory|notes", f, re.I)]
        out["loose_knowledge_files"] = loose
        return out

    section("memory_systems", memory_systems)
    return facts


def to_markdown(facts):
    lines = ["# DEEP-RECON FACTS", f"Config dir: {facts['config_dir']}", ""]
    for key in ["disk", "injected_files", "settings", "local_inventory", "phantom_refs",
                "state", "plugin_surface", "claude_ai_connectors", "memory_systems"]:
        lines.append(f"## {key}")
        lines.append("```json")
        lines.append(json.dumps(facts.get(key), indent=1, default=str))
        lines.append("```")
        lines.append("")
    if facts["errors"]:
        lines.append(f"## recon errors\n{json.dumps(facts['errors'])}")
    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    config_dir = os.path.expanduser(args[0] if args else os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"))
    if not os.path.isdir(config_dir):
        print(f"ERROR: config dir not found: {config_dir}", file=sys.stderr)
        sys.exit(1)
    state_candidates = [os.path.join(os.path.expanduser("~"), ".claude.json"),
                        os.path.join(config_dir, ".claude.json")]
    if os.path.realpath(config_dir) != os.path.realpath(os.path.expanduser("~/.claude")):
        state_candidates.reverse()  # fixture layout: prefer sibling state file
    state_path = next((p for p in state_candidates if os.path.isfile(p)), state_candidates[0])
    facts = collect(config_dir, state_path)
    print(json.dumps(facts, indent=1, default=str) if as_json else to_markdown(facts))


if __name__ == "__main__":
    main()
