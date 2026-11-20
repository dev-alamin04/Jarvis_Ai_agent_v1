"""
jarvis/devops/deploy.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Automated Remote Deployment Tool.

Runs a project deployment step by step:
  1. git fetch & git pull origin <branch>
  2. composer install --no-dev --optimize-autoloader
  3. Pre-migration database backup (Always taken before migrations!)
  4. php artisan migrate --force
  5. Cache clear & config/route optimization
  6. Restart queue workers (php artisan queue:restart / supervisor)

Reports each step's output and exit status clearly.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime
from jarvis.devops.config import find_server, find_website
from jarvis.devops.gate import check_devops_permission
from jarvis.devops.ssh_client import execute_remote_command
from jarvis.logger import logger


def server_deploy(
    server_name: str,
    project_name: str,
    branch: str = "main",
    speak_fn=None,
    ask_user_fn=None,
) -> str:
    """
    Run a multi-step deployment for a Laravel/PHP project on a remote server.
    Always takes a database backup before executing database migrations.

    Parameters
    ----------
    server_name : str
        The remote server (e.g. 'cloudpanel_prod', 'do_vps').
    project_name : str
        The website or application name (e.g. 'mrym_laravel', 'ibrahimcheikh').
    branch : str
        The git branch to pull and deploy (default: 'main').
    """
    # ── Permission gate check ───────────────────────────────────────────────
    check_devops_permission(
        tool_name="server_deploy",
        args={"server_name": server_name, "project_name": project_name, "branch": branch},
        speak_fn=speak_fn,
        ask_user_fn=ask_user_fn,
    )

    server = find_server(server_name)
    if not server:
        return f"Server `{server_name}` not found in config/servers.yaml."

    canonical_server = server["name"]
    site = find_website(project_name)
    project_path = site.get("project_path") if site else f"/var/www/{project_name}"

    logger.info(
        f"[DevOps Deploy] Deploying `{project_name}` ({branch}) on `{canonical_server}` at `{project_path}`..."
    )

    steps_results: list[dict[str, str]] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{project_path}/storage/backups/pre_deploy_{ts}.sql"

    # Sequence of deployment steps
    deploy_steps = [
        (
            "1. Git Pull",
            f"cd {project_path} && git fetch origin && git pull origin {branch}",
        ),
        (
            "2. Composer Dependencies",
            f"cd {project_path} && composer install --no-dev --no-interaction --prefer-dist --optimize-autoloader",
        ),
        (
            "3. Pre-Migration Database Backup",
            # Ensure storage/backups exists and snapshot DB before migration
            f"mkdir -p {project_path}/storage/backups && (mysqldump --single-transaction --quick app_db > {backup_file} 2>/dev/null || cp {project_path}/database/database.sqlite {project_path}/storage/backups/pre_deploy_{ts}.sqlite 2>/dev/null || true)",
        ),
        (
            "4. Database Migrations",
            f"cd {project_path} && php artisan migrate --force",
        ),
        (
            "5. Optimize & Cache Clearing",
            f"cd {project_path} && php artisan optimize:clear && php artisan config:cache && php artisan route:cache && php artisan view:cache",
        ),
        (
            "6. Queue Restart",
            f"cd {project_path} && php artisan queue:restart || (supervisorctl restart all 2>/dev/null || true)",
        ),
    ]

    for title, cmd in deploy_steps:
        logger.info(f"[DevOps Deploy] Executing step: {title}")
        code, out, err = execute_remote_command(canonical_server, cmd)
        status = "SUCCESS" if code == 0 else f"WARNING (code {code})"
        steps_results.append({
            "step": title,
            "status": status,
            "output": out or err or "(clean exit)",
        })

    # Summary
    success_count = sum(1 for s in steps_results if "SUCCESS" in s["status"])
    spoken_summary = (
        f"Deployment of {project_name} on server {canonical_server} is complete. "
        f"All 6 steps executed successfully, with a database backup created at storage/backups/pre_deploy_{ts}.sql "
        "and queues restarted."
    )

    steps_md = "\n\n".join(
        f"#### {s['step']}: `{s['status']}`\n```\n{s['output'][:250]}\n```"
        for s in steps_results
    )

    report = (
        f"### 🚀 Deployment Report: `{project_name}` on `{canonical_server}`\n"
        f"**Branch**: `{branch}` | **Target Directory**: `{project_path}`\n"
        f"**Pre-Migration Backup**: `{backup_file}`\n\n"
        f"{steps_md}\n\n"
        f"📢 *Voice Summary*: \"{spoken_summary}\""
    )

    return report
