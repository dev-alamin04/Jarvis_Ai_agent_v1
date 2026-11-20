"""
jarvis/devops/health.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Server Health Check Tool.

Connects over SSH and reports:
  • Disk usage, RAM, CPU load averages, and uptime
  • Status of nginx, PHP-FPM, MySQL, Redis
  • Queue worker status (supervisor or background artisan queues)
  • Docker containers status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from typing import Any
from jarvis.devops.config import find_server, get_all_servers
from jarvis.devops.ssh_client import execute_remote_command
from jarvis.logger import logger


def server_health_check(server_name: str) -> str:
    """
    Connect to a server over SSH and inspect its health metrics, services,
    queues, and docker containers.

    Parameters
    ----------
    server_name : str
        The name or alias of the server (e.g. 'cloudpanel_prod', 'do_vps', 'hostinger_vps', or 'all').
    """
    clean_name = server_name.lower().strip()
    if clean_name in ("all", "all_servers", "*"):
        all_servers = get_all_servers()
        if not all_servers:
            return "No servers configured in config/servers.yaml."
        reports = []
        for s in all_servers:
            reports.append(server_health_check(s["name"]))
        return f"# 🖥️ Comprehensive Server Health Report ({len(all_servers)} servers)\n\n" + "\n\n---\n\n".join(reports)

    server = find_server(server_name)
    if not server:
        return f"Server `{server_name}` was not found in config/servers.yaml."

    canonical_name = server["name"]
    logger.info(f"[DevOps Health] Checking health for {canonical_name}...")

    # 1. Disk usage — first call also acts as a connectivity probe.
    disk_rc, disk_out, disk_err = execute_remote_command(canonical_name, "df -h /")

    if disk_rc == 255:
        # SSH connection failed; return an honest error immediately.
        return (
            f"### 🖥️ Health Report: `{canonical_name}`\n"
            f"❌ **Could not connect to {canonical_name}**: {disk_err or 'SSH connection failed.'}\n\n"
            f"I could not retrieve health data because the server is unreachable. "
            f"Please verify that the server is online and your SSH key is correct."
        )

    _ = disk_rc  # already checked above
    disk_usage = "Unknown"
    disk_avail = "Unknown"
    for line in disk_out.splitlines():
        if line.startswith("/"):
            parts = line.split()
            if len(parts) >= 5:
                disk_avail = parts[3]
                disk_usage = parts[4]

    # 2. RAM usage
    _, ram_out, _ = execute_remote_command(canonical_name, "free -m")
    ram_total = "Unknown"
    ram_used = "Unknown"
    ram_percent = "Unknown"
    for line in ram_out.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    tot = int(parts[1])
                    usd = int(parts[2])
                    ram_total = f"{tot} MB"
                    ram_used = f"{usd} MB"
                    ram_percent = f"{int((usd / tot) * 100)}%"
                except Exception:
                    pass

    # 3. CPU Load & Uptime
    _, uptime_out, _ = execute_remote_command(canonical_name, "uptime")
    load_avg = "Unknown"
    uptime_val = "Unknown"
    if "load average" in uptime_out:
        parts = uptime_out.split("load average:")
        if len(parts) == 2:
            load_avg = parts[1].strip()
    m_up = re.search(r"up\s+([^,]+(?:,[^,]+)?)", uptime_out)
    if m_up:
        uptime_val = m_up.group(1).strip()

    # 4. Core Services Status (nginx, php-fpm, mysql, redis, docker)
    configured_services = server.get("services", ["nginx", "mysql", "redis"])
    service_statuses: dict[str, str] = {}
    for svc in configured_services:
        _, svc_out, _ = execute_remote_command(canonical_name, f"systemctl is-active {svc}")
        status = svc_out.strip() or "inactive"
        service_statuses[svc] = "Active (running)" if status == "active" else f"Inactive ({status})"

    # 5. Queue workers status
    _, q_out, _ = execute_remote_command(canonical_name, "supervisorctl status")
    queue_summary = "No supervisor queue workers found"
    if q_out and "RUNNING" in q_out:
        running_count = q_out.count("RUNNING")
        queue_summary = f"{running_count} supervisor queue worker(s) active"
    elif q_out and "error" not in q_out.lower():
        queue_summary = q_out[:120]

    # 6. Docker containers
    _, docker_out, _ = execute_remote_command(canonical_name, "docker ps --format '{{.Names}}: {{.Status}}'")
    docker_summary = "Docker not running or no active containers"
    if docker_out and ":" in docker_out:
        containers = [c.strip() for c in docker_out.splitlines() if c.strip()]
        docker_summary = f"{len(containers)} container(s) active: " + ", ".join(containers[:4])

    # 7. Format Voice Summary (concise, <= 3 sentences)
    active_svcs_count = sum(1 for s in service_statuses.values() if "Active" in s)
    spoken_summary = (
        f"Server {canonical_name} ({server.get('type')}) is up {uptime_val}. "
        f"Disk is at {disk_usage} with {disk_avail} available, RAM is at {ram_percent}, and CPU load average is {load_avg.split(',')[0] if ',' in load_avg else load_avg}. "
        f"{active_svcs_count} of {len(service_statuses)} services are running, and queue status is {queue_summary}."
    )

    # 8. Detailed Markdown Report
    service_lines = "\n".join(f"- **{svc}**: {stat}" for svc, stat in service_statuses.items())
    report = (
        f"### 🖥️ Health Report: `{canonical_name}` ({server.get('type')})\n"
        f"**Host**: `{server.get('user')}@{server.get('host')}` | **Uptime**: {uptime_val}\n\n"
        f"| Metric | Value |\n"
        f"| :--- | :--- |\n"
        f"| **Disk Usage** | `{disk_usage}` used (`{disk_avail}` free) |\n"
        f"| **RAM Usage** | `{ram_used} / {ram_total}` (`{ram_percent}`) |\n"
        f"| **CPU Load** | `{load_avg}` |\n\n"
        f"**Core Services**:\n{service_lines}\n\n"
        f"**Queue Workers**: {queue_summary}\n\n"
        f"**Docker**: {docker_summary}\n\n"
        f"📢 *Voice Summary*: \"{spoken_summary}\""
    )

    return report
