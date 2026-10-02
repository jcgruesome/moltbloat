#!/usr/bin/env python3
"""Check if the moltbloat ecosystem snapshot is stale."""
import json
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (per-config moltbloat data dir)
MOLTBLOAT_HOME = paths.moltbloat_home()
baseline_path = os.path.join(MOLTBLOAT_HOME, "baseline.json")
config_path = os.path.join(MOLTBLOAT_HOME, "config.json")

# Default threshold
STALE_DAYS = 30

# Try to load threshold from config
try:
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        STALE_DAYS = config.get("thresholds", {}).get("snapshot_stale_days", 30)
except Exception:
    pass

if not os.path.exists(baseline_path):
    sys.exit(0)

try:
    with open(baseline_path) as f:
        data = json.load(f)
    ts = data["timestamp"][:10]
    days = (datetime.date.today() - datetime.date.fromisoformat(ts)).days
    if days > STALE_DAYS:
        # Stop fires after every response; a marker keeps the reminder to
        # once per day instead of repeating it every turn.
        marker_path = os.path.join(MOLTBLOAT_HOME, ".snapshot-reminder-shown")
        today = datetime.date.today().isoformat()
        if os.path.exists(marker_path):
            with open(marker_path) as f:
                if f.read().strip() == today:
                    sys.exit(0)
        with open(marker_path, "w") as f:
            f.write(today)
        print(f"[moltbloat] Last ecosystem snapshot is {days} days old. Run /moltbloat:snapshot to check for drift.")
except Exception:
    sys.exit(0)
