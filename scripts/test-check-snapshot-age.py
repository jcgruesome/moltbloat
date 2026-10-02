#!/usr/bin/env python3
"""Tests for check-snapshot-age.py: the Stop-hook snapshot reminder.

Stop fires after every response, so the reminder must print at most once a
day, not after every turn.

Run: python3 scripts/test-check-snapshot-age.py
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check-snapshot-age.py")


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def run_hook(home):
    env = dict(os.environ, HOME=home)
    env.pop("CLAUDE_CONFIG_DIR", None)
    out = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True, check=True)
    return out.stdout


def write_baseline(home, days_old):
    ts = (datetime.date.today() - datetime.timedelta(days=days_old)).isoformat()
    os.makedirs(os.path.join(home, ".moltbloat"), exist_ok=True)
    with open(os.path.join(home, ".moltbloat", "baseline.json"), "w") as f:
        json.dump({"timestamp": ts + "T00:00:00Z"}, f)


def run():
    with tempfile.TemporaryDirectory() as home:
        print("Test: no baseline -> silent")
        _assert(run_hook(home) == "", "no output without a baseline")

        print("Test: fresh baseline -> silent")
        write_baseline(home, 2)
        _assert(run_hook(home) == "", "no output when snapshot is recent")

        print("Test: stale baseline -> reminder once per day")
        write_baseline(home, 45)
        first = run_hook(home)
        _assert("45 days old" in first, "first stale check prints the reminder")
        _assert(len(first.encode()) <= 200, "reminder stays within its 200-byte budget")
        _assert(run_hook(home) == "", "second check the same day is silent")

        print("Test: reminder returns on a later day")
        marker = os.path.join(home, ".moltbloat", ".snapshot-reminder-shown")
        with open(marker, "w") as f:
            f.write((datetime.date.today() - datetime.timedelta(days=1)).isoformat())
        _assert("days old" in run_hook(home), "reminder prints again once the marker is from an earlier day")
    print("All check-snapshot-age tests passed.")


if __name__ == "__main__":
    run()
