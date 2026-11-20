"""
jarvis/routines/config.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Routine configuration loader, resolver, and persistence manager.
Reads and writes to config/routines.yaml.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml

from jarvis.logger import logger

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
ROUTINES_CONFIG_PATH = PROJECT_ROOT / "config" / "routines.yaml"

_DEFAULT_ROUTINES: dict[str, dict[str, Any]] = {
    "work_mode": {
        "name": "work_mode",
        "title": "Work Mode",
        "triggers": ["work mode", "start work", "start work mode", "enter work mode", "begin work"],
        "description": "Open VS Code on the active project, start the Laravel dev server, and open the local site in browser.",
        "steps": [
            {
                "tool": "open_app",
                "args": {"app_name": "code", "file_or_args": "{active_project_path}"},
                "description": "Open VS Code on the active project",
            },
            {
                "tool": "run_shell_command",
                "args": {"command": "cd {active_project_path} && php artisan serve > /dev/null 2>&1 &"},
                "description": "Start the Laravel development server",
            },
            {
                "tool": "browser_open",
                "args": {"url": "http://127.0.0.1:8000"},
                "description": "Open browser to the local site",
            },
        ],
    },
    "end_of_day": {
        "name": "end_of_day",
        "title": "End of Day",
        "triggers": ["end of day", "wrap up", "finish work for today", "end my day", "wrap up today"],
        "description": "Show git status of the active project, review pending reminders, stop dev servers, and summarize what was done today.",
        "steps": [
            {
                "tool": "laravel_git_status",
                "args": {},
                "description": "Show git status of the active project",
            },
            {
                "tool": "list_reminders",
                "args": {},
                "description": "Review pending reminders and tasks to commit",
            },
            {
                "tool": "run_shell_command",
                "args": {"command": "pkill -f 'artisan serve' || true"},
                "description": "Stop local development servers",
            },
            {
                "tool": "get_cost_today",
                "args": {},
                "description": "Summarize today's activities and spending",
            },
        ],
    },
    "server_check": {
        "name": "server_check",
        "title": "Server Check",
        "triggers": ["server check", "check servers", "check all servers", "run server check", "health check servers", "check server health"],
        "description": "Run health checks on all monitored servers and report status.",
        "steps": [
            {
                "tool": "server_health_check",
                "args": {"server_name": "all"},
                "description": "Run health checks across all configured servers",
            },
        ],
    },
}


def load_routines() -> dict[str, dict[str, Any]]:
    """Load all configured routines from config/routines.yaml."""
    if ROUTINES_CONFIG_PATH.exists():
        try:
            with open(ROUTINES_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                routines = data.get("routines", {})
                if isinstance(routines, dict) and routines:
                    return routines
        except Exception as exc:
            logger.warning(f"[Routines] Error reading {ROUTINES_CONFIG_PATH}: {exc}")

    return dict(_DEFAULT_ROUTINES)


def save_routine(routine_dict: dict[str, Any]) -> None:
    """Save or update a routine in config/routines.yaml."""
    name = routine_dict.get("name", "").strip().lower()
    if not name:
        raise ValueError("Routine must have a valid 'name' attribute.")

    # Security check on routine steps
    from jarvis.permission_gate import PermissionDenied
    from jarvis.tools import TOOL_REGISTRY
    for step in routine_dict.get("steps", []):
        tool = step.get("tool")
        if tool not in TOOL_REGISTRY:
            raise PermissionDenied(f"Security Error: Tool `{tool}` is not registered in TOOL_REGISTRY.")
        args = step.get("args", {})
        if any(k in args for k in ["skip_gate", "bypass_permission", "no_gate"]):
            raise PermissionDenied("Security Policy Violation: Routines can never contain steps that skip the permission gate.")

    routines = load_routines()
    routines[name] = routine_dict

    ROUTINES_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ROUTINES_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump({"routines": routines}, f, sort_keys=False, allow_unicode=True)

    logger.info(f"[Routines] Saved routine '{name}' to {ROUTINES_CONFIG_PATH}")


def get_routine(name_or_trigger: str) -> dict[str, Any] | None:
    """Find a routine by name or trigger phrase."""
    clean = name_or_trigger.strip().lower()
    routines = load_routines()

    # Exact name match
    if clean in routines:
        return routines[clean]

    # Normalized slug match (e.g. 'study mode' -> 'study_mode')
    slug = clean.replace(" ", "_")
    if slug in routines:
        return routines[slug]

    # Trigger phrase match
    for r in routines.values():
        triggers = [t.lower().strip() for t in r.get("triggers", [])]
        if clean in triggers or any(t in clean for t in triggers):
            return r

    return None


def get_active_project_path() -> str:
    """Resolve active project path safely for parameter substitution."""
    try:
        from jarvis.laravel.context import get_active_laravel_project
        _, path = get_active_laravel_project()
        return str(path)
    except Exception:
        pass

    try:
        from jarvis.config import PROJECTS, PROJECT_ROOT
        if "jarvis" in PROJECTS:
            return str(PROJECTS["jarvis"])
        if PROJECTS:
            first_key = next(iter(PROJECTS))
            return str(PROJECTS[first_key])
        return str(PROJECT_ROOT)
    except Exception:
        return str(PROJECT_ROOT)


def resolve_step_args(args: dict[str, Any]) -> dict[str, Any]:
    """Substitute placeholders like {active_project_path} in step arguments."""
    active_path = get_active_project_path()
    active_name = Path(active_path).name

    def _sub(val: Any) -> Any:
        if isinstance(val, str):
            return val.replace("{active_project_path}", active_path).replace("{active_project_name}", active_name)
        elif isinstance(val, dict):
            return {k: _sub(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_sub(x) for x in val]
        return val

    return {k: _sub(v) for k, v in args.items()}
