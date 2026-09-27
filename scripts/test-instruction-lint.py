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
        m = il.lint_files([misc], byte_budget=50, measured={os.path.realpath(misc): (1234, 7)})
        bb = [x for x in m["findings"] if x["type"] == "instruction_byte_budget"][0]
        _assert(bb["measured_tokens"] == 1234 and "~1,234 tokens per session (median of 7 sessions)" in bb["message"],
                "byte budget finding reports ledger-measured tokens")
        import json as _json
        lj = write(d, "ledger.json", _json.dumps({"sources": {"instructions": {"files": [
            {"path": misc, "median_tokens": 99, "samples": 2}]}}}))
        import contextlib as _cl
        import io as _io
        buf = _io.StringIO()
        with _cl.redirect_stdout(buf):
            code = il.main(["x", misc, "--byte-budget", "50", "--ledger-json", lj, "--json"])
        got = [x for x in _json.loads(buf.getvalue())["findings"] if x["type"] == "instruction_byte_budget"][0]
        _assert(code == 0 and got["measured_tokens"] == 99, "--ledger-json wires measured tokens through the CLI")
        _assert(il.main(["x", misc, "--ledger-json", os.path.join(d, "nope.json")]) == 1, "missing ledger file -> 1")

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

        print("Test: rewrite removes markers and exact duplicate sections only")
        doc = write(d, "doc.md", "<!-- imported-from: x -->\n# Top\n\nIMPORTANT: you MUST run `MUST_KEEP` via https://x.io/MUST.\n"
                    "Set the header to <YOUR_API_TOKEN> first. See docs/IMPORTANT.md.\n\n"
                    "```\nNEVER touch\n\n\nkeep blanks\n```\n\n" + WRAP_A + "\n" + WRAP_A)
        new = il.rewrite(il._read(doc))
        _assert("imported-from" not in new, "marker removed")
        _assert(new.count("## Wrap") == 1, "exact duplicate section removed, first kept")
        _assert("IMPORTANT: you MUST run `MUST_KEEP` via https://x.io/MUST." in new, "emphasis, code and URL untouched")
        _assert("<YOUR_API_TOKEN>" in new and "docs/IMPORTANT.md" in new, "placeholders and paths untouched")
        _assert("NEVER touch\n\n\nkeep blanks" in new, "blank lines inside a fence untouched")
        code, out = il.suggest_rewrite(doc)
        _assert(code == 0 and out.startswith("---"), "suggest_rewrite returns a unified diff")
        again = write(d, "again.md", new)
        _assert(il.suggest_rewrite(again) == (0, f"No rewrite suggested for {again}."), "rewrite is idempotent")

        print("Test: rewrite respects the heading hierarchy")
        mono = ("# Repo\n\n## web\n\n### Commands\n\n- pnpm dev\n- pnpm test\n\n"
                "## api\n\n### Commands\n\n- pnpm dev\n- pnpm test\n")
        _assert(il.rewrite(mono) == mono, "same subsection under different parents is kept")
        reparent = ("## Setup\n\nInstall deps\nRun build\n\n### Web\n\nweb one\nweb two\n\n"
                    "## Setup\n\nInstall deps\nRun build\n\n### API\n\napi one\napi two\n")
        _assert(il.rewrite(reparent) == reparent, "duplicate parent with different children is kept")
        whole = WRAP_A + "\n### Detail\n\nd one\nd two\n\n" + WRAP_A + "\n### Detail\n\nd one\nd two\n"
        out_whole = il.rewrite(whole)
        _assert(out_whole.count("## Wrap") == 1 and out_whole.count("### Detail") == 1,
                "identical subtree removed with its children")

        print("Test: diff applies with patch, including files without a final newline")
        import shutil
        import subprocess
        if shutil.which("patch"):
            for name, tail in (("nl.md", "\n"), ("nonl.md", "")):
                src = write(d, name, "<!-- imported-from: x -->\n# T\n\nbody one\nbody two" + tail)
                code, diff = il.suggest_rewrite(src)
                expected = il.rewrite(il._read(src))
                res = subprocess.run(["patch", "-s", src], input=diff, text=True, capture_output=True)
                _assert(res.returncode == 0 and il._read(src) == expected, f"patch applies the diff ({name})")
        else:
            print("  skip patch not installed")

        print("Test: refusals")
        crlf = write(d, "crlf.md", "<!-- imported-from: x -->\r\n# T\r\n")
        _assert(il.suggest_rewrite(crlf)[0] == 3, "CRLF file refused")
        txt = write(d, "rules.txt", "<!-- imported-from: x -->\n")
        _assert(il.suggest_rewrite(txt)[0] == 3, "non-Markdown file refused")
        orig_rewrite = il.rewrite
        il.rewrite = lambda text: text.replace("`MUST_KEEP`", "").replace("docs/IMPORTANT.md", "")
        code, out = il.suggest_rewrite(doc)
        il.rewrite = orig_rewrite
        _assert(code == 3 and "preserved content" in out, "losing inline code or a path is refused with exit 3")

        print("Test: main exit codes")
        _assert(il.main(["x"]) == 2, "no files -> 2")
        _assert(il.main(["x", os.path.join(d, "nope.md")]) == 1, "missing file -> 1")
        _assert(il.main(["x", a, "--byte-budget", "abc"]) == 2, "bad number -> 2")
        _assert(il.main(["x", "--suggest-rewrite", os.path.join(d, "nope.md")]) == 1, "rewrite missing file -> 1")
        _assert(il.main(["x", "--suggest-rewrite", a, "--also", c]) == 2, "--also no longer accepted -> 2")
        _assert(il.main(["x", a, c, "--json"]) == 0, "json run ok")
    print("All instruction-lint tests passed.")


if __name__ == "__main__":
    run()
