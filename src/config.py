"""SELLO — Configuration: YAML-based config for automated verification."""

import os
import json


# We avoid requiring PyYAML by supporting a simple YAML subset parser
# or falling back to JSON config

CONFIG_PATH = os.path.expanduser("~/.sello/config.json")
CONFIG_YAML_PATH = os.path.expanduser("~/.sello/config.yml")


def load_config():
    """Load configuration from ~/.sello/config.json or config.yml."""

    # Try JSON first
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)

    # Try YAML (simple parser for basic structures)
    if os.path.exists(CONFIG_YAML_PATH):
        return _parse_simple_yaml(CONFIG_YAML_PATH)

    return get_default_config()


def save_default_config():
    """Create default config file."""
    config = get_default_config()
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return CONFIG_PATH


def get_default_config():
    return {
        "version": "0.1.0",

        # Backups to verify automatically with 'sello watch' or 'sello verify-all'
        "backups": [
            {
                "name": "daily-files",
                "path": "/backups/daily-*.tar.gz",
                "type": "auto",
                "enabled": True
            },
            {
                "name": "mysql-dump",
                "path": "/backups/mysql/dump.sql.gz",
                "type": "db_mysql",
                "engine": "mysql",
                "enabled": False
            },
            {
                "name": "postgres-dump",
                "path": "/backups/postgres/dump.sql",
                "type": "db_postgres",
                "engine": "postgres",
                "enabled": False
            }
        ],

        # Size anomaly detection
        "size_policy": {
            "enabled": True,
            "min_size_mb": 0.001,
            "max_deviation_percent": 80,
            "compare_with_last": 5
        },

        # Freshness policy
        "freshness_policy": {
            "warn_after_hours": 168,
            "fail_after_hours": 720
        },

        # Notifications
        "notifications": {
            "notify_on": "failure",
            "telegram": {
                "enabled": False,
                "bot_token": "",
                "chat_id": ""
            },
            "slack": {
                "enabled": False,
                "webhook_url": ""
            },
            "email": {
                "enabled": False,
                "to": "admin@tuempresa.com"
            }
        },

        # Report settings
        "reports": {
            "default_format": "terminal",
            "html_output_dir": os.path.expanduser("~/sello-reports"),
            "keep_html_reports": 30
        }
    }


def _parse_simple_yaml(path):
    """Minimal YAML parser for basic key-value configs. Falls back to JSON."""
    # For MVP, we recommend JSON config. This is a placeholder.
    # In production, add PyYAML as optional dependency.
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        print("⚠ PyYAML no instalado. Usa config.json en su lugar.")
        print("  pip install pyyaml --break-system-packages")
        return get_default_config()
