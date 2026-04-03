#!/usr/bin/env python3
"""Check if the moltbloat ecosystem snapshot is stale (>30 days old)."""
import json
import datetime
import os
import sys

baseline_path = os.path.expanduser("~/.moltbloat/baseline.json")

if not os.path.exists(baseline_path):
    sys.exit(0)

try:
    with open(baseline_path) as f:
        data = json.load(f)
    ts = data["timestamp"][:10]
    days = (datetime.date.today() - datetime.date.fromisoformat(ts)).days
    if days > 30:
        print(f"[moltbloat] Last ecosystem snapshot is {days} days old. Run /moltbloat:snapshot to check for drift.")
except Exception:
    sys.exit(0)
