#!/usr/bin/env python3
"""Measure the context each Claude Code session actually loaded.

Claude Code writes what it injected at session start into the transcript as
`attachment` records: the skill listing, deferred tool names, MCP server
instructions, the agent listing, SessionStart hook output, and the
instruction files (CLAUDE.md and friends) it loaded. This script reads those
records instead of estimating from file sizes.

These record shapes are undocumented internals verified on 2026-09-25. If no
known record type is found at all, the script fails rather than guessing.

Usage:
  python3 context-ledger.py [--projects-dir DIR] [--config-dir DIR]
                            [--samples N] [--max-sessions N]
                            [--tokens-per-byte F] [--include-sdk] [--json]
"""
import glob
import json
import os
import re
import statistics
import sys

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
CONFIG_DIR = os.path.expanduser("~/.claude")


def server_of(tool_name):
    """MCP server segment of a tool name, or "(built-in)" for non-MCP tools."""
    if tool_name.startswith("mcp__"):
        return tool_name[len("mcp__"):].split("__", 1)[0]
    return "(built-in)"


def hook_context_len(stdout):
    """Classify a SessionStart hook's stdout.

    Only JSON `hookSpecificOutput.additionalContext` is injected as context.
    Returns ("context", n), ("no_context", 0) for JSON without it, or
    ("unparsed", 0) for non-JSON output.
    """
    try:
        obj = json.loads(stdout)
    except (TypeError, ValueError):
        return ("unparsed", 0)
    if not isinstance(obj, dict):
        return ("unparsed", 0)
    hso = obj.get("hookSpecificOutput")
    ctx = hso.get("additionalContext") if isinstance(hso, dict) else None
    if isinstance(ctx, str):
        return ("context", len(ctx))
    return ("no_context", 0)


def _lines_chars(lines):
    return sum(len(x) + 1 for x in lines)


def _iter_attachments(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"attachment"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # truncated line in a live session
            a = obj.get("attachment") if isinstance(obj, dict) else None
            if isinstance(a, dict) and a.get("type"):
                yield a


def session_entrypoint(path):
    """The session's `entrypoint` (e.g. "cli", "sdk-cli"), or None if absent."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"entrypoint"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            ep = obj.get("entrypoint") if isinstance(obj, dict) else None
            if ep:
                return ep
    return None


def _aligned(a, keys_field, values_field, kind, path, errors):
    keys = a.get(keys_field) or []
    values = a.get(values_field) or []
    if len(keys) != len(values):
        errors.append(f"{kind}: {len(keys)} {keys_field} vs {len(values)} {values_field} in {path}")
        return []
    return list(zip(keys, values))


def extract_session(path):
    """Measure one main-session transcript (per-session rules in the plan)."""
    s = {"format_errors": [], "entrypoint": session_entrypoint(path)}
    deferred, mcp, agents = {}, {}, {}
    hook_batch = None
    hooks = []
    for a in _iter_attachments(path):
        kind = a["type"]
        if kind == "skill_listing" and "skill_listing" not in s:
            content = a.get("content") or ""
            s["skill_listing"] = {"chars": len(content), "skill_count": a.get("skillCount"), "content": content}
        elif kind == "deferred_tools_delta":
            names = a.get("addedNames") or []
            if "addedLines" not in a:
                a = dict(a, addedLines=names)
            deferred.update(_aligned(a, "addedNames", "addedLines", kind, path, s["format_errors"]))
        elif kind == "mcp_instructions_delta":
            mcp.update(_aligned(a, "addedNames", "addedBlocks", kind, path, s["format_errors"]))
        elif kind == "agent_listing_delta":
            agents.update(_aligned(a, "addedTypes", "addedLines", kind, path, s["format_errors"]))
        elif kind == "instructions" and "instructions" not in s:
            s["instructions"] = [
                {"path": f.get("path"), "type": f.get("type"), "chars": len(f.get("content") or "")}
                for f in a.get("files") or [] if isinstance(f, dict)
            ]
        elif kind == "hook_additional_context" and "hook_merged" not in s:
            content = a.get("content")
            parts = content if isinstance(content, list) else [content or ""]
            s["hook_merged"] = {"chars": sum(len(x) for x in parts if isinstance(x, str))}
        elif kind == "hook_success" and a.get("hookEvent") == "SessionStart":
            if hook_batch is None:
                hook_batch = a.get("toolUseID")
            if a.get("toolUseID") != hook_batch:
                continue
            status, n = hook_context_len(a.get("stdout") or "")
            hooks.append({"command": a.get("command") or "", "status": status, "chars": n})
    if deferred:
        by_server = {}
        for name, line in deferred.items():
            srv = server_of(name)
            by_server[srv] = by_server.get(srv, 0) + len(line) + 1
        s["deferred_tools"] = {"chars": _lines_chars(deferred.values()), "names": len(deferred), "by_server": by_server}
    if mcp:
        by_server = {name: len(block) for name, block in mcp.items()}
        s["mcp_instructions"] = {"chars": sum(by_server.values()), "by_server": by_server}
    if agents:
        s["agent_listing"] = {"chars": _lines_chars(agents.values())}
    if hooks:
        s["hooks"] = hooks
    return s


SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+(:[A-Za-z0-9_.-]+)?$")


def parse_skill_listing(content):
    """[(name, listed_with_description)] for each `- name[: description]` line.

    Lines not starting with `- `, or whose name is not a valid skill name, are
    description continuations and are skipped.
    """
    entries = []
    for line in content.split("\n"):
        if not line.startswith("- "):
            continue
        name, sep, desc = line[2:].partition(": ")
        name = name.strip()
        if not SKILL_NAME_RE.match(name):
            continue
        entries.append((name, bool(sep and desc.strip())))
    return entries


def _skill_has_description(skill_md):
    with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    for line in text[3:end].splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip() not in ("", '""', "''")
    return False


def load_skill_descriptions(config_dir):
    """Map every locally installed skill name to whether its SKILL.md has a description."""
    descs = {}
    manifest = os.path.join(config_dir, "plugins", "installed_plugins.json")
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            plugins = (json.load(f).get("plugins") or {})
        for key, entries in plugins.items():
            plugin = key.split("@", 1)[0]
            for entry in entries or []:
                install = (entry or {}).get("installPath")
                if not install:
                    continue
                for md in glob.glob(os.path.join(install, "skills", "*", "SKILL.md")):
                    descs[f"{plugin}:{os.path.basename(os.path.dirname(md))}"] = _skill_has_description(md)
    for md in glob.glob(os.path.join(config_dir, "skills", "*", "SKILL.md")):
        descs[os.path.basename(os.path.dirname(md))] = _skill_has_description(md)
    return descs


def listing_chars_by_owner(content):
    """Skill listing chars per owning plugin; unprefixed skills are "(local)"."""
    out = {}
    owner = None
    for line in content.split("\n"):
        if line.startswith("- "):
            name = line[2:].partition(": ")[0].strip()
            if SKILL_NAME_RE.match(name):
                owner = name.split(":", 1)[0] if ":" in name else "(local)"
        if owner is not None:
            out[owner] = out.get(owner, 0) + len(line) + 1
    return out


def dropped_skills(content, skill_descs):
    """Bare listing entries for skills that have a description Claude never saw."""
    out = []
    for name, described in parse_skill_listing(content):
        if described:
            continue
        if name not in skill_descs:
            out.append({"name": name, "reason": "source_not_found"})
        elif skill_descs[name]:
            out.append({"name": name, "reason": "has_description"})
    return out


def _hook_commands(hooks_obj):
    for groups in (hooks_obj or {}).values():
        for group in groups or []:
            for h in (group or {}).get("hooks") or []:
                cmd = (h or {}).get("command")
                if cmd:
                    yield cmd


def load_hook_owners(config_dir):
    """Literal hook command string -> owner label.

    Transcripts record commands unexpanded, so matching is verbatim.
    """
    owners = {}
    manifest = os.path.join(config_dir, "plugins", "installed_plugins.json")
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            plugins = (json.load(f).get("plugins") or {})
        for key, entries in plugins.items():
            plugin = key.split("@", 1)[0]
            for entry in entries or []:
                hooks_path = os.path.join((entry or {}).get("installPath") or "", "hooks", "hooks.json")
                if not os.path.isfile(hooks_path):
                    continue
                with open(hooks_path, encoding="utf-8") as f:
                    for cmd in _hook_commands(json.load(f).get("hooks")):
                        owners.setdefault(cmd, set()).add(plugin)
    settings = os.path.join(config_dir, "settings.json")
    if os.path.isfile(settings):
        with open(settings, encoding="utf-8") as f:
            for cmd in _hook_commands(json.load(f).get("hooks")):
                owners.setdefault(cmd, set()).add("settings.json")
    return {cmd: ", ".join(sorted(names)) for cmd, names in owners.items()}
