#!/usr/bin/env python3
"""Tests for apply-instruction-change.py: guarded writes used by /moltbloat:clean.

Run: python3 scripts/test-apply-instruction-change.py
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("apply_change", os.path.join(HERE, "apply-instruction-change.py"))
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        f.write(text)
    return path


def read(path):
    with open(path, newline="") as f:
        return f.read()


def call(argv, home):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ac.main(["x"] + argv, home=home)
    return code, (json.loads(out.getvalue()) if code == 0 else None), err.getvalue()


SECTION = "## Wrap\n\n1. Commit\n2. Push\n3. Merge\n"


def run():
    with tempfile.TemporaryDirectory() as d:
        home = os.path.realpath(os.path.join(d, "home"))
        backups = os.path.join(d, "backups")
        doc = write(os.path.join(home, "proj", "CLAUDE.md"),
                    "<!-- imported-from: x -->\n# Top\n\nkeep `code` here\n\n" + SECTION + "\n" + SECTION)
        original = read(doc)

        print("Test: rewrite dry run shows a diff and writes nothing")
        code, res, _ = call(["rewrite", doc, "--dry-run"], home)
        _assert(code == 0 and res["changed"] and res["diff"].startswith("---"), "diff returned")
        _assert(read(doc) == original and "backup" not in res, "file untouched on dry run")

        print("Test: rewrite applies with a backup and a matching hash")
        code, res, _ = call(["rewrite", doc, "--expect-sha256", res["sha256"], "--backup-root", backups], home)
        _assert(code == 0 and res["applied"], "applied")
        _assert(read(res["backup"]) == original, "backup holds the original")
        _assert(res["backup"].startswith(backups) and res["backup"].endswith(os.path.join("proj", "CLAUDE.md")),
                "backup mirrors the absolute path under the backup root")
        new = read(doc)
        _assert(new.count("## Wrap") == 1 and "imported-from" not in new and "`code`" in new, "rewrite result correct")
        code, res2, _ = call(["rewrite", doc, "--dry-run"], home)
        _assert(not res2["changed"], "second rewrite is a no-op")

        print("Test: stale review hash is refused")
        code, _, err = call(["rewrite", doc, "--expect-sha256", "0" * 64], home)
        _assert(code == 3 and "changed since" in err, "hash mismatch -> 3")

        print("Test: drop-section removes one side of a drifted pair, checked by heading")
        drift = write(os.path.join(home, "proj", "AGENTS.md"),
                      "# Rules\n\n## Wrap\n\nv1 line\nv1 two\n\n### Sub\n\nsub body\n\n## Other\n\nkeep me\n")
        code, _, err = call(["drop-section", drift, "--line", "3", "--heading", "Nope"], home)
        _assert(code == 3 and "not heading" in err, "heading mismatch refused")
        code, _, err = call(["drop-section", drift, "--line", "4", "--heading", "Wrap"], home)
        _assert(code == 3 and "no section heading" in err, "line that is not a heading refused")
        code, res, _ = call(["drop-section", drift, "--line", "3", "--heading", "Wrap", "--backup-root", backups], home)
        after = read(drift)
        _assert(code == 0 and "v1 line" not in after and "sub body" not in after, "section and its subsection removed")
        _assert("## Other" in after and "keep me" in after and "# Rules" in after, "neighbors kept")

        print("Test: pin-model replaces or inserts model in frontmatter")
        agent = write(os.path.join(home, ".claude", "agents", "executor.md"),
                      "---\nname: executor\ndescription: builds\n---\nbody\n")
        code, res, _ = call(["pin-model", agent, "--model", "sonnet", "--backup-root", backups], home)
        _assert(code == 0 and read(agent) == "---\nname: executor\nmodel: sonnet\ndescription: builds\n---\nbody\n",
                "model inserted after name")
        code, res, _ = call(["pin-model", agent, "--model", "haiku", "--backup-root", backups], home)
        _assert("model: haiku" in read(agent) and read(agent).count("model:") == 1, "existing model replaced")
        code, _, err = call(["pin-model", agent, "--model", "gpt"], home)
        _assert(code == 2, "unknown model -> 2")
        nofm = write(os.path.join(home, ".claude", "agents", "bare.md"), "no frontmatter\n")
        _assert(call(["pin-model", nofm, "--model", "sonnet"], home)[0] == 3, "no frontmatter refused")

        print("Test: refusals")
        plug = write(os.path.join(home, ".claude", "plugins", "cache", "p", "1", "agents", "a.md"), "---\nname: a\n---\n")
        code, _, err = call(["pin-model", plug, "--model", "sonnet"], home)
        _assert(code == 3 and "plugin" in err, "plugin-owned file refused")
        _assert(read(plug) == "---\nname: a\n---\n", "plugin file untouched")
        txt = write(os.path.join(home, "proj", "rules.txt"), "x\n")
        _assert(call(["rewrite", txt], home)[0] == 3, "non-Markdown refused")
        crlf = write(os.path.join(home, "proj", "crlf.md"), "<!-- imported-from: x -->\r\n# T\r\n")
        _assert(call(["rewrite", crlf], home)[0] == 3, "CRLF refused")
        _assert(call(["rewrite", os.path.join(home, "nope.md")], home)[0] == 1, "missing file -> 1")
        _assert(call(["bogus", doc], home)[0] == 2, "unknown action -> 2")
        _assert(call(["drop-section", drift, "--line", "x", "--heading", "W"], home)[0] == 2, "bad --line -> 2")

        print("Test: file mode preserved")
        os.chmod(doc, 0o640)
        write(doc, read(doc) + "\n<!-- imported-from: y -->\n")
        os.chmod(doc, 0o640)
        call(["rewrite", doc, "--backup-root", backups], home)
        _assert(os.stat(doc).st_mode & 0o777 == 0o640, "mode kept after atomic replace")
    print("All apply-instruction-change tests passed.")


if __name__ == "__main__":
    run()
