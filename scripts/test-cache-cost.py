#!/usr/bin/env python3
"""Tests for cache-cost.py: caching-aware dollar cost calculation.

Run: python3 scripts/test-cache-cost.py
Exits non-zero on first failure so it can gate CI.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cache_cost", os.path.join(HERE, "cache-cost.py"))
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

BASE = dict(total_tokens=1_000_000, rate_per_1m=2.00, cache_write_multiplier=1.25, cache_read_multiplier=0.1)


def _assert(cond, msg):
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def run():
    print("Test: turn-1/turn-2+/uncached tiers apply the right multiplier")
    r = cc.scan(messages_per_day=200, **BASE)
    _assert(r["turn1_cost"] == 2.50, "turn 1 = base rate * cache_write_multiplier")
    _assert(r["cached_turn_cost"] == 0.20, "cached turn = base rate * cache_read_multiplier")
    _assert(r["uncached_cost"] == 2.00, "uncached = plain base rate, no multiplier")

    print("Test: session blended average amortizes the one-time write over more turns")
    short = cc.scan(messages_per_day=200, session_messages=2, **BASE)["session_blended_cost"]
    long_ = cc.scan(messages_per_day=200, session_messages=50, **BASE)["session_blended_cost"]
    _assert(short > long_, "blended cost drops as session grows")
    _assert(round(long_, 3) == round((2.50 + 49 * 0.20) / 50, 3), "blended = (write + (N-1)*read) / N")

    print("Test: daily cost is one write plus (messages_per_day - 1) cached reads")
    _assert(round(r["daily_cost"], 2) == round(2.50 + 199 * 0.20, 2), "daily cost formula holds")

    print("Test: a single daily message pays only the cache write, no negative reads")
    single = cc.scan(messages_per_day=1, **BASE)
    _assert(single["daily_cost"] == 2.50, "single-message day = write cost only")

    print("Test: fails fast on non-positive total_tokens")
    try:
        cc.scan(messages_per_day=200, **{**BASE, "total_tokens": 0})
        _assert(False, "should have raised ValueError")
    except ValueError:
        _assert(True, "raises ValueError on total_tokens <= 0")

    print("Test: monthly cost is daily cost times 30")
    _assert(round(r["monthly_cost"], 2) == round(r["daily_cost"] * 30, 2), "monthly = daily_cost * 30")

    print("\n✓ All cache-cost tests passed")


if __name__ == "__main__":
    run()
