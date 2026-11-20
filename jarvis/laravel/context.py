"""
jarvis/laravel/context.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Laravel Project Context Resolution.

Retrieves the currently active project from Jarvis memory. If not explicitly
set, auto-discovers configured Laravel projects with an `artisan` binary.
Executes artisan commands securely inside the project directory.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from jarvis.config import PROJECT_ROOT, get
from jarvis.logger import logger
from jarvis.memory import memory_manager


def get_active_laravel_project(preferred_path: str | None = None) -> tuple[str, Path]:
    """
    Resolve the active Laravel project name and filesystem Path.

    Returns
    -------
    tuple[str, Path]
        (project_name, project_path)

    Raises
    ------
    RuntimeError
        If no valid Laravel project root (containing `artisan`) can be resolved.
    """
    if preferred_path:
        p = Path(preferred_path).expanduser().resolve()
        if (p / "artisan").exists():
            return p.name, p

    # 1. Check active project from memory
    active = memory_manager.get_active_project()
    if active and active.get("path"):
        cand = Path(active["path"]).expanduser().resolve()
        if (cand / "artisan").exists():
            return active["name"], cand

    # 2. Check registered projects in memory DB or config
    with memory_manager.long_term._lock, memory_manager.long_term._get_connection() as conn:
        rows = conn.execute("SELECT name, path FROM projects").fetchall()
        for r in rows:
            cand = Path(r["path"]).expanduser().resolve()
            if (cand / "artisan").exists():
                logger.info(f"Auto-activating Laravel project '{r['name']}' at {cand}")
                memory_manager.set_active_project(r["name"], str(cand))
                return r["name"], cand

    # 3. Check config.yaml projects
    cfg_projects = get("projects") or {}
    for name, p_str in cfg_projects.items():
        cand = Path(p_str).expanduser().resolve()
        if (cand / "artisan").exists():
            logger.info(f"Auto-activating Laravel project from config '{name}' at {cand}")
            memory_manager.set_active_project(name, str(cand))
            return name, cand

    # 4. Check current root
    if (PROJECT_ROOT / "artisan").exists():
        return PROJECT_ROOT.name, PROJECT_ROOT

    raise RuntimeError(
        "No active Laravel project found in memory. "
        "Please specify or switch to a Laravel project using `set_project_context(name, path)`."
    )


def run_artisan(command: str, project_path: Path | None = None, timeout: int = 60) -> tuple[int, str, str]:
    """
    Run `php artisan <command>` inside the Laravel project directory.

    Returns
    -------
    tuple[int, str, str]
        (returncode, stdout, stderr)
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    artisan_file = project_path / "artisan"
    if not artisan_file.exists():
        return 1, "", f"No artisan file found in {project_path}"

    args = ["php", str(artisan_file)] + shlex.split(command)
    logger.info(f"[Laravel] Executing: {' '.join(args)} in {project_path}")

    # Track in project memory
    try:
        memory_manager.record_command(f"php artisan {command}")
    except Exception:
        pass

    try:
        res = subprocess.run(
            args,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Command 'php artisan {command}' timed out after {timeout} seconds."
    except Exception as exc:
        return 1, "", f"Failed to run artisan command: {exc}"


def run_project_cmd(cmd: list[str] | str, project_path: Path | None = None, timeout: int = 60) -> tuple[int, str, str]:
    """Run an arbitrary command inside the Laravel project directory."""
    if not project_path:
        _, project_path = get_active_laravel_project()

    logger.info(f"[Laravel CMD] {cmd} in {project_path}")
    try:
        if isinstance(cmd, str):
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        else:
            res = subprocess.run(
                cmd,
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s."
    except Exception as exc:
        return 1, "", str(exc)
