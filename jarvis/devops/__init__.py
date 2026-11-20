"""
jarvis/devops/__init__.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Jarvis DevOps & Server Monitoring Package.

Exports:
  • server_health_check: SSH health check (disk, RAM, load, services, queues, docker)
  • server_analyze_logs: remote log analysis and fix suggestions
  • server_deploy: multi-step remote deployment with pre-migration DB backup
  • server_check_backups: remote backup verification and age reporting
  • server_restart_service: remote service restart with confirmation
  • server_run_remote_command: remote shell execution with permission gate
  • server_list_sites: list servers and monitored websites
  • watcher / BackgroundServerWatcher: background monitoring and proactive speech alerts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.devops.backup import server_check_backups
from jarvis.devops.config import (
    find_server,
    find_website,
    get_all_servers,
    get_all_websites,
    get_watcher_config,
    load_servers_config,
)
from jarvis.devops.deploy import server_deploy
from jarvis.devops.gate import check_devops_permission
from jarvis.devops.health import server_health_check
from jarvis.devops.logs import server_analyze_logs
from jarvis.devops.services import (
    server_list_sites,
    server_restart_service,
    server_run_remote_command,
)
from jarvis.devops.watcher import BackgroundServerWatcher, watcher

# ── Register tool risk levels in Central Tool Risk Table dynamically ─────────
try:
    from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel
    CENTRAL_TOOL_RISK_TABLE["server_health_check"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["server_check_backups"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["server_analyze_logs"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["server_list_sites"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["server_restart_service"] = RiskLevel.NEEDS_CONFIRMATION
    CENTRAL_TOOL_RISK_TABLE["server_deploy"] = RiskLevel.NEEDS_CONFIRMATION
    CENTRAL_TOOL_RISK_TABLE["server_run_remote_command"] = RiskLevel.NEEDS_CONFIRMATION
except Exception:
    pass

__all__ = [
    "server_health_check",
    "server_analyze_logs",
    "server_deploy",
    "server_check_backups",
    "server_restart_service",
    "server_run_remote_command",
    "server_list_sites",
    "check_devops_permission",
    "load_servers_config",
    "get_all_servers",
    "get_all_websites",
    "get_watcher_config",
    "find_server",
    "find_website",
    "watcher",
    "BackgroundServerWatcher",
]
