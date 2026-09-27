#!/usr/bin/env python3
"""Tests for instruction-files.py: which instruction files load, and how.

Run: python3 scripts/test-instruction-files.py
"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("instruction_files", os.path.join(HERE, "instruction-files.py"))
inf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inf)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def by_path(result):
    return {f["path"]: f for f in result["files"]}


def run():
    with tempfile.TemporaryDirectory() as d:
        home = os.path.realpath(os.path.join(d, "home"))
        proj = os.path.join(home, "work", "proj")
        write(os.path.join(home, ".claude", "CLAUDE.md"), "user rules\n@~/shared/common.md\n")
        write(os.path.join(home, "shared", "common.md"), "common\n@./deeper.md\n")
        write(os.path.join(home, "shared", "deeper.md"), "deeper\n@./common.md\n")
        write(os.path.join(home, "work", "CLAUDE.md"), "ancestor\n")
        write(os.path.join(proj, "CLAUDE.md"), "project\n@AGENTS.md\n`@not/an/import.md`\n```\n@fenced.md\n```\nmail me@example.com\n@scope/pkg\n@./missing.md\nSee @./guide.md.\n")
        write(os.path.join(proj, "guide.md"), "guide\n")
        write(os.path.join(home, "CLAUDE.md"), "home-level\n")
        write(os.path.join(proj, "sub", "local-import.md"), "lazy child\n")
        write(os.path.join(proj, "AGENTS.md"), "agents\n")
        write(os.path.join(proj, "CLAUDE.local.md"), "local\n")
        write(os.path.join(proj, ".claude", "rules", "always.md"), "rule\n")
        write(os.path.join(proj, ".claude", "rules", "ts.md"), "---\npaths:\n  - \"**/*.ts\"\n---\nts rule\n")
        write(os.path.join(proj, "sub", "CLAUDE.md"), "nested\n@./local-import.md\n")
        write(os.path.join(proj, ".claude", "rules", "broken.md"), "---\npaths: x\nno close\n")
        write(os.path.join(proj, "node_modules", "x", "CLAUDE.md"), "vendored\n")
        write(inf.automem_path(home, proj), "- memory index\n")

        print("Test: collect labels each file with its load mode")
        r = inf.collect(proj, home)
        f = by_path(r)
        real = os.path.realpath(proj)
        _assert(f[os.path.join(home, ".claude", "CLAUDE.md")]["load_mode"] == "always", "user CLAUDE.md always")
        _assert(f[os.path.join(home, "work", "CLAUDE.md")]["kind"] == "ancestor", "ancestor CLAUDE.md found")
        _assert(f[os.path.join(real, "CLAUDE.local.md")]["kind"] == "local", "CLAUDE.local.md found")
        _assert(f[os.path.join(real, "AGENTS.md")]["load_mode"] == "always", "AGENTS.md always (per docs)")
        _assert(f[os.path.join(real, ".claude", "rules", "always.md")]["load_mode"] == "always", "rule without paths: always")
        _assert(f[os.path.join(real, ".claude", "rules", "ts.md")]["load_mode"] == "path-scoped", "rule with paths: path-scoped")
        _assert(f[os.path.join(real, "sub", "CLAUDE.md")]["load_mode"] == "lazy", "nested CLAUDE.md lazy")
        _assert(not any("node_modules" in p for p in f), "node_modules skipped")
        _assert(f[inf.automem_path(home, proj)]["kind"] == "automem", "auto memory MEMORY.md found")
        _assert(f[os.path.join(home, "CLAUDE.md")]["kind"] == "ancestor", "~/CLAUDE.md read as an ancestor")
        _assert(any("broken.md" in w for w in r["warnings"]), "unclosed frontmatter warned")

        print("Test: @imports resolve up to the hop limit, skip code and cycles")
        imports = [x for x in r["files"] if x["load_mode"] == "imported"]
        names = sorted(os.path.basename(x["path"]) for x in imports)
        _assert(names == ["common.md", "deeper.md", "guide.md", "local-import.md"],
                "~ import, relative import, and sentence-final import followed; cycle not repeated")
        modes = {os.path.basename(x["path"]): x["parent_load_mode"] for x in imports}
        _assert(modes["local-import.md"] == "lazy" and modes["guide.md"] == "always", "imports carry the parent's load mode")
        _assert(all("/./" not in x["path"] for x in imports), "import paths normalized")
        _assert(sum(1 for p in f if p.endswith("AGENTS.md")) == 1, "@AGENTS.md import does not list AGENTS.md twice")
        _assert(not any("fenced.md" in p or "an/import.md" in p for p in f), "imports inside fences and inline code ignored")
        tokens = [u["token"] for u in r["unresolved_imports"]]
        _assert(tokens == ["@./missing.md"], "missing path-like import reported; @scope/pkg and emails ignored")

        print("Test: import hop limit")
        chain = os.path.join(d, "chain")
        for k in range(6):
            write(os.path.join(chain, f"f{k}.md"), f"@./f{k + 1}.md\n")
        write(os.path.join(chain, "f6.md"), "end\n")
        imported, _ = inf.resolve_imports([(os.path.join(chain, "f0.md"), "always")], home)
        _assert(len(imported) == inf.MAX_IMPORT_HOPS, "stops after 4 hops")

        print("Test: project dir encoding matches Claude Code's (literal names)")
        _assert(inf.encode_project_dir("/Users/james/.claude") == "-Users-james--claude", "dot becomes dash")
        _assert(inf.encode_project_dir("/a/b_c/d-e") == "-a-b-c-d-e", "underscore becomes dash")

        print("Test: a git worktree shares the main repo's memory dir")
        import subprocess
        repo = os.path.realpath(os.path.join(d, "repo"))
        os.makedirs(repo)
        git = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
        git("init", "-q")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        wt = os.path.realpath(os.path.join(d, "repo-lanes", "feat-x"))
        git("worktree", "add", "-q", wt)
        _assert(inf.memory_root(wt) == repo, "worktree memory root is the main repo")
        _assert(inf.memory_root(repo) == repo, "main checkout memory root is itself")
        _assert(inf.memory_root(chain) == os.path.realpath(chain), "non-git dir is its own root")

        print("Test: symlinked AGENTS.md -> CLAUDE.md listed once")
        sym = os.path.join(d, "symproj")
        write(os.path.join(sym, "CLAUDE.md"), "shared\n")
        os.symlink("CLAUDE.md", os.path.join(sym, "AGENTS.md"))
        paths = [x["path"] for x in inf.collect(sym, home)["files"] if x["path"].startswith(os.path.realpath(sym))]
        _assert(len(paths) == 1, "same file under two names listed once")

        print("Test: mark_observed against a ledger")
        ledger = {"sources": {"instructions": {"samples": 3, "files": [
            {"path": os.path.join(home, ".claude", "CLAUDE.md")}]}}}
        inf.mark_observed(r, ledger)
        f = by_path(r)
        _assert(f[os.path.join(home, ".claude", "CLAUDE.md")]["observed"] is True, "seen file marked observed")
        _assert(f[os.path.join(real, "AGENTS.md")]["observed"] is False, "always file never seen marked False")
        _assert(f[os.path.join(real, "sub", "CLAUDE.md")]["observed"] is None, "lazy file not judged")
        r2 = inf.mark_observed(inf.collect(proj, home), {"sources": {}})
        _assert(all(x["observed"] is None for x in r2["files"]), "no ledger samples: nothing judged")

        print("Test: main exit codes")
        _assert(inf.main(["x", "--project", os.path.join(d, "nope")]) == 2, "missing project dir -> 2")
        _assert(inf.main(["x", "--bogus"]) == 2, "unknown argument -> 2")
        lj = os.path.join(d, "ledger.json")
        with open(lj, "w") as fh:
            json.dump(ledger, fh)
        _assert(inf.main(["x", "--project", proj, "--home", home, "--ledger-json", lj, "--json"]) == 0, "json run ok")
    print("All instruction-files tests passed.")


if __name__ == "__main__":
    run()
