#!/usr/bin/env python3
"""Check if the moltbloat ecosystem snapshot is stale."""
import json
import datetime
import os
import sys

baseline_path = os.path.expanduser("~/.moltbloat/baseline.json")
config_path = os.path.expanduser("~/.moltbloat/config.json")

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
        print(f"[moltbloat] Last ecosystem snapshot is {days} days old. Run /moltbloat:snapshot to check for drift.")
except Exception:
    sys.exit(0)
