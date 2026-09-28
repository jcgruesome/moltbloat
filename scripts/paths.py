#!/usr/bin/env python3
"""Where Claude Code and moltbloat keep their files, for the active config.

Claude Code reads its config dir from CLAUDE_CONFIG_DIR, falling back to
~/.claude. Transcripts (projects/), plugins, agents, rules, skills,
settings.json, and the user CLAUDE.md all live there, so every moltbloat
script resolves paths through this module instead of assuming ~/.claude.

moltbloat's own data (usage log, snapshots, profiles, config, backups) is
kept per Claude config so two configs never mix their usage or baselines:
  default config (~/.claude)  -> ~/.moltbloat
  any other config dir        -> ~/.moltbloat/configs/<encoded dir>-<hash>
where <encoded dir> turns every non-alphanumeric character of the resolved
path into '-' (readable) and <hash> is the first 8 hex digits of its sha256
(so /a/claude-work and /a/claude.work never share data).

A non-default config reads moltbloat's settings (config.json) from the
default data dir until it has its own; see init-config.py.

CLI, for skill bash snippets:
  python3 paths.py config-dir | projects-dir | plugins-dir | moltbloat-home | state-file
"""
import hashlib
import os
import re
import sys


def _home(home=None):
    return home or os.path.expanduser("~")


def default_config_dir(home=None):
    return os.path.join(_home(home), ".claude")


def config_dir(home=None):
    """The active Claude config dir: $CLAUDE_CONFIG_DIR, else ~/.claude."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return os.path.expanduser(env) if env else default_config_dir(home)


def is_default_config(home=None):
    return os.path.realpath(config_dir(home)) == os.path.realpath(default_config_dir(home))


def projects_dir(home=None):
    return os.path.join(config_dir(home), "projects")


def plugins_dir(home=None):
    return os.path.join(config_dir(home), "plugins")


def encode(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def default_moltbloat_home(home=None):
    return os.path.join(_home(home), ".moltbloat")


def moltbloat_home(home=None):
    """moltbloat's data dir for the active Claude config."""
    if is_default_config(home):
        return default_moltbloat_home(home)
    real = os.path.realpath(config_dir(home))
    digest = hashlib.sha256(real.encode("utf-8")).hexdigest()[:8]
    return os.path.join(default_moltbloat_home(home), "configs", f"{encode(real)}-{digest}")


def state_file(config=None, home=None):
    """Claude Code's global state file (.claude.json) for a config dir.

    The default config keeps it at ~/.claude.json (older installs inside
    ~/.claude). A non-default CLAUDE_CONFIG_DIR keeps it inside that dir,
    and the default config's file is never used for it.
    """
    cfg = config or config_dir(home)
    if os.path.realpath(cfg) == os.path.realpath(default_config_dir(home)):
        for p in (os.path.join(_home(home), ".claude.json"), os.path.join(cfg, ".claude.json")):
            if os.path.isfile(p):
                return p
        return os.path.join(_home(home), ".claude.json")
    return os.path.join(cfg, ".claude.json")


def main(argv):
    commands = {"config-dir": config_dir, "projects-dir": projects_dir, "plugins-dir": plugins_dir,
                "moltbloat-home": moltbloat_home, "state-file": state_file}
    if len(argv) != 2 or argv[1] not in commands:
        sys.stderr.write("usage: paths.py {" + "|".join(commands) + "}\n")
        return 2
    print(commands[argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
