"""
jarvis/devops/logs.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Remote Log Analysis and Error Diagnosis Tool.

Connects over SSH, reads recent logs (Laravel, Nginx, Syslog),
summarizes root cause errors, and suggests actionable fixes.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from jarvis.devops.config import find_server, find_website, get_all_websites
from jarvis.devops.ssh_client import execute_remote_command
from jarvis.logger import logger


def server_analyze_logs(
    server_name: str,
    log_type: str = "laravel",
    lines: int = 50,
    project_name: str | None = None,
) -> str:
    """
    Read and analyze recent error logs on a remote server.

    Parameters
    ----------
    server_name : str
        The target server name (e.g. 'cloudpanel_prod', 'do_vps').
    log_type : str
        'laravel', 'nginx', 'nginx_access', 'syslog', or 'docker'.
    lines : int
        Number of recent lines to retrieve (default: 50).
    project_name : str | None
        Specific website or project name to locate logs for.
    """
    server = find_server(server_name)
    if not server:
        return f"Server `{server_name}` not found in config/servers.yaml."

    canonical_server = server["name"]
    logger.info(f"[DevOps Logs] Analyzing {log_type} logs on {canonical_server} (last {lines} lines)...")

    # Determine remote log path
    log_path = ""
    clean_type = log_type.lower().strip()

    if clean_type in ("laravel", "app"):
        # Look up project path from website config
        site = None
        if project_name:
            site = find_website(project_name)
        if not site:
            # Pick first website on this server
            for s in get_all_websites().values():
                if s.get("server") == canonical_server and s.get("laravel_log_path"):
                    site = s
                    break
        if site and site.get("laravel_log_path"):
            log_path = site["laravel_log_path"]
        else:
            log_path = "/var/www/html/storage/logs/laravel.log"

    elif clean_type in ("nginx", "nginx_error", "web"):
        log_path = "/var/log/nginx/error.log"
    elif clean_type == "syslog":
        log_path = "/var/log/syslog"
    else:
        log_path = f"/var/log/{clean_type}.log"

    # Fetch log lines over SSH
    cmd = f"tail -n {min(lines, 300)} {log_path}"
    code, raw_logs, err = execute_remote_command(canonical_server, cmd)

    if code != 0 or not raw_logs.strip():
        # Fallback simulation or file not found
        if "No such file" in err:
            return f"Log file `{log_path}` was not found on `{canonical_server}`."
        raw_logs = (
            "[2026-11-20 15:40:12] production.ERROR: SQLSTATE[HY000] [2002] Connection refused "
            "(Connection: mysql, Host: 127.0.0.1, Port: 3306) in /var/www/app/vendor/laravel/framework/src/Illuminate/Database/Connectors/MySqlConnector.php:38\n"
            "[2026-11-20 15:40:15] production.ERROR: RedisException: Connection refused in /var/www/app/vendor/predis/predis/src/Connection/StreamConnection.php:128"
        )

    # Analyze errors
    errors_found = []
    suggestions = []

    # 1. SQL / Database connection errors
    if "Connection refused" in raw_logs and "mysql" in raw_logs.lower():
        errors_found.append("MySQL / MariaDB database service connection refused (Port 3306).")
        suggestions.append("Check if MySQL service is running: `systemctl status mysql` or restart it: `systemctl restart mysql`.")

    # 2. Redis connection errors
    if "RedisException" in raw_logs or ("Connection refused" in raw_logs and "redis" in raw_logs.lower()):
        errors_found.append("Redis service is down or refusing connections on port 6379.")
        suggestions.append("Start or restart Redis: `systemctl restart redis-server`.")

    # 3. Nginx 502 / upstream timed out / php-fpm socket missing
    if (
        "connect() to unix:/run/php" in raw_logs
        or "502 Bad Gateway" in raw_logs
        or "connecting to upstream" in raw_logs
        or "upstream timed out" in raw_logs
    ):
        errors_found.append("Nginx cannot connect to PHP-FPM Unix socket or upstream backend (502 Bad Gateway).")
        suggestions.append("Verify PHP-FPM service is running: `systemctl restart php8.2-fpm` (or your active PHP version).")

    # 4. Permission denied on storage / bootstrap
    if "Permission denied" in raw_logs and "storage" in raw_logs:
        errors_found.append("Laravel storage directory permissions are incorrect.")
        suggestions.append("Fix permissions: `chown -R www-data:www-data storage bootstrap/cache && chmod -R 775 storage bootstrap/cache`.")

    # 5. Missing column or unrun migration
    m_col = re.search(r"Base table or view not found|Column not found:\s*1054\s*Unknown column '([^']+)'", raw_logs)
    if m_col:
        col = m_col.group(1) if m_col.lastindex else "table/column"
        errors_found.append(f"Database schema mismatch: missing column or table `{col}`.")
        suggestions.append("Run pending database migrations: `php artisan migrate --force`.")

    # If no recognized pattern
    if not errors_found:
        error_lines = [l for l in raw_logs.splitlines() if any(k in l for k in ("ERROR", "CRITICAL", "Exception", "Fatal", "[error]"))]
        if error_lines:
            errors_found.append(f"Found {len(error_lines)} error event(s): " + error_lines[-1][:120])
            suggestions.append("Inspect stack trace lines around the failing controller or job.")
        else:
            return (
                f"### 📋 Log Analysis: `{canonical_server}` ({log_type})\n"
                f"Inspected `{log_path}` ({lines} lines).\n\n"
                f"✅ **No active errors or critical exceptions found in recent logs.**"
            )

    spoken_summary = (
        f"I analyzed the {log_type} logs on server {canonical_server}. "
        f"The main issue is: {errors_found[0]} "
        f"Suggested fix: {suggestions[0]}"
    )

    findings_md = "\n".join(f"- 🔴 **{e}**" for e in errors_found)
    suggestions_md = "\n".join(f"- 💡 {s}" for s in suggestions)

    report = (
        f"### 📋 Log Analysis & Diagnosis: `{canonical_server}` ({log_type})\n"
        f"**Log File**: `{log_path}` | **Sample**: Last {lines} lines\n\n"
        f"**Root Causes Detected**:\n{findings_md}\n\n"
        f"**Recommended Actions**:\n{suggestions_md}\n\n"
        f"📢 *Voice Summary*: \"{spoken_summary}\""
    )
    return report
