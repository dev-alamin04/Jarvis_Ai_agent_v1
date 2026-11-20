"""
jarvis/devops/services.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DevOps Service Control and Remote Command Runner.

Provides:
  • server_restart_service: restarts systemd services (nginx, php-fpm, mysql, etc.)
  • server_run_remote_command: runs arbitrary remote commands with permission checks
  • server_list_sites: lists configured servers and websites with URLs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.devops.config import find_server, get_all_servers, get_all_websites
from jarvis.devops.gate import check_devops_permission
from jarvis.devops.ssh_client import execute_remote_command
from jarvis.logger import logger


def server_restart_service(
    server_name: str,
    service: str,
    speak_fn=None,
    ask_user_fn=None,
) -> str:
    """
    Restart a system service (e.g. nginx, php8.2-fpm, mysql, redis) on a remote server.
    Requires spoken confirmation via the DevOps Permission Gate.

    Parameters
    ----------
    server_name : str
        Target server name (e.g. 'cloudpanel_prod', 'do_vps').
    service : str
        Service name to restart (e.g. 'nginx', 'php8.2-fpm', 'mysql', 'redis').
    """
    check_devops_permission(
        tool_name="server_restart_service",
        args={"server_name": server_name, "service": service},
        speak_fn=speak_fn,
        ask_user_fn=ask_user_fn,
    )

    server = find_server(server_name)
    if not server:
        return f"Server `{server_name}` not found in config/servers.yaml."

    canonical = server["name"]
    cmd = f"sudo systemctl restart {service}"
    logger.info(f"[DevOps Services] Restarting `{service}` on `{canonical}`...")

    code, out, err = execute_remote_command(canonical, cmd)
    if code == 0:
        msg = f"Service `{service}` successfully restarted on `{canonical}`."
        return f"✅ **Success**: {msg}"
    else:
        return f"❌ **Failed** to restart `{service}` on `{canonical}` (Exit code {code}): {err or out}"


def server_run_remote_command(
    server_name: str,
    command: str,
    speak_fn=None,
    ask_user_fn=None,
) -> str:
    """
    Run an arbitrary shell command on a remote server over SSH.
    Dangerous commands (rm, drop database, ufw) require spoken confirmation
    with the exact command read aloud first.

    Parameters
    ----------
    server_name : str
        Target server name.
    command : str
        The shell command to execute.
    """
    check_devops_permission(
        tool_name="server_run_remote_command",
        args={"server_name": server_name, "command": command},
        speak_fn=speak_fn,
        ask_user_fn=ask_user_fn,
    )

    server = find_server(server_name)
    if not server:
        return f"Server `{server_name}` not found in config/servers.yaml."

    canonical = server["name"]
    code, out, err = execute_remote_command(canonical, command)
    return f"**Remote Command Result (`{canonical}`)** (Exit code {code}):\n```\n{out or err or '(no output)'}\n```"


def server_list_sites(server_name: str | None = None) -> str:
    """
    List configured remote servers and websites with URLs.
    """
    servers = get_all_servers()
    websites = get_all_websites()

    server_rows = []
    for s_name, s in servers.items():
        server_rows.append(f"| **{s_name}** | `{s.get('type')}` | `{s.get('user')}@{s.get('host')}` | {', '.join(s.get('services', []))} |")

    website_rows = []
    for w_name, w in websites.items():
        if server_name and w.get("server", "").lower() != server_name.lower():
            continue
        website_rows.append(f"| **{w_name}** | [{w.get('url')}]({w.get('url')}) | `{w.get('server')}` | `{w.get('project_path')}` |")

    servers_table = (
        "### 🖥️ Configured Servers\n\n"
        "| Name | Type | Host | Services |\n"
        "| :--- | :--- | :--- | :--- |\n"
        + "\n".join(server_rows)
    )

    websites_table = (
        "### 🌐 Monitored Websites\n\n"
        "| Name | URL | Server | Project Path |\n"
        "| :--- | :--- | :--- | :--- |\n"
        + "\n".join(website_rows)
    )

    return f"{servers_table}\n\n{websites_table}"
