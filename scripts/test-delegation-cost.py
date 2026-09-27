#!/usr/bin/env python3
"""Tests for delegation-cost.py: subagent spend from transcripts.

Run: python3 scripts/test-delegation-cost.py
"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("delegation_cost", os.path.join(HERE, "delegation-cost.py"))
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

RATES = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10},
}


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def close(a, b):
    return abs(a - b) < 1e-9


def assistant(mid, model, usage, content=(), ts="2026-09-20T10:00:00Z"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": model, "usage": usage, "content": list(content)}}


def usage(inp=0, write=0, read=0, out=0, w1h=0):
    return {"input_tokens": inp, "cache_creation_input_tokens": write, "cache_read_input_tokens": read,
            "output_tokens": out,
            "cache_creation": {"ephemeral_5m_input_tokens": write - w1h, "ephemeral_1h_input_tokens": w1h}}


def write_run(root, name, records, meta):
    d = os.path.join(root, "-Users-x-proj", "sess1", "subagents")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"agent-{name}.jsonl")
    with open(p, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    if meta is not None:
        with open(p[:-len(".jsonl")] + ".meta.json", "w") as f:
            f.write(meta if isinstance(meta, str) else json.dumps(meta))
    return p


def tool(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def run():
    print("Test: price() uses per-model rates and cache write TTLs")
    u = dc._flat_usage(usage(inp=1_000_000, write=1_000_000, read=1_000_000, out=1_000_000, w1h=500_000))
    cost = dc.price(u, RATES["claude-opus-5-5"])
    _assert(close(cost, 4 + 0.5 * 4 * 1.25 + 0.5 * 4 * 2.0 + 0.20 + 20), "input + 5m write + 1h write + read + output")
    _assert(dc.rates_for("claude-haiku-4-5-20251001", RATES) is RATES["claude-haiku-4-5"], "dated id matches prefix")
    _assert(dc.rates_for("claude-mystery-9", RATES) is None, "unknown model has no rate")
    _assert(dc.rates_for("claude-opus-5-5-7", RATES) is None and dc.rates_for("claude-sonnet-5-1", {"claude-sonnet-5": RATES["claude-sonnet-5"]}) is None,
            "a newer model sharing a prefix is unpriced, not guessed")

    print("Test: bash read-only classification")
    for cmd, want in (("grep -E \"a|b\" f | head", True), ("cd /x && git log -3", True), ("ls 2>/dev/null; wc -l f", True),
                      ("sed -n 1,5p f", True), ("sed -i s/a/b/ f", False), ("cat a > b", False),
                      ("echo $(whoami)", False), ("cd x && python3 t.py", False), ("git push", False),
                      ("ls\nrm -rf x", False), ("ls & rm x", False), ("find . -delete", False),
                      ("find . -exec rm {} \\;", False), ("find . -name x", True), ("git branch -D main", False),
                      ("git branch newb", False), ("git branch -a", True), ("sed -n 'w out' f", False),
                      ("git diff --output=x", False), ("git -C /x log --oneline", True), ("cat <<EOF", False)):
        _assert(dc._bash_read_only(cmd) is want, f"{cmd!r} -> {want}")

    with tempfile.TemporaryDirectory() as d:
        root = os.path.join(d, "projects")
        print("Test: repeated message ids are counted once (largest value per field)")
        p = write_run(root, "a", [
            assistant("m1", "claude-opus-5-5", usage(inp=10, write=1000, out=2)),
            assistant("m1", "claude-opus-5-5", usage(inp=10, write=1000, out=500),
                      [tool("Read", file_path="/x"), {"type": "text", "text": "short answer"}]),
            assistant("m2", "claude-opus-5-5", usage(inp=5, read=1000, out=100), [tool("Grep", pattern="x")]),
            assistant("m3", "<synthetic>", usage(out=0)),
        ], {"agentType": "explore", "model": "opus", "description": "find the thing"})
        r = dc.parse_run(p)
        _assert(len(r["messages"]) == 2, "two unique messages; synthetic skipped")

        print("Test: nested workflow runs are found; SubagentHandback message is the reply")
        wf = os.path.join(root, "-Users-x-proj", "sess1", "subagents", "workflows", "wf_1")
        os.makedirs(wf)
        with open(os.path.join(wf, "agent-w.jsonl"), "w") as f:
            f.write(json.dumps(assistant("w1", "claude-opus-5-5", usage(out=5), [
                {"type": "text", "text": "ok"}, tool("SubagentHandback", message="x" * 5000)])) + "\n")
        with open(os.path.join(wf, "agent-w.meta.json"), "w") as f:
            json.dump({"agentType": "workflow-subagent"}, f)
        _assert(any(p_.endswith("agent-w.jsonl") for p_ in dc.find_runs(root)), "workflow run found")
        _assert(len(dc.parse_run(os.path.join(wf, "agent-w.jsonl"))["last_text"]) == 5000, "handback message used as reply")
        _assert(r["messages"][0]["usage"]["output_tokens"] == 500, "streamed repeat keeps the final output count")

        print("Test: analyze groups spend, spin-up, and read-only premium candidates")
        write_run(root, "b", [
            assistant("n1", "claude-sonnet-5", usage(inp=100, write=2000, out=300), [tool("Edit", file_path="/x")]),
        ], {"agentType": "executor"})
        write_run(root, "c", [assistant("o1", "claude-mystery-9", usage(out=10))], {"agentType": "general-purpose"})
        write_run(root, "d", [assistant("q1", "claude-sonnet-5", usage(out=1))], "{not json")
        runs = dc.find_runs(root)
        res = dc.analyze(runs, RATES)
        groups = {(g["agent_type"], g["model"]): g for g in res["by_agent_type_model"]}
        a_cost = dc.price(dc._flat_usage(usage(inp=10, write=1000, out=500)), RATES["claude-opus-5-5"]) + \
            dc.price(dc._flat_usage(usage(inp=5, read=1000, out=100)), RATES["claude-opus-5-5"])
        _assert(close(groups[("explore", "claude-opus-5-5")]["cost"], a_cost), "explore run priced from deduped usage")
        _assert(groups[("executor", "claude-sonnet-5")]["runs"] == 1, "executor grouped by model")
        _assert("claude-mystery-9" in res["unpriced_models"], "unknown model reported unpriced, not guessed")
        _assert(any("unparseable" in e for e in res["errors"]), "malformed meta.json reported")
        _assert(groups[("unknown", "claude-sonnet-5")]["runs"] == 1, "run with bad meta still counted as unknown type")
        cands = res["mechanical_on_premium"]
        _assert(len(cands) == 1 and cands[0]["agent_type"] == "explore",
                "read-only short opus run is a candidate; long handback reply is not")
        alt = sum(dc.price(m["usage"], RATES["claude-sonnet-5"]) for m in dc.parse_run(p)["messages"])
        _assert(close(cands[0]["estimated_saving"], a_cost - alt), "saving = same tokens re-priced on sonnet, not zero")
        _assert(res["spin_up"]["executor"]["runs"] == 1, "spin-up recorded per agent type")

        print("Test: forks are never candidates; --project matches only that project's dir")
        fk = write_run(root, "f", [assistant("k1", "claude-opus-5-5", usage(out=1), [tool("Read", file_path="/x")])],
                       {"agentType": "fork", "isFork": True})
        _assert(not dc.analyze([fk], RATES)["mechanical_on_premium"], "fork excluded from candidates")
        sib = os.path.join(root, "-Users-x-proj2", "s", "subagents")
        os.makedirs(sib)
        with open(os.path.join(sib, "agent-s.jsonl"), "w") as f:
            f.write("")
        _assert(not any("proj2" in p_ for p_ in dc.find_runs(root, "/Users/x/proj")), "sibling project dir excluded")

        print("Test: --since filters by run start time")
        old = write_run(root, "e", [assistant("z1", "claude-sonnet-5", usage(out=5), ts="2020-01-01T00:00:00Z")],
                        {"agentType": "old"})
        recent = dc.analyze([old], RATES, since_days=30)
        _assert(recent["runs_scanned"] == 0, "old run excluded")

        print("Test: agent inventory, unpinned findings, prose conflicts")
        cfg = os.path.join(d, "cfg")
        os.makedirs(os.path.join(cfg, "agents"))
        for name, model in (("executor", None), ("explore", "haiku # cheap"), ("reviewer", "inherit")):
            fm = f"model: {model}\n" if model else ""
            with open(os.path.join(cfg, "agents", f"{name}.md"), "w") as f:
                f.write(f"---\nname: {name}\n{fm}---\nbody\n")
        inv = dc.agent_inventory(cfg)
        _assert(inv["explore"]["model"] == "haiku" and inv["executor"]["model"] is None,
                "pins read (inline comment stripped); missing = None")

        print("Test: plugin agents only from enabled plugins, at the install for this project")
        cache = os.path.join(d, "cache")
        for plug in ("on", "off", "other"):
            os.makedirs(os.path.join(cache, plug, "agents"))
            with open(os.path.join(cache, plug, "agents", "worker.md"), "w") as f:
                f.write("---\nname: worker\n---\n")
        os.makedirs(os.path.join(cfg, "plugins"))
        with open(os.path.join(cfg, "plugins", "installed_plugins.json"), "w") as f:
            json.dump({"plugins": {
                "on@m": [{"scope": "user", "installPath": os.path.join(cache, "on")}],
                "off@m": [{"scope": "user", "installPath": os.path.join(cache, "off")}],
                "other@m": [{"scope": "project", "projectPath": "/elsewhere", "installPath": os.path.join(cache, "other")}]}}, f)
        with open(os.path.join(cfg, "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {"on@m": True, "off@m": False, "other@m": True}}, f)
        inv = dc.agent_inventory(cfg, "/Users/x/proj")
        _assert("on:worker" in inv and "off:worker" not in inv, "disabled plugin agents excluded")
        _assert("other:worker" not in inv, "another project's install excluded")
        _assert(inv["reviewer"]["model"] is None, "model: inherit treated as unpinned")
        un = dc.unpinned_findings(res, inv)
        by = {f["agent"]: f for f in un}
        _assert(by["executor"]["severity"] == "MEDIUM" and by["executor"]["spend"] > 0, "unpinned with spend is MEDIUM")
        _assert(by["reviewer"]["severity"] == "LOW", "unpinned with no runs is LOW")
        _assert("explore" not in by, "pinned agent not flagged")
        _assert(by["on:worker"]["spend"] == 0, "plugin agent does not borrow a same-named agent's spend")
        doc = os.path.join(d, "CLAUDE.md")
        with open(doc, "w") as f:
            f.write("Use the `explore` agent on haiku.\nRun the `executor` agent on sonnet.\n"
                    "Run the explore step first, then use Opus to write the plan.\n"
                    "Never send `executor` work to Haiku.\n```\n`executor` on opus\n```\n"
                    "Route: haiku for `explore`, sonnet for `executor`.\n")
        conf = dc.prose_conflicts([doc], inv)
        _assert([(c["agent"], c["line"]) for c in conf] == [("executor", 2)],
                "only line 2 flags: matching pin, bare common word, negation, fence, and routing table skipped")
        _assert(conf[0]["severity"] == "LOW" and "unpinned" in conf[0]["message"], "LOW, and says unpinned")

        print("Test: main exit codes")
        rj = os.path.join(d, "rates.json")
        with open(rj, "w") as f:
            json.dump(RATES, f)
        _assert(dc.main(["x", "--projects-dir", os.path.join(d, "nope")]) == 1, "missing projects dir -> 1")
        _assert(dc.main(["x", "--since", "soon"]) == 2, "bad --since -> 2")
        _assert(dc.main(["x", "--projects-dir", root, "--rates-json", rj, "--instructions", "/nope.md"]) == 1,
                "missing instruction file -> 1")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            code = dc.main(["x", "--projects-dir", root, "--config-dir", cfg, "--rates-json", rj, "--since", "all",
                            "--instructions", doc, "--json"])
        _assert(code == 0, "json run ok")
    print("All delegation-cost tests passed.")


if __name__ == "__main__":
    run()
