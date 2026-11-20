"""
jarvis/devops/config.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Server and website configuration loader for DevOps tools.

Key invariants:
  • Secrets (private key bytes, passwords, API tokens) stay in files
    OUTSIDE the repo (e.g. ~/.ssh/id_rsa), never in memory or logs.
  • Server lookups are fuzzy and case-insensitive.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

SERVERS_CONFIG_PATH = PROJECT_ROOT / "config" / "servers.yaml"

_DEFAULT_SERVERS_CONFIG: dict[str, Any] = {
    "servers": {
        "cloudpanel_prod": {
            "name": "cloudpanel_prod",
            "host": "127.0.0.1",
            "user": "root",
            "port": 22,
            "key_path": "~/.ssh/id_rsa",
            "type": "CloudPanel",
            "services": ["nginx", "php8.2-fpm", "mysql", "redis"],
            "backup_dir": "/home/cloudpanel/backups",
        },
        "do_vps": {
            "name": "do_vps",
            "host": "127.0.0.1",
            "user": "ubuntu",
            "port": 22,
            "key_path": "~/.ssh/id_ed25519",
            "type": "DigitalOcean",
            "services": ["nginx", "php8.3-fpm", "mysql", "redis"],
            "backup_dir": "/var/backups",
        },
        "hostinger_vps": {
            "name": "hostinger_vps",
            "host": "127.0.0.1",
            "user": "root",
            "port": 22,
            "key_path": "~/.ssh/id_rsa",
            "type": "Hostinger VPS",
            "services": ["nginx", "php8.2-fpm", "mysql"],
            "backup_dir": "/backup",
        },
    },
    "websites": {
        "mrym_laravel": {
            "name": "mrym_laravel",
            "url": "https://mrym.example.com",
            "server": "cloudpanel_prod",
            "project_path": "/home/cloudpanel/htdocs/mrym_laravel",
            "type": "laravel",
            "ssl_days_threshold": 14,
            "laravel_log_path": "/home/cloudpanel/htdocs/mrym_laravel/storage/logs/laravel.log",
            "nginx_log_path": "/var/log/nginx/error.log",
        },
        "ibrahimcheikh": {
            "name": "ibrahimcheikh",
            "url": "https://ibrahimcheikh.example.com",
            "server": "do_vps",
            "project_path": "/var/www/ibrahimcheikh_laravel",
            "type": "laravel",
            "ssl_days_threshold": 14,
            "laravel_log_path": "/var/www/ibrahimcheikh_laravel/storage/logs/laravel.log",
            "nginx_log_path": "/var/log/nginx/error.log",
        },
    },
    "watcher": {
        "enabled": True,
        "interval_seconds": 180,
        "owner_name": "Alamin",
        "ssl_warning_days": 14,
        "alert_cooldown_seconds": 600,
    },
}


def load_servers_config() -> dict[str, Any]:
    """Load configuration from config/servers.yaml."""
    if not SERVERS_CONFIG_PATH.exists():
        return _DEFAULT_SERVERS_CONFIG

    try:
        with open(SERVERS_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data or _DEFAULT_SERVERS_CONFIG
    except Exception as exc:
        logger.warning(f"[DevOps Config] Failed to parse {SERVERS_CONFIG_PATH}: {exc}")
        return _DEFAULT_SERVERS_CONFIG


def get_all_servers() -> dict[str, dict[str, Any]]:
    """Return all configured servers."""
    cfg = load_servers_config()
    return cfg.get("servers", {})


def get_all_websites() -> dict[str, dict[str, Any]]:
    """Return all configured websites."""
    cfg = load_servers_config()
    return cfg.get("websites", {})


def get_watcher_config() -> dict[str, Any]:
    """Return background watcher settings."""
    cfg = load_servers_config()
    return cfg.get("watcher", _DEFAULT_SERVERS_CONFIG["watcher"])


def find_server(server_query: str) -> dict[str, Any] | None:
    """
    Find a server by name, hostname, or alias (case-insensitive fuzzy match).
    """
    clean = server_query.strip().lower()
    servers = get_all_servers()

    # Exact match
    for name, s in servers.items():
        if name.lower() == clean:
            return s

    # Partial / keyword match
    for name, s in servers.items():
        if clean in name.lower() or name.lower() in clean:
            return s
        if clean in str(s.get("host", "")).lower():
            return s
        if clean in str(s.get("type", "")).lower():
            return s

    return None


def find_website(site_query: str) -> dict[str, Any] | None:
    """
    Find a website by name or URL substring.
    """
    clean = site_query.strip().lower()
    websites = get_all_websites()

    # Exact match
    for name, site in websites.items():
        if name.lower() == clean:
            return site

    # Partial / URL match
    for name, site in websites.items():
        if clean in name.lower() or clean in str(site.get("url", "")).lower():
            return site

    return None
