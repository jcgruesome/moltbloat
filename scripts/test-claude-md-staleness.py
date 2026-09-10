#!/usr/bin/env python3
"""Tests for claude-md-staleness.py — CLAUDE.md/SKILL.md staleness and bloat checks.

Run: python3 scripts/test-claude-md-staleness.py
Exits non-zero on first failure so it can gate CI.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location(
    "claude_md_staleness", os.path.join(HERE, "claude-md-staleness.py")
)
cms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cms)


def _assert(cond, msg):
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def run():
    print("Test: flags a known deprecated reference with dated evidence")
    text = "Run /reload-plugins after installing a new plugin.\n"
    findings = cms.analyze_text("CLAUDE.md", text)
    ids = [f["id"] for f in findings]
    _assert("reload-plugins-removed" in ids, "reload-plugins-removed finding present")
    hit = next(f for f in findings if f["id"] == "reload-plugins-removed")
    _assert(hit["severity"] == "MEDIUM", "deprecation finding carries expected severity")
    _assert("2.1.268" in hit["message"], "finding cites the Claude Code version that removed it")
    _assert(hit["line"] == 1, "finding reports the correct line number")

    print("Test: clean text produces no deprecation findings")
    findings = cms.analyze_text("CLAUDE.md", "Just a normal instruction file.\n")
    _assert(
        not [f for f in findings if f["type"] == "deprecated_reference"],
        "no deprecation findings on unrelated text",
    )

    print("Test: multiple known deprecations detected independently")
    text = 'Set keybindingFlavor to vim.\nAlso defaultMode: "bypassPermissions" for CI.\n'
    findings = cms.analyze_text("CLAUDE.md", text)
    ids = {f["id"] for f in findings}
    _assert("keybinding-flavor-removed" in ids, "keybindingFlavor detected")
    _assert("bypass-permissions-default-mode-ignored" in ids, "defaultMode bypassPermissions detected")

    print("Test: verbosity heuristic flags long files, spares short ones")
    long_text = "\n".join(f"Line {i} of instructions." for i in range(250))
    findings = cms.analyze_text("CLAUDE.md", long_text, verbose_threshold=200)
    verbosity_hits = [f for f in findings if f["type"] == "verbose"]
    _assert(len(verbosity_hits) == 1, "long file flagged exactly once for verbosity")
    _assert("250" in verbosity_hits[0]["message"], "verbosity finding reports actual line count")

    short_text = "\n".join(f"Line {i}" for i in range(20))
    findings = cms.analyze_text("CLAUDE.md", short_text, verbose_threshold=200)
    _assert(
        not [f for f in findings if f["type"] == "verbose"],
        "short file is not flagged for verbosity",
    )

    print("Test: low header density flagged on a long, unstructured file")
    unstructured = "\n".join(f"paragraph line {i} with no headers at all" for i in range(150))
    findings = cms.analyze_text("CLAUDE.md", unstructured, verbose_threshold=1000)
    _assert(
        any(f["type"] == "unstructured" for f in findings),
        "long file with zero headers flagged as unstructured",
    )

    structured_lines = []
    for i in range(150):
        if i % 10 == 0:
            structured_lines.append(f"## Section {i}")
        else:
            structured_lines.append(f"content line {i}")
    structured = "\n".join(structured_lines)
    findings = cms.analyze_text("CLAUDE.md", structured, verbose_threshold=1000)
    _assert(
        not [f for f in findings if f["type"] == "unstructured"],
        "well-sectioned file is not flagged as unstructured",
    )

    print("Test: unknown skill-command reference flagged")
    text = "Run `/moltbloat:doctor` to check plugin health.\n"
    findings = cms.analyze_text(
        "CLAUDE.md", text, known_skill_refs={"moltbloat:diagnose", "moltbloat:audit"}
    )
    hits = [f for f in findings if f["type"] == "unknown_skill_reference"]
    _assert(len(hits) == 1, "unknown skill reference detected")
    _assert("moltbloat:doctor" in hits[0]["message"], "finding names the stale reference")
    _assert(hits[0]["severity"] == "HIGH", "unknown skill reference is HIGH severity")

    print("Test: known skill-command reference is not flagged")
    text = "Run `/moltbloat:audit` for a full scan.\n"
    findings = cms.analyze_text(
        "CLAUDE.md", text, known_skill_refs={"moltbloat:diagnose", "moltbloat:audit"}
    )
    _assert(
        not [f for f in findings if f["type"] == "unknown_skill_reference"],
        "reference to a real, still-installed skill is not flagged",
    )

    print("Test: skill-reference check skipped when no known set is supplied")
    text = "Run `/whatever:thing` here.\n"
    findings = cms.analyze_text("CLAUDE.md", text, known_skill_refs=None)
    _assert(
        not [f for f in findings if f["type"] == "unknown_skill_reference"],
        "no known_skill_refs means no false positives from an incomplete inventory",
    )

    print("Test: scan_paths aggregates findings across multiple files")
    with tempfile.TemporaryDirectory() as d:
        p1 = os.path.join(d, "CLAUDE.md")
        p2 = os.path.join(d, "SKILL.md")
        with open(p1, "w") as f:
            f.write("Use /reload-plugins after installing.\n")
        with open(p2, "w") as f:
            f.write("Nothing stale here.\n")
        result = cms.scan_paths([p1, p2])
        _assert(result["files_scanned"] == 2, "both files counted as scanned")
        _assert(
            any(f["file"] == p1 for f in result["findings"]),
            "finding attributed to the correct source file",
        )
        _assert(
            not any(f["file"] == p2 for f in result["findings"]),
            "clean file contributes no findings",
        )

    print("Test: render_markdown produces a readable report with the snapshot date disclaimer")
    with tempfile.TemporaryDirectory() as d:
        p1 = os.path.join(d, "CLAUDE.md")
        with open(p1, "w") as f:
            f.write("Use /reload-plugins after installing.\n")
        result = cms.scan_paths([p1])
        md = cms.render_markdown(result)
        _assert("CLAUDE.md" in md, "report mentions the scanned file")
        _assert("reload-plugins" in md, "report surfaces the deprecation finding")
        _assert("snapshot" in md.lower(), "report discloses that the deprecation table is a dated snapshot")

    print("Test: main() CLI exits 0 and prints markdown for a clean file")
    with tempfile.TemporaryDirectory() as d:
        p1 = os.path.join(d, "CLAUDE.md")
        with open(p1, "w") as f:
            f.write("A short, clean file.\n")
        rc = cms.main(["claude-md-staleness.py", p1])
        _assert(rc == 0, "main returns 0 on successful scan")

    print("Test: main() fails fast on a missing file")
    rc = cms.main(["claude-md-staleness.py", "/nonexistent/path/CLAUDE.md"])
    _assert(rc != 0, "main returns non-zero when a given path does not exist")

    print("\nAll tests passed.")


if __name__ == "__main__":
    run()
