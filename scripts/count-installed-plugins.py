#!/usr/bin/env python3
"""Count installed plugins from Claude Code's installed_plugins.json.

/moltbloat:diagnose used to count with `grep -c '"name"'`, which never matched
this file's real shape: plugins are keyed by "<plugin>@<marketplace>" under a
top-level "plugins" object, not listed under "name" fields. On every real
install this silently reported 0. Reads the actual registry structure instead.

Usage: python3 count-installed-plugins.py [PATH]
PATH defaults to ~/.claude/plugins/installed_plugins.json.
Prints the count on success; 0 on a missing or malformed file (never raises,
since this feeds a diagnostic report that should degrade quietly).
"""
import json
import os
import sys

DEFAULT_PATH = os.path.expanduser("~/.claude/plugins/installed_plugins.json")


def count_installed_plugins(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return 0
    return len(plugins)


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_PATH
    print(count_installed_plugins(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
