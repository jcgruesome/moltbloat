#!/usr/bin/env python3
"""Tests for count-installed-plugins.py.

Run: python3 scripts/test-count-installed-plugins.py
Exits non-zero on first failure so it can gate CI.
"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location(
    "count_installed_plugins", os.path.join(HERE, "count-installed-plugins.py")
)
cip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cip)


def _assert(cond, msg):
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def _write(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def run():
    with tempfile.TemporaryDirectory() as d:

        print("Test: counts plugins keyed under the top-level 'plugins' object")
        p = os.path.join(d, "installed_plugins.json")
        _write(p, {
            "version": "1.0",
            "plugins": {
                "moltbloat@moltbloat": [{"scope": "user"}],
                "superpowers@claude-plugins-official": [{"scope": "user"}],
            },
        })
        _assert(cip.count_installed_plugins(p) == 2, "counts each plugin key once")

        print("Test: empty plugins object counts as zero")
        p2 = os.path.join(d, "empty.json")
        _write(p2, {"version": "1.0", "plugins": {}})
        _assert(cip.count_installed_plugins(p2) == 0, "empty registry counts as 0")

        print("Test: missing file returns 0, no exception")
        _assert(cip.count_installed_plugins(os.path.join(d, "nonexistent.json")) == 0, "missing file is 0")

        print("Test: malformed JSON returns 0, no exception")
        p3 = os.path.join(d, "malformed.json")
        with open(p3, "w") as f:
            f.write("{ this is not valid json")
        _assert(cip.count_installed_plugins(p3) == 0, "malformed JSON is 0")

        print("Test: does not naively grep-match a 'name' substring inside a plugin's own data")
        p4 = os.path.join(d, "with_name_fields.json")
        _write(p4, {
            "version": "1.0",
            "plugins": {
                "only-one@marketplace": [
                    {"scope": "user", "name": "irrelevant metadata field"},
                    {"scope": "project", "name": "another one"},
                ],
            },
        })
        _assert(
            cip.count_installed_plugins(p4) == 1,
            "one plugin key counted once, regardless of how many 'name'-shaped fields its entries contain",
        )

    print("\nAll tests passed.")


if __name__ == "__main__":
    run()
