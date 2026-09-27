#!/usr/bin/env python3
"""Tests for instruction-lint.py: instruction-file checks and safe rewrites.

Run: python3 scripts/test-instruction-lint.py
"""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("instruction_lint", os.path.join(HERE, "instruction-lint.py"))
il = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(il)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def types(result):
    return [f["type"] for f in result["findings"]]


WRAP_A = "## Wrap\n\n1. Commit work\n2. Push branch\n3. Open PR\n4. Merge when green\n5. Clean up lanes\n"
WRAP_B = "# Wrap\n\n1. Commit work\n2. Push branch\n3. Open PR with template\n4. Merge when green\n5. Clean up lanes and branches\n"


def run():
    with tempfile.TemporaryDirectory() as d:
        print("Test: emphasis density counts prose only")
        loud = write(d, "loud.md", "# Rules\n\nYou MUST do X.\nNEVER do Y.\n<EXTREMELY_IMPORTANT>\nALWAYS check.\n"
                     "```\nMUST in code\n```\n> NEVER in a quote\nUse `MUST_FLAG` here.\n")
        r = il.lint_files([loud])
        f = [x for x in r["findings"] if x["type"] == "emphasis_density"]
        _assert(len(f) == 1 and f[0]["severity"] == "MEDIUM", "loud file flagged MEDIUM")
        _assert("4 emphatic" in f[0]["message"], "fence, blockquote, and inline code excluded (4 hits)")
        calm = write(d, "calm.md", "# Rules\n\n" + "Use plain words here.\n" * 40 + "You MUST do X.\n")
        _assert("emphasis_density" not in types(il.lint_files([calm])), "one hit in 41 lines is under threshold")

        print("Test: placeholders, import residue, byte budget")
        misc = write(d, "misc.md", "TODO: finish\nsee `TODO` in code\nnothing todo here\n<!-- imported-from: cursor:x -->\nnot implemented yet\n")
        r = il.lint_files([misc], byte_budget=50)
        t = types(r)
        _assert(t.count("placeholder_marker") == 2, "TODO and 'not implemented' flagged; inline code and lowercase ignored")
        _assert("import_residue" in t, "import marker flagged")
        _assert("instruction_byte_budget" in t, "over byte budget flagged")

        print("Test: duplicate vs drifted sections, across files")
        a = write(d, "a.md", WRAP_A)
        b = write(d, "b.md", WRAP_A.replace("## Wrap", "### Wrap"))
        c = write(d, "c.md", WRAP_B)
        r = il.lint_files([a, b])
        _assert(types(r) == ["duplicate_section"], "identical bodies across files: duplicate")
        r = il.lint_files([a, c])
        dr = [x for x in r["findings"] if x["type"] == "drifted_duplicate"]
        _assert(len(dr) == 1 and dr[0]["severity"] == "HIGH", "same heading, diverged body: drifted HIGH")
        _assert(any("template" in line for line in dr[0]["differences"]), "differing lines reported")
        short = write(d, "short.md", "## One\nalpha beta\ngamma delta\n## Two\nalpha beta\ngamma delta\n")
        _assert("duplicate_section" not in types(il.lint_files([short])), "short sections with different headings not paired")

        print("Test: rewrite drops exact duplicates and markers, softens emphasis, keeps code")
        doc = write(d, "doc.md", "<!-- imported-from: x -->\n# Top\n\nIMPORTANT: you MUST run `MUST_KEEP` via https://x.io/MUST.\n\n"
                    "```\nNEVER touch\n```\n\n" + WRAP_A + "\n" + WRAP_A)
        new = il.rewrite(il._read(doc))
        _assert("imported-from" not in new, "marker removed")
        _assert(new.count("## Wrap") == 1, "exact duplicate section removed, first kept")
        _assert("you must run `MUST_KEEP`" in new and "IMPORTANT:" not in new, "emphasis softened, inline code kept")
        _assert("https://x.io/MUST" in new and "NEVER touch" in new, "URL and fenced block untouched")
        code, out = il.suggest_rewrite(doc)
        _assert(code == 0 and out.startswith("---"), "suggest_rewrite returns a unified diff")
        again = write(d, "again.md", new)
        _assert(il.suggest_rewrite(again) == (0, f"No rewrite suggested for {again}."), "rewrite is idempotent")

        print("Test: --also removes a section duplicated in another file")
        other = write(d, "other.md", WRAP_A)
        _assert("## Wrap" not in il.rewrite(il._read(a), [il._read(other)]), "section already in --also file removed")

        print("Test: unsafe rewrite refused")
        orig_rewrite = il.rewrite
        il.rewrite = lambda text, other=(): text.replace("`MUST_KEEP`", "")
        code, out = il.suggest_rewrite(doc)
        il.rewrite = orig_rewrite
        _assert(code == 3 and "preserved content" in out, "dropping inline code is refused with exit 3")

        print("Test: main exit codes")
        _assert(il.main(["x"]) == 2, "no files -> 2")
        _assert(il.main(["x", os.path.join(d, "nope.md")]) == 1, "missing file -> 1")
        _assert(il.main(["x", a, "--byte-budget", "abc"]) == 2, "bad number -> 2")
        _assert(il.main(["x", "--suggest-rewrite", os.path.join(d, "nope.md")]) == 1, "rewrite missing file -> 1")
        _assert(il.main(["x", a, c, "--json"]) == 0, "json run ok")
    print("All instruction-lint tests passed.")


if __name__ == "__main__":
    run()
