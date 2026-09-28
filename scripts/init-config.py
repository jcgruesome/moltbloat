#!/usr/bin/env python3
"""Initialize or read moltbloat configuration file with migration support."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (per-config moltbloat data dir)
CONFIG_PATH = os.path.join(paths.moltbloat_home(), "config.json")
# A non-default Claude config inherits the default config's moltbloat
# settings (thresholds, rates) until it has a config.json of its own.
INHERITED_CONFIG_PATH = (None if paths.is_default_config()
                         else os.path.join(paths.default_moltbloat_home(), "config.json"))
CONFIG_VERSION = "1.8"

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "created": "",
    "thresholds": {
        "token_warning": 30000,
        "token_critical": 50000,
        "disk_warning_mb": 500,
        "disk_critical_mb": 1000,
        "snapshot_stale_days": 30,
        "baseline_max_age_days": 90,
        "usage_compact_lines": 5000,
        "stale_days": 30,
        "connector_overlap_min_shared_tools": 2,
        "connector_overlap_boilerplate_df": 3,
        "claude_md_verbose_lines": 200,
        "instruction_emphasis_per_100_lines": 3,
        "duplicate_section_similarity": 0.95,
        "drifted_section_similarity": 0.6,
        "instruction_byte_budget": 25000,
        "context_ledger_samples": 10,
        "context_ledger_max_sessions": 100
    },
    "costs": {
        "fable_per_1m_tokens": 10.00,
        "opus_per_1m_tokens": 4.00,  # Opus 5.5, which replaced Opus 5
        "sonnet_per_1m_tokens": 2.00,
        "haiku_per_1m_tokens": 1.00,
        "context_window_tokens": 1000000,
        "context_windows": {
            "fable_5_1": 1000000,
            "opus_5_5": 1000000,
            "opus_5": 1000000,
            "sonnet_5": 1000000,
            "haiku_4_5": 200000
        },
        # Prompt-cache multipliers on the base rate above: write (~once per
        # 5-min window) vs. read (every later turn reusing the cache).
        "cache_write_multiplier": 1.25,
        "cache_read_multiplier": 0.1,
        # Per-model rates per 1M tokens, matched by model-id prefix (longest
        # wins). Source: Claude API pricing reference, cached 2026-06-24.
        # cache_read is per model (Opus 5.5 and Fable 5.1 are not 0.1x).
        # Used by delegation-cost.py to price subagent runs.
        "models": {
            "claude-fable-5-1": {"input": 10.0, "output": 50.0, "cache_read": 0.25},
            "claude-fable-5": {"input": 10.0, "output": 50.0, "cache_read": 1.0},
            "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
            "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50},
            "claude-opus-4-8": {"input": 5.0, "output": 25.0, "cache_read": 0.50},
            "claude-opus-4-7": {"input": 5.0, "output": 25.0, "cache_read": 0.50},
            "claude-opus-4-6": {"input": 5.0, "output": 25.0, "cache_read": 0.50},
            "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20},
            "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30},
            "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10}
        }
    },
    "estimates": {
        "tokens_per_byte": 0.25,
        "tokens_per_skill": 25,
        "tokens_per_mcp_tool": 350,
        "tokens_per_agent": 200,
        "messages_per_day": 200
    },
    "health_score": {
        "critical_penalty": 15,
        "high_penalty": 10,
        "medium_penalty": 5,
        "low_penalty": 2,
        "token_cost_5pct_penalty": 5,
        "token_cost_10pct_penalty": 10,
        "large_disk_penalty": 3,
        "many_disabled_penalty": 3,
        "no_baseline_penalty": 5
    },
    "defaults": {
        "dry_run_first": True,
        "auto_compact": True,
        "snapshot_reminder": True,
        "show_dollar_costs": True
    },
    "ignored_findings": [],
    "export": {
        "default_format": "json",
        "include_usage_data": True,
        "anonymize": False
    }
}


# Built-in default values that were later corrected (e.g. stale model pricing).
# A deep-merge migration alone can't tell "user customized this" from "user
# never touched this, it's still the old default" — so refresh a value only
# when it still equals the OLD default below; a genuinely customized value is
# left alone. Each entry: dotted path -> the values it used to default to.
SUPERSEDED_DEFAULTS = {
    "costs.opus_per_1m_tokens": (15.00, 5.00),
    "costs.sonnet_per_1m_tokens": 3.00,
    "costs.haiku_per_1m_tokens": 0.80,
}


def _refresh_superseded_defaults(config):
    """Overwrite values still sitting at an old default with the new one."""
    for dotted, old_default in SUPERSEDED_DEFAULTS.items():
        section, key = dotted.split(".", 1)
        if section not in config or key not in config[section]:
            continue
        olds = old_default if isinstance(old_default, tuple) else (old_default,)
        if config[section][key] in olds:
            config[section][key] = DEFAULT_CONFIG[section][key]


def _merge_rate_table(config, user_config):
    """Merge `costs.models` per model id: defaults first, the user's entries
    on top. A one-level merge would let one custom model wipe every default
    rate, and freeze the table so later default rates never arrive."""
    user_models = ((user_config or {}).get("costs") or {}).get("models") or {}
    config["costs"] = dict(config.get("costs") or {})
    config["costs"]["models"] = {**DEFAULT_CONFIG["costs"]["models"], **user_models}
    return config


def model_rates(model, config=None):
    """(input, cache_read) per 1M for a model id from `costs.models`: an
    exact id, or the id plus a -YYYYMMDD date suffix. None if unknown."""
    import re
    models = ((config or load_config()).get("costs") or {}).get("models") or {}
    entry = models.get(model) or models.get(re.sub(r"-\d{8}$", "", model or ""))
    return (entry["input"], entry["cache_read"]) if entry else None


def migrate_config(old_config):
    """Migrate old config to current schema."""
    # A shallow .copy() would leave nested dicts (costs, thresholds, ...)
    # aliased to DEFAULT_CONFIG's own, so mutating config[key] below would
    # corrupt the module-level default for the rest of the process.
    config = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}

    # Deep merge existing values
    for key, value in old_config.items():
        if key == "version":
            continue  # Will be updated
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value

    _refresh_superseded_defaults(config)
    _merge_rate_table(config, old_config)

    # Update version and migration timestamp
    config["version"] = CONFIG_VERSION
    config["migrated"] = datetime.now(timezone.utc).isoformat()

    return config


def init_config():
    """Create default config if it doesn't exist, or migrate existing."""
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    except OSError as e:
        print(f"Error creating config directory: {e}", file=sys.stderr)
        return DEFAULT_CONFIG
    
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            
            # Check if migration needed
            user_version = user_config.get("version", "1.0")
            if user_version != CONFIG_VERSION:
                config = migrate_config(user_config)
                with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)
                print(f"Config migrated from {user_version} to {CONFIG_VERSION}", file=sys.stderr)
                return config
            
            # Deep merge with defaults for any missing keys
            config = DEFAULT_CONFIG.copy()
            for key, value in user_config.items():
                if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                    config[key] = {**config[key], **value}
                else:
                    config[key] = value
            
            return _merge_rate_table(config, user_config)
            
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading config: {e}, using defaults", file=sys.stderr)
            return DEFAULT_CONFIG
    
    # Create new config
    config = DEFAULT_CONFIG.copy()
    config["created"] = datetime.now(timezone.utc).isoformat()
    
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except IOError as e:
        print(f"Error saving config: {e}", file=sys.stderr)
    
    return config


def load_config():
    """Read config without writing anything.

    Missing file -> defaults. Old version -> migrated in memory only. Skills
    call --get/--dump, and read-only skills must not rewrite the user's file;
    only --init (init_config) creates or migrates it on disk.
    """
    source = CONFIG_PATH
    if not os.path.exists(source):
        if INHERITED_CONFIG_PATH and os.path.exists(INHERITED_CONFIG_PATH):
            source = INHERITED_CONFIG_PATH
        else:
            return migrate_config({})
    try:
        with open(source, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading config: {e}, using defaults", file=sys.stderr)
        return DEFAULT_CONFIG
    if user_config.get("version", "1.0") != CONFIG_VERSION:
        return migrate_config(user_config)
    config = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    for key, value in user_config.items():
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return _merge_rate_table(config, user_config)


def get_value(key_path, default=None):
    """Get a config value by dot-notation path (e.g., 'thresholds.token_warning')."""
    config = load_config()
    keys = key_path.split('.')
    
    try:
        value = config
        for key in keys:
            value = value[key]
        return value
    except (KeyError, TypeError):
        return default


def validate_config():
    """Validate config structure and print any issues."""
    config = load_config()
    errors = []
    
    # Check required sections
    required_sections = ["thresholds", "costs", "estimates", "health_score", "defaults"]
    for section in required_sections:
        if section not in config:
            errors.append(f"Missing required section: {section}")
    
    # Check value types
    if not isinstance(config.get("ignored_findings", []), list):
        errors.append("ignored_findings must be a list")
    
    if errors:
        print("Config validation errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return False
    
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Moltbloat config manager")
    parser.add_argument("--init", action="store_true", help="Initialize config file")
    parser.add_argument("--get", help="Get value by key path (e.g., thresholds.token_warning)")
    parser.add_argument("--dump", action="store_true", help="Dump full config as JSON")
    parser.add_argument("--validate", action="store_true", help="Validate config structure")
    
    args = parser.parse_args()
    
    if args.validate:
        sys.exit(0 if validate_config() else 1)
    elif args.init:
        config = init_config()
        print(f"Config initialized at {CONFIG_PATH}")
    elif args.get:
        value = get_value(args.get)
        if isinstance(value, (dict, list)):
            print(json.dumps(value))
        else:
            print(value if value is not None else "")
    elif args.dump:
        print(json.dumps(load_config(), indent=2))
    else:
        # Default: ensure config exists and show path
        init_config()
        print(CONFIG_PATH)
