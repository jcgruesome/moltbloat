#!/usr/bin/env python3
"""Tests for deep-recon.py's plugin_component_counts(): output-style counting
so Check 4 (Zero-Skill Plugins) doesn't false-flag a plugin that only ships an
output style.

Run: python3 scripts/test-deep-recon.py
"""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("deep_recon", os.path.join(HERE, "deep-recon.py"))
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def make_files(dirpath, names):
    os.makedirs(dirpath, exist_ok=True)
    for name in names:
        with open(os.path.join(dirpath, name), "w") as f:
            f.write("")


def run():
    with tempfile.TemporaryDirectory() as d:
        # Plugin with only an output style: should be counted, not zero-value.
        style_only = os.path.join(d, "style-only", "1.0.0")
        make_files(os.path.join(style_only, "output-styles"), ["terse.md"])
        counts = dr.plugin_component_counts([style_only])
        _assert(counts["output_styles"] == 1, "output-style-only plugin counts 1 output style")
        _assert(counts["skills"] == 0 and counts["commands"] == 0 and counts["agents"] == 0,
                "output-style-only plugin has zero skills/commands/agents")
        total = sum(counts.values())
        _assert(total > 0, "output-style-only plugin is NOT zero-value (total surface > 0)")

        # Plugin with genuinely nothing: still correctly flagged as zero-value.
        empty = os.path.join(d, "empty", "1.0.0")
        os.makedirs(empty, exist_ok=True)
        counts_empty = dr.plugin_component_counts([empty])
        _assert(sum(counts_empty.values()) == 0, "plugin with no component dirs at all is zero-value")

        # Plugin with both skills and output styles: both counted.
        both = os.path.join(d, "both", "1.0.0")
        os.makedirs(os.path.join(both, "skills"), exist_ok=True)
        with open(os.path.join(both, "skills", "SKILL.md"), "w") as f:
            f.write("")
        make_files(os.path.join(both, "output-styles"), ["verbose.md", "terse.md"])
        counts_both = dr.plugin_component_counts([both])
        _assert(counts_both["skills"] == 1, "both: skills counted")
        _assert(counts_both["output_styles"] == 2, "both: output styles counted")

        # Max-across-versions semantics: two cached versions, differing output-style counts.
        v1 = os.path.join(d, "multi-version", "1.0.0")
        v2 = os.path.join(d, "multi-version", "2.0.0")
        make_files(os.path.join(v1, "output-styles"), ["a.md"])
        make_files(os.path.join(v2, "output-styles"), ["a.md", "b.md"])
        counts_multi = dr.plugin_component_counts([v1, v2])
        _assert(counts_multi["output_styles"] == 2, "output styles take max across cached versions")

        # Nonexistent version dir: no error, zero counts.
        missing = dr.plugin_component_counts([os.path.join(d, "does-not-exist", "1.0.0")])
        _assert(sum(missing.values()) == 0, "nonexistent version directory yields zero counts, no error")

    print("\nAll deep-recon plugin_component_counts tests passed")


if __name__ == "__main__":
    run()
