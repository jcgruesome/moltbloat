#!/usr/bin/env python3
"""Detect skills in `.claude/skills/` dirs, invisible to the plugin-only audit.

Claude Code auto-loads skills from `.claude/skills/` (user-level and nested
per-project) with no plugin install needed. moltbloat's Check 1 skill-collision
scan only inventories plugin skills and `~/.claude/commands/`, never
`.claude/skills/`, so a local skill shadowing a plugin skill goes unseen.

A skill entry is a subdirectory containing `SKILL.md`, or the scanned
directory itself if it has a root-level `SKILL.md`.

Usage: python3 local-skills-scan.py [DIR ...] [--plugin-skills-file PATH] [--json]
`--plugin-skills-file` is a JSON object mapping skill name -> plugin name.
"""
import json
import os
import sys

DEFAULT_DIRS = [os.path.expanduser("~/.claude/skills"), os.path.join(os.getcwd(), ".claude", "skills")]


def find_local_skills(root):
    """Skill entries directly under `root`. Returns {name: path}."""
    found = {}
    if not os.path.isdir(root):
        return found
    if os.path.isfile(os.path.join(root, "SKILL.md")):
        found[os.path.basename(root.rstrip("/"))] = root
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "SKILL.md")):
            found[entry] = path
    return found


def scan(dirs, plugin_skill_names=None):
    """Scan `.claude/skills`-style dirs for local skills and collisions."""
    plugin_skill_names = plugin_skill_names or {}
    local = {}
    for d in dirs:
        for name, path in find_local_skills(d).items():
            local.setdefault(name, []).append(path)
    collisions = [
        {"name": n, "paths": p, "plugin_source": plugin_skill_names.get(n)}
        for n, p in sorted(local.items())
        if len(p) > 1 or plugin_skill_names.get(n)
    ]
    return {"local_skills": local, "collisions": collisions}


def render_markdown(result):
    lines = ["# Local .claude/skills Scan", "", f"Local skills found: {len(result['local_skills'])}."]
    if not result["collisions"]:
        lines.append("No collisions between local skills or with plugin skills.")
        return "\n".join(lines)
    lines += ["", "| Skill | Local paths | Plugin collision |", "|---|---|---|"]
    lines += [f"| {c['name']} | {', '.join(c['paths'])} | {c['plugin_source'] or '-'} |" for c in result["collisions"]]
    return "\n".join(lines)


def main(argv):
    args, dirs, as_json, plugin_skills_file = argv[1:], [], False, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--plugin-skills-file":
            i += 1
            if i >= len(args):
                sys.stderr.write("error: --plugin-skills-file requires a path\n")
                return 2
            plugin_skills_file = args[i]
        else:
            dirs.append(a)
        i += 1

    dirs = dirs or DEFAULT_DIRS
    plugin_skill_names = {}
    if plugin_skills_file:
        with open(plugin_skills_file, "r", encoding="utf-8") as fh:
            plugin_skill_names = json.load(fh)

    result = scan(dirs, plugin_skill_names)
    print(json.dumps(result, indent=2) if as_json else render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
