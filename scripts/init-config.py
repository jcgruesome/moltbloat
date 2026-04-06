#!/usr/bin/env python3
"""Initialize or read moltbloat configuration file with migration support."""
import json
import os
import sys
from datetime import datetime, timezone

CONFIG_PATH = os.path.expanduser("~/.moltbloat/config.json")
CONFIG_VERSION = "1.1"

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


def migrate_config(old_config):
    """Migrate old config to current schema."""
    config = DEFAULT_CONFIG.copy()
    
    # Deep merge existing values
    for key, value in old_config.items():
        if key == "version":
            continue  # Will be updated
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value
    
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
            
            return config
            
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


def get_value(key_path, default=None):
    """Get a config value by dot-notation path (e.g., 'thresholds.token_warning')."""
    config = init_config()
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
    config = init_config()
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
        print(json.dumps(init_config(), indent=2))
    else:
        # Default: ensure config exists and show path
        init_config()
        print(CONFIG_PATH)
