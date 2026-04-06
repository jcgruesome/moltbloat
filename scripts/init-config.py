#!/usr/bin/env python3
"""Initialize or read moltbloat configuration file."""
import json
import os
import sys

CONFIG_PATH = os.path.expanduser("~/.moltbloat/config.json")

DEFAULT_CONFIG = {
    "version": "1.1",
    "created": "",
    "thresholds": {
        "token_warning": 30000,
        "token_critical": 50000,
        "disk_warning_mb": 500,
        "disk_critical_mb": 1000,
        "snapshot_stale_days": 30,
        "baseline_max_age_days": 90,
        "usage_compact_lines": 5000
    },
    "costs": {
        "opus_per_1m_tokens": 15.00,
        "sonnet_per_1m_tokens": 3.00,
        "haiku_per_1m_tokens": 0.80,
        "context_window_tokens": 1000000
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


def init_config():
    """Create default config if it doesn't exist."""
    if os.path.exists(CONFIG_PATH):
        return load_config()
    
    # Create with timestamp
    from datetime import datetime, timezone
    config = DEFAULT_CONFIG.copy()
    config["created"] = datetime.now(timezone.utc).isoformat()
    
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
    
    return config


def load_config():
    """Load existing config, merging with defaults for any missing keys."""
    try:
        with open(CONFIG_PATH) as f:
            user_config = json.load(f)
        
        # Deep merge with defaults for any missing keys
        config = DEFAULT_CONFIG.copy()
        for key, value in user_config.items():
            if isinstance(value, dict) and key in config:
                config[key].update(value)
            else:
                config[key] = value
        
        return config
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        return DEFAULT_CONFIG


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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Moltbloat config manager")
    parser.add_argument("--init", action="store_true", help="Initialize config file")
    parser.add_argument("--get", help="Get value by key path (e.g., thresholds.token_warning)")
    parser.add_argument("--dump", action="store_true", help="Dump full config as JSON")
    
    args = parser.parse_args()
    
    if args.init:
        config = init_config()
        print(f"Config initialized at {CONFIG_PATH}")
    elif args.get:
        value = get_value(args.get)
        print(json.dumps(value) if isinstance(value, (dict, list)) else value)
    elif args.dump:
        print(json.dumps(load_config(), indent=2))
    else:
        # Default: ensure config exists and show path
        init_config()
        print(CONFIG_PATH)
