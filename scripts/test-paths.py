#!/usr/bin/env python3
"""Tests for paths.py and CLAUDE_CONFIG_DIR handling across moltbloat.

Run: python3 scripts/test-paths.py
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402


def _assert(cond, msg):
    if not cond:
        print(f"  x {msg}")
        raise SystemExit(1)
    print(f"  ok {msg}")


def env_for(home, config_dir=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    env["HOME"] = home
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    return env


def py(code, env):
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                          check=True, cwd=HERE).stdout.strip()


def run():
    saved = os.environ.pop("CLAUDE_CONFIG_DIR", None)
    try:
        with tempfile.TemporaryDirectory() as d:
            home = os.path.realpath(os.path.join(d, "home"))
            os.makedirs(os.path.join(home, ".claude"))
            alt = os.path.join(d, "work.cfg", "claude_alt")
            os.makedirs(alt)

            print("Test: resolver defaults and CLAUDE_CONFIG_DIR")
            _assert(paths.config_dir(home) == os.path.join(home, ".claude"), "default config dir")
            _assert(paths.moltbloat_home(home) == os.path.join(home, ".moltbloat"), "default data dir")
            os.environ["CLAUDE_CONFIG_DIR"] = alt
            _assert(paths.config_dir(home) == alt and paths.projects_dir(home) == os.path.join(alt, "projects"),
                    "CLAUDE_CONFIG_DIR sets config and projects dirs")
            expected = paths.moltbloat_home(home)
            import re as _re
            _assert(os.path.dirname(expected) == os.path.join(home, ".moltbloat", "configs")
                    and _re.fullmatch(_re.escape(paths.encode(alt)) + r"-[0-9a-f]{8}", os.path.basename(expected))
                    and "-work-cfg-claude-alt" in expected,
                    "non-default config gets its own data dir: readable name plus 8-digit hash")
            os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(home, ".claude")
            _assert(paths.moltbloat_home(home) == os.path.join(home, ".moltbloat"),
                    "CLAUDE_CONFIG_DIR pointing at ~/.claude is the default config")
            os.environ.pop("CLAUDE_CONFIG_DIR")

            print("Test: edge cases resolve consistently")
            os.environ["CLAUDE_CONFIG_DIR"] = ""
            _assert(paths.moltbloat_home(home) == os.path.join(home, ".moltbloat"), "empty CLAUDE_CONFIG_DIR = default")
            os.environ["CLAUDE_CONFIG_DIR"] = alt + "/"
            _assert(paths.moltbloat_home(home) == expected, "trailing slash ignored")
            link = os.path.join(d, "alt-link")
            os.symlink(alt, link)
            os.environ["CLAUDE_CONFIG_DIR"] = link
            _assert(paths.moltbloat_home(home) == expected, "symlinked config dir resolves to the same data dir")
            twin = os.path.join(d, "work.cfg", "claude-alt")
            os.makedirs(twin)
            os.environ["CLAUDE_CONFIG_DIR"] = twin
            _assert(paths.moltbloat_home(home) != expected and paths.encode(twin) == paths.encode(alt),
                    "dirs with the same readable name still get distinct data dirs (hash suffix)")
            os.environ.pop("CLAUDE_CONFIG_DIR")

            print("Test: state file per config")
            with open(os.path.join(home, ".claude.json"), "w") as f:
                f.write("{}")
            _assert(paths.state_file(os.path.join(home, ".claude"), home) == os.path.join(home, ".claude.json"),
                    "default config uses ~/.claude.json")
            _assert(paths.state_file(alt, home) == os.path.join(alt, ".claude.json"),
                    "other config uses its own state file, never ~/.claude.json")

            print("Test: managed-mcp-check reads the active config's state file")
            with open(os.path.join(home, ".claude.json"), "w") as f:
                json.dump({"mcpServers": {"default-only": {}}}, f)
            with open(os.path.join(alt, ".claude.json"), "w") as f:
                json.dump({"mcpServers": {"alt-only": {}}}, f)
            managed = os.path.join(d, "managed.json")
            with open(managed, "w") as f:
                json.dump({"managedMcpServers": {"default-only": {}, "alt-only": {}}}, f)
            r = subprocess.run([sys.executable, os.path.join(HERE, "managed-mcp-check.py"), "--managed-settings", managed, "--json"],
                               env=env_for(home, alt), capture_output=True, text=True, check=True)
            names = {c["name"] for c in json.loads(r.stdout)["collisions"]}
            _assert(names == {"alt-only"}, "collision found in the alt config's state, none from the default's")

            print("Test: a non-default config inherits moltbloat settings until it has its own")
            os.makedirs(os.path.join(home, ".moltbloat"), exist_ok=True)
            with open(os.path.join(home, ".moltbloat", "config.json"), "w") as f:
                json.dump({"version": "1.8", "thresholds": {"token_warning": 12345}}, f)
            get = ("import importlib.util;s=importlib.util.spec_from_file_location('ic','init-config.py');"
                   "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(m.get_value('thresholds.token_warning'))")
            _assert(py(get, env_for(home, alt)) == "12345", "inherited from ~/.moltbloat/config.json")
            os.makedirs(expected, exist_ok=True)
            with open(os.path.join(expected, "config.json"), "w") as f:
                json.dump({"version": "1.8", "thresholds": {"token_warning": 777}}, f)
            _assert(py(get, env_for(home, alt)) == "777", "own config.json wins once present")
            os.remove(os.path.join(expected, "config.json"))

            print("Test: CLI")
            out = subprocess.run([sys.executable, os.path.join(HERE, "paths.py"), "moltbloat-home"],
                                 env=env_for(home, alt), capture_output=True, text=True)
            _assert(out.returncode == 0 and out.stdout.strip() == expected, "moltbloat-home CLI")
            bad = subprocess.run([sys.executable, os.path.join(HERE, "paths.py"), "nope"],
                                 env=env_for(home), capture_output=True, text=True)
            _assert(bad.returncode == 2, "unknown command -> 2")

            print("Test: the bash usage hook and Python agree on the data dir")
            payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
            for cfg, want in ((None, os.path.join(home, ".moltbloat")), (alt, expected)):
                subprocess.run(["bash", os.path.join(HERE, "track-usage.sh")], input=payload, text=True,
                               env=env_for(home, cfg), check=True, capture_output=True)
                _assert(os.path.isfile(os.path.join(want, "usage.jsonl")),
                        f"hook wrote usage under {'default' if not cfg else 'per-config'} data dir")

            print("Test: config and snapshot reminder follow the active config")
            cp = py("import importlib.util,os;s=importlib.util.spec_from_file_location('ic','init-config.py');"
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(m.CONFIG_PATH)", env_for(home, alt))
            _assert(cp == os.path.join(expected, "config.json"), "config path is per-config")
            os.makedirs(expected, exist_ok=True)
            stale = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
            with open(os.path.join(expected, "baseline.json"), "w") as f:
                json.dump({"timestamp": stale + "T00:00:00Z"}, f)
            out = subprocess.run([sys.executable, os.path.join(HERE, "check-snapshot-age.py")],
                                 env=env_for(home, alt), capture_output=True, text=True, check=True).stdout
            _assert("90 days old" in out, "reminder reads the per-config baseline")
            out_default = subprocess.run([sys.executable, os.path.join(HERE, "check-snapshot-age.py")],
                                         env=env_for(home), capture_output=True, text=True, check=True).stdout
            _assert(out_default == "", "default config has no baseline, so no reminder")

            print("Test: ledger and delegation read transcripts from the active config")
            for script in ("context-ledger.py", "delegation-cost.py"):
                r = subprocess.run([sys.executable, os.path.join(HERE, script)], env=env_for(home, alt),
                                   capture_output=True, text=True)
                _assert(r.returncode == 1 and os.path.join(alt, "projects") in r.stderr,
                        f"{script} looks in $CLAUDE_CONFIG_DIR/projects")
    finally:
        if saved is not None:
            os.environ["CLAUDE_CONFIG_DIR"] = saved
    print("All paths tests passed.")


if __name__ == "__main__":
    run()
