#!/usr/bin/env python3
"""Tests for init-config.py — config defaults, migration, and stale-default refresh.

Run: python3 scripts/test-init-config.py
Exits non-zero on first failure so it can gate CI.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location(
    "init_config", os.path.join(HERE, "init-config.py")
)
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)


def _assert(cond, msg):
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def run():
    print("Test: current model cost defaults are the Claude 5 family rates")
    _assert(ic.DEFAULT_CONFIG["costs"]["opus_per_1m_tokens"] == 5.00, "opus 5 rate")
    _assert(ic.DEFAULT_CONFIG["costs"]["sonnet_per_1m_tokens"] == 2.00, "sonnet 5 rate")
    _assert(ic.DEFAULT_CONFIG["costs"]["haiku_per_1m_tokens"] == 1.00, "haiku 4.5 rate")
    _assert(ic.DEFAULT_CONFIG["costs"]["fable_per_1m_tokens"] == 10.00, "fable 5.1 rate present")

    print("Test: per-model context windows are stored alongside the flat default")
    windows = ic.DEFAULT_CONFIG["costs"]["context_windows"]
    _assert(ic.DEFAULT_CONFIG["costs"]["context_window_tokens"] == 1000000, "flat context_window_tokens default unchanged (1M)")
    _assert(windows["fable_5_1"] == 1000000, "fable 5.1 context window is 1M")
    _assert(windows["opus_5"] == 1000000, "opus 5 context window is 1M")
    _assert(windows["sonnet_5"] == 1000000, "sonnet 5 context window is 1M")
    _assert(windows["haiku_4_5"] == 200000, "haiku 4.5 context window is 200K, not the shared 1M")

    print("Test: migrating an old config without context_windows picks up the new default")
    old_no_windows = {"version": "1.3", "costs": {"opus_per_1m_tokens": 5.00}}
    migrated_windows = ic.migrate_config(old_no_windows)
    _assert(migrated_windows["costs"]["context_windows"]["haiku_4_5"] == 200000, "migrated config gains context_windows dict")

    print("Test: migrating an old config refreshes untouched stale defaults")
    old = {
        "version": "1.3",
        "costs": {"opus_per_1m_tokens": 15.00, "sonnet_per_1m_tokens": 3.00, "haiku_per_1m_tokens": 0.80},
    }
    migrated = ic.migrate_config(old)
    _assert(migrated["costs"]["opus_per_1m_tokens"] == 5.00, "stale opus rate refreshed")
    _assert(migrated["costs"]["sonnet_per_1m_tokens"] == 2.00, "stale sonnet rate refreshed")
    _assert(migrated["costs"]["haiku_per_1m_tokens"] == 1.00, "stale haiku rate refreshed")
    _assert(migrated["costs"]["fable_per_1m_tokens"] == 10.00, "new fable rate added for existing config")
    _assert(migrated["version"] == ic.CONFIG_VERSION, "version bumped to current")

    print("Test: migration preserves a genuinely customized rate")
    customized = {
        "version": "1.3",
        "costs": {"opus_per_1m_tokens": 99.00, "sonnet_per_1m_tokens": 3.00, "haiku_per_1m_tokens": 0.80},
    }
    migrated2 = ic.migrate_config(customized)
    _assert(migrated2["costs"]["opus_per_1m_tokens"] == 99.00, "customized opus rate untouched")
    _assert(migrated2["costs"]["sonnet_per_1m_tokens"] == 2.00, "untouched sonnet rate still refreshed")

    print("Test: migrate_config never mutates the shared DEFAULT_CONFIG dict")
    before = dict(ic.DEFAULT_CONFIG["costs"])
    ic.migrate_config({"version": "1.3", "costs": {"opus_per_1m_tokens": 15.00}})
    _assert(ic.DEFAULT_CONFIG["costs"] == before, "DEFAULT_CONFIG['costs'] unchanged after migrate_config")

    print("\nAll tests passed.")


if __name__ == "__main__":
    run()
