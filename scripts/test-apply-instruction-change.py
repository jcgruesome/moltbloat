#!/usr/bin/env python3
"""Tests for apply-instruction-change.py: guarded writes used by /moltbloat:clean.

Run: python3 scripts/test-apply-instruction-change.py
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("apply_change", os.path.join(HERE, "apply-instruction-change.py"))
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)
os.environ.pop("CLAUDE_CONFIG_DIR", None)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(text)
    return path


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return f.read()


def call(argv, home):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ac.main(["x"] + argv, home=home)
    return code, (json.loads(out.getvalue()) if code == 0 else None), err.getvalue()


def apply(argv, path, home, backups):
    """Dry run, then apply with the reviewed hash (the SKILL's flow)."""
    code, res, err = call(argv + ["--dry-run"], home)
    if code != 0:
        return code, res, err
    return call(argv + ["--expect-sha256", res["sha256"], "--backup-root", backups], home)


SECTION = "## Wrap\n\n1. Commit\n2. Push\n3. Merge\n"


def run():
    with tempfile.TemporaryDirectory() as d:
        home = os.path.realpath(os.path.join(d, "home"))
        backups = os.path.join(d, "backups")
        doc = write(os.path.join(home, "proj", "CLAUDE.md"),
                    "<!-- imported-from: x -->\n# Top\n\nkeep `code` here\n\n" + SECTION + "\n" + SECTION)
        original = read(doc)

        print("Test: dry run shows a diff and writes nothing; writes need the reviewed hash")
        code, res, _ = call(["rewrite", doc, "--dry-run"], home)
        _assert(code == 0 and res["changed"] and res["diff"].startswith("---"), "diff returned")
        _assert(read(doc) == original, "file untouched on dry run")
        code, _, err = call(["rewrite", doc], home)
        _assert(code == 2 and "expect-sha256" in err, "write without --expect-sha256 -> 2")
        code, _, err = call(["rewrite", doc, "--expect-sha256", "0" * 64], home)
        _assert(code == 3 and "changed since" in err, "stale hash -> 3")

        print("Test: rewrite applies with a backup")
        code, res, _ = apply(["rewrite", doc], doc, home, backups)
        _assert(code == 0 and res["applied"] and read(res["backup"]) == original, "applied; backup holds the original")
        new = read(doc)
        _assert(new.count("## Wrap") == 1 and "imported-from" not in new and "`code`" in new, "rewrite result correct")

        print("Test: an existing backup is never overwritten; default roots are unique")
        write(doc, new + "\n<!-- imported-from: y -->\n")
        code, _, err = apply(["rewrite", doc], doc, home, backups)
        _assert(code == 3 and "already exists" in err, "same backup root twice refused")
        r1, r2 = ac._backup_root(home), ac._backup_root(home)
        _assert(r1 != r2 and os.path.isdir(r1), "default backup roots differ per invocation")

        print("Test: line breaks other than \\n survive byte for byte")
        odd = write(os.path.join(home, "proj", "odd.md"),
                    "<!-- imported-from: x -->\n# T\n\nkeep\x0cthis that\n")
        code, res, _ = apply(["rewrite", odd], odd, home, os.path.join(d, "b-odd"))
        _assert(code == 0 and read(odd) == "# T\n\nkeep\x0cthis that\n", "form feed and U+2028 untouched")

        print("Test: drop-section")
        drift = write(os.path.join(home, "proj", "AGENTS.md"),
                      "# Rules\n\n## Wrap\n\nv1 line\nv1 two\n\n## Other\n\nkeep me\n\n## Parent\n\nbody\n\n### Child\n\nchild body\n")
        _assert(call(["drop-section", drift, "--line", "3", "--heading", "Nope", "--dry-run"], home)[0] == 3,
                "heading mismatch refused")
        _assert(call(["drop-section", drift, "--line", "4", "--heading", "Wrap", "--dry-run"], home)[0] == 3,
                "non-heading line refused")
        code, _, err = call(["drop-section", drift, "--line", "12", "--heading", "Parent", "--dry-run"], home)
        _assert(code == 3 and "subsections" in err, "section with subsections refused")
        code, res, _ = apply(["drop-section", drift, "--line", "3", "--heading", "Wrap"], drift, home, os.path.join(d, "b-drop"))
        after = read(drift)
        _assert(code == 0 and "v1 line" not in after and "## Other" in after and "child body" in after,
                "only the chosen section removed")

        print("Test: pin-model")
        agent = write(os.path.join(home, ".claude", "agents", "executor.md"),
                      "---\nname: >\n  executor\n  agent\ndescription: builds\n---\nbody\n---bar\n")
        code, res, _ = apply(["pin-model", agent, "--model", "sonnet"], agent, home, os.path.join(d, "b-pin1"))
        _assert(code == 0 and read(agent).startswith("---\nmodel: sonnet\nname: >\n  executor\n"),
                "model inserted as the first key, outside the folded name value")
        code, res, _ = apply(["pin-model", agent, "--model", "haiku"], agent, home, os.path.join(d, "b-pin2"))
        _assert(read(agent).count("model:") == 1 and "model: haiku" in read(agent) and read(agent).endswith("---bar\n"),
                "existing model replaced; body untouched")
        empty = write(os.path.join(home, ".claude", "agents", "empty.md"), "---\n---\nbody\n")
        apply(["pin-model", empty, "--model", "opus"], empty, home, os.path.join(d, "b-pin3"))
        _assert(read(empty) == "---\nmodel: opus\n---\nbody\n", "empty frontmatter handled")
        _assert(call(["pin-model", agent, "--model", "inherit", "--dry-run"], home)[0] == 2,
                "inherit not offered (it leaves the agent unpinned)")
        nofm = write(os.path.join(home, ".claude", "agents", "bare.md"), "no frontmatter\n")
        _assert(call(["pin-model", nofm, "--model", "sonnet", "--dry-run"], home)[0] == 3, "no frontmatter refused")

        print("Test: symlinks follow to the target and keep the link")
        target = write(os.path.join(home, "shared", "AGENTS.md"), "<!-- imported-from: x -->\n# S\n")
        link = os.path.join(home, "proj2", "CLAUDE.md")
        os.makedirs(os.path.dirname(link))
        os.symlink(target, link)
        apply(["rewrite", link], link, home, os.path.join(d, "b-link"))
        _assert(os.path.islink(link) and read(target) == "# S\n", "target rewritten, link kept")
        evil = os.path.join(home, "proj2", "evil.md")
        os.symlink(write(os.path.join(home, "settings.json"), "{}\n"), evil)
        _assert(call(["rewrite", evil, "--dry-run"], home)[0] == 3, ".md link to a non-Markdown file refused")

        print("Test: plugin-owned files refused, including installPaths and case variants")
        plug = write(os.path.join(home, ".claude", "plugins", "cache", "p", "1", "agents", "a.md"), "---\nname: a\n---\n")
        _assert(call(["pin-model", plug, "--model", "sonnet", "--dry-run"], home)[0] == 3, "plugins dir refused")
        ext = write(os.path.join(d, "ext-plugin", "agents", "b.md"), "---\nname: b\n---\n")
        write(os.path.join(home, ".claude", "plugins", "installed_plugins.json"),
              json.dumps({"plugins": {"x@m": [{"scope": "user", "installPath": os.path.join(d, "ext-plugin")}]}}))
        _assert(call(["pin-model", ext, "--model", "sonnet", "--dry-run"], home)[0] == 3, "installPath outside plugins dir refused")
        if sys.platform == "darwin":
            variant = plug.replace("/.claude/plugins/", "/.Claude/Plugins/")
            _assert(call(["pin-model", variant, "--model", "sonnet", "--dry-run"], home)[0] == 3, "case variant refused")

        print("Test: other refusals")
        crlf = write(os.path.join(home, "proj", "crlf.md"), "# T\r\n\r\n## A\r\n\r\nx\r\ny\r\n")
        _assert(call(["drop-section", crlf, "--line", "3", "--heading", "A", "--dry-run"], home)[0] == 3, "CRLF refused for every action")
        bom = write(os.path.join(home, "proj", "bom.md"), "﻿# T\n")
        _assert(call(["rewrite", bom, "--dry-run"], home)[0] == 3, "BOM refused")
        ro = write(os.path.join(home, "proj", "ro.md"), "<!-- imported-from: x -->\n# R\n")
        os.chmod(ro, 0o444)
        _assert(call(["rewrite", ro, "--dry-run"], home)[0] == 3, "read-only file refused")
        hard = write(os.path.join(home, "proj", "hard.md"), "<!-- imported-from: x -->\n# H\n")
        os.link(hard, os.path.join(home, "proj", "hard2.md"))
        _assert(call(["rewrite", hard, "--dry-run"], home)[0] == 3, "hard-linked file refused")
        _assert(call(["rewrite", write(os.path.join(home, "proj", "r.txt"), "x\n"), "--dry-run"], home)[0] == 3, "non-Markdown refused")
        _assert(call(["rewrite", os.path.join(home, "nope.md"), "--dry-run"], home)[0] == 1, "missing file -> 1")
        _assert(call(["bogus", doc], home)[0] == 2, "unknown action -> 2")
        _assert(call(["drop-section", drift, "--line", "x", "--heading", "W"], home)[0] == 2, "bad --line -> 2")

        print("Test: file mode preserved")
        mode = write(os.path.join(home, "proj", "mode.md"), "<!-- imported-from: x -->\n# M\n")
        os.chmod(mode, 0o640)
        apply(["rewrite", mode], mode, home, os.path.join(d, "b-mode"))
        _assert(os.stat(mode).st_mode & 0o777 == 0o640, "mode kept after atomic replace")
    print("All apply-instruction-change tests passed.")


if __name__ == "__main__":
    run()
