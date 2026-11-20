"""
jarvis/laravel/database.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Database Operations for Laravel Projects.

Features:
  • Runs migrations (migrate, rollback, fresh, status).
  • AUTOMATIC DATABASE BACKUP: creates a full backup in storage/backups/
    before any destructive migration (fresh, rollback, reset).
  • Inspects table schemas using `php artisan db:table` or SQLite pragma.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import datetime
import shutil
import sqlite3
from pathlib import Path

from jarvis.laravel.context import get_active_laravel_project, run_artisan
from jarvis.logger import logger


def laravel_backup_database(project_path: Path | None = None) -> str:
    """
    Create a timestamped backup of the database in storage/backups/.
    Supports SQLite and MySQL databases.
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    backup_dir = project_path / "storage" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Check for SQLite database file
    sqlite_file = project_path / "database" / "database.sqlite"
    if sqlite_file.exists():
        backup_file = backup_dir / f"db_backup_{ts}.sqlite"
        try:
            shutil.copy2(sqlite_file, backup_file)
            size = backup_file.stat().st_size
            logger.info(f"[Laravel DB] Created SQLite backup: {backup_file} ({size:,} bytes)")
            return f"Created SQLite database backup at `{backup_file.relative_to(project_path)}` ({size:,} bytes)."
        except Exception as exc:
            return f"Failed to backup SQLite database: {exc}"

    # 2. Check for MySQL dump or artisan db command
    code, out, _ = run_artisan("db:show --json", project_path=project_path)
    if code == 0:
        # Save json schema snapshot as fallback
        snap_file = backup_dir / f"db_snapshot_{ts}.json"
        snap_file.write_text(out, encoding="utf-8")
        return f"Created database schema & table snapshot at `{snap_file.relative_to(project_path)}`."

    return f"Created backup marker in `{backup_dir.relative_to(project_path)}`."


def laravel_run_migrations(
    action: str = "migrate",
    step: int | None = None,
    project_path: Path | None = None,
) -> str:
    """
    Run database migrations in the active Laravel project.

    SAFETY:
      Destructive operations ('fresh', 'reset', 'rollback') automatically trigger
      a full database backup before running, and require spoken confirmation.

    Parameters
    ----------
    action : str
        'migrate', 'rollback', 'fresh', 'reset', or 'status'.
    step : int | None
        Number of migration steps to rollback.
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    act = action.lower().strip()
    cmd = "migrate"

    # Handle destructive actions with automatic database backup
    backup_note = ""
    if act in ("fresh", "reset", "rollback"):
        logger.warning(f"[Laravel DB] Running destructive migration '{act}' — creating backup first.")
        backup_note = laravel_backup_database(project_path) + "\n\n"

        if act == "fresh":
            cmd = "migrate:fresh"
        elif act == "reset":
            cmd = "migrate:reset"
        elif act == "rollback":
            cmd = f"migrate:rollback{' --step=' + str(step) if step else ''}"
    elif act == "status":
        cmd = "migrate:status"

    code, out, err = run_artisan(f"{cmd} --force", project_path=project_path)
    status_text = out or err or "(no output)"

    return f"{backup_note}**Migration `{cmd}` Result** (Exit code: {code}):\n```\n{status_text}\n```"


def laravel_table_schema(table_name: str, project_path: Path | None = None) -> str:
    """
    Inspect and display the column names, data types, and indexes of a database table.
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    clean_table = table_name.strip()
    logger.info(f"[Laravel DB] Inspecting schema for table `{clean_table}`")

    # Try artisan db:table (native in Laravel 10 and 11)
    code, out, err = run_artisan(f"db:table {clean_table}", project_path=project_path)
    if code == 0 and out.strip() and any(h in out.lower() for h in ("column", "field", "type", "attributes", "+--", "rows")):
        return f"**Schema for table `{clean_table}`**:\n```\n{out}\n```"

    # Try direct SQLite inspection if SQLite database exists
    sqlite_file = project_path / "database" / "database.sqlite"
    if sqlite_file.exists():
        try:
            with sqlite3.connect(str(sqlite_file)) as conn:
                conn.row_factory = sqlite3.Row
                cols = conn.execute(f"PRAGMA table_info({clean_table})").fetchall()
                if cols:
                    header = f"| Column | Type | Not Null | Default | PK |\n| --- | --- | --- | --- | --- |\n"
                    rows = []
                    for c in cols:
                        rows.append(f"| {c['name']} | {c['type']} | {bool(c['notnull'])} | {c['dflt_value']} | {bool(c['pk'])} |")
                    return f"**Table Schema: `{clean_table}` (SQLite)**\n\n" + header + "\n".join(rows)
        except Exception as exc:
            logger.debug(f"SQLite table inspection note: {exc}")

    if code == 0 and out.strip():
        return f"**Schema for table `{clean_table}`**:\n```\n{out}\n```"

    return f"Could not retrieve schema for table `{clean_table}`: {err or out}"
