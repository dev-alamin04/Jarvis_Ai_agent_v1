"""
jarvis/devops/ssh_client.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SSH Client and Remote Command Execution Engine.

Key features:
  • Connects over SSH using private key files outside the repo.
  • Secrets (passwords, key bytes) are NEVER stored in memory or logs.
  • Logs EVERY remote command with timestamp and server name to
    logs/remote_commands.log and the tamper-evident cryptographic hash chain.
  • Simulation is ONLY active when JARVIS_MOCK_SSH=1 env var is set or
    force_simulation=True is passed explicitly.  It is NEVER used as a
    silent fallback on connection failure.
  • On connection failure an honest error result is returned (exit code 255)
    so callers can report the problem to the user clearly.
  • Host key verification uses the system known_hosts file; unknown keys are
    rejected and the user is told how to add them manually.
  • Placeholder hosts (127.0.0.1, localhost, *.example.com) are refused so
    that an unconfigured servers.yaml is caught at call time, not silently.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.config import PROJECT_ROOT
from jarvis.devops.config import find_server
from jarvis.logger import logger

REMOTE_COMMANDS_LOG = PROJECT_ROOT / "logs" / "remote_commands.log"

# Hosts that indicate the servers.yaml still has unconfigured placeholder values.
_PLACEHOLDER_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_placeholder_host(host: str) -> bool:
    """Return True if *host* looks like an unconfigured placeholder."""
    return host in _PLACEHOLDER_HOSTS or "example.com" in host


def _scrub_command(cmd: str) -> str:
    """Scrub passwords, tokens, and sensitive flags before writing to logs."""
    cleaned = re.sub(r"(-p|--password=)\s*['\"][^'\"]+['\"]", r"\1 '***'", cmd)
    cleaned = re.sub(r"(-p|--password=)\s*\S+", r"\1 ***", cleaned)
    cleaned = re.sub(r"(token|secret|key|passwd|password)=\S+", r"\1=***", cleaned, flags=re.I)
    cleaned = re.sub(r"(Bearer\s+)\S+", r"\1***", cleaned, flags=re.I)
    cleaned = re.sub(r"(Basic\s+)\S+", r"\1***", cleaned, flags=re.I)
    return cleaned


def log_remote_command(
    server_name: str,
    user: str,
    command: str,
    exit_code: int,
    result_summary: str,
    status: str = "APPROVED",
) -> None:
    """Log remote command with timestamp and server name."""
    REMOTE_COMMANDS_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    scrubbed = _scrub_command(command)

    entry = (
        f"[{timestamp}] [SERVER: {server_name}] [USER: {user}] [STATUS: {status}] "
        f"[EXIT: {exit_code}] [CMD: {scrubbed}] [RESULT: {result_summary[:200]!r}]\n"
    )

    with open(REMOTE_COMMANDS_LOG, "a", encoding="utf-8") as f:
        f.write(entry)

    # Mirror to tamper-evident audit log
    try:
        from jarvis.safety import log_tamper_evident_action
        log_tamper_evident_action(
            tool="devops:remote_command",
            args={"server": server_name, "command": scrubbed},
            result=f"Exit {exit_code}: {result_summary[:200]}",
            status=status,
        )
    except Exception as exc:
        logger.debug(f"Tamper-evident log error: {exc}")


# ---------------------------------------------------------------------------
# Simulation responses — ONLY used when JARVIS_MOCK_SSH=1 or force_simulation
# ---------------------------------------------------------------------------

_SIMULATED_RESPONSES: dict[str, tuple[int, str, str]] = {
    "df -h /": (
        0,
        "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        80G   24G   53G  32% /",
        "",
    ),
    "free -m": (
        0,
        "               total        used        free      shared  buff/cache   available\nMem:            7962        2410        3120         128        2432        5230\nSwap:           2048           0        2048",
        "",
    ),
    "uptime": (
        0,
        " 16:20:00 up 45 days,  3:12,  2 users,  load average: 0.28, 0.35, 0.40",
        "",
    ),
    "systemctl is-active": (
        0,
        "active",
        "",
    ),
    "supervisorctl status": (
        0,
        "mrym-worker:mrym-worker_00   RUNNING   pid 18234, uptime 12 days, 4:10:00\nmrym-worker:mrym-worker_01   RUNNING   pid 18235, uptime 12 days, 4:10:00",
        "",
    ),
    "docker ps": (
        0,
        "mrym-redis: Up 14 days\nmrym-mysql: Up 14 days",
        "",
    ),
    "tail": (
        0,
        "[2026-11-20 15:40:12] production.ERROR: SQLSTATE[HY000] [2002] Connection refused (Connection: mysql, Host: 127.0.0.1, Port: 3306) in /var/www/app/vendor/laravel/framework/src/Illuminate/Database/Connectors/MySqlConnector.php:38\n[2026-11-20 15:40:15] production.ERROR: RedisException: Connection refused in /var/www/app/vendor/predis/predis/src/Connection/StreamConnection.php:128",
        "",
    ),
    "ls -lt": (
        0,
        "-rw-r--r-- 1 root root 148592384 2026-11-20 03:00:00 app_db_backup_20261120.sql.gz\n-rw-r--r-- 1 root root 854932110 2026-11-19 02:00:00 full_site_backup_20261119.tar.gz",
        "",
    ),
}


def _simulate_remote_command(
    server_name: str, user: str, command: str
) -> tuple[int, str, str]:
    """Provide realistic output for mock/test execution (JARVIS_MOCK_SSH=1 only)."""
    cmd_clean = command.strip()

    # Exact or prefix simulated match
    for prefix, resp in _SIMULATED_RESPONSES.items():
        if cmd_clean.startswith(prefix) or prefix in cmd_clean:
            log_remote_command(server_name, user, command, resp[0], resp[1])
            return resp

    # Simulated generic success
    out = f"Simulated output for `{cmd_clean}` on {server_name}"
    log_remote_command(server_name, user, command, 0, out)
    return 0, out, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_remote_command(
    server_name: str,
    command: str,
    timeout: int = 30,
    force_simulation: bool = False,
) -> tuple[int, str, str]:
    """
    Connect to a server over SSH and run a command.

    Returns (exit_code, stdout, stderr).

    Simulation is ONLY used when force_simulation=True or the environment
    variable JARVIS_MOCK_SSH=1 is set.  On any real connection failure a
    result of (255, "", "<descriptive error>") is returned — fake data is
    NEVER substituted silently.

    Raises nothing; all errors are captured in the return value.
    """
    # ── 0. Resolve server config ──────────────────────────────────────────
    server = find_server(server_name)
    if not server:
        err = f"Server `{server_name}` not found in config/servers.yaml."
        logger.warning(f"[SSH Client] {err}")
        return 1, "", err

    host = server.get("host", "127.0.0.1")
    port = int(server.get("port", 22))
    user = server.get("user", "root")
    key_path_raw = server.get("key_path", "~/.ssh/id_rsa")
    key_path = Path(os.path.expanduser(key_path_raw)).resolve()
    canonical_name = server["name"]

    # ── 1. Simulation gate (tests / offline mode only) ────────────────────
    # Check simulation FIRST so that tests with JARVIS_MOCK_SSH=1 can safely
    # use placeholder hosts without being rejected.
    use_simulation = force_simulation or os.environ.get("JARVIS_MOCK_SSH") == "1"
    if use_simulation:
        logger.info(f"[SSH] SIMULATION mode: {canonical_name} — {command[:80]}")
        return _simulate_remote_command(canonical_name, user, command)

    # ── 2. Refuse placeholder / unconfigured hosts (real connections only) ─
    if _is_placeholder_host(host):
        err = (
            f"Server config for '{canonical_name}' still has placeholder values "
            f"(host={host!r}). Please update config/servers.yaml with real server "
            f"details before running SSH commands."
        )
        logger.error(f"[SSH Client] {err}")
        return 255, "", err

    # ── 3. Real SSH execution ─────────────────────────────────────────────
    logger.info(f"[SSH] Executing on {canonical_name} ({user}@{host}:{port}): {command[:100]}")

    try:
        import paramiko

        client = paramiko.SSHClient()

        # Load known_hosts; reject keys not in it rather than accepting blindly.
        known_hosts_path = Path("~/.ssh/known_hosts").expanduser()
        if known_hosts_path.exists():
            try:
                client.load_host_keys(str(known_hosts_path))
            except Exception as kh_exc:
                logger.warning(f"[SSH] Could not load known_hosts ({kh_exc}); proceeding with strict rejection.")

        # RejectPolicy: raise SSHException for any key not already trusted.
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": user,
            "timeout": 5,
        }

        if key_path.exists():
            connect_kwargs["key_filename"] = str(key_path)

        try:
            client.connect(**connect_kwargs)
        except paramiko.ssh_exception.SSHException as ssh_exc:
            client.close()
            # Distinguish "unknown host key" from other SSH errors for a helpful message.
            exc_msg = str(ssh_exc)
            if "not found in known_hosts" in exc_msg or "Server" in exc_msg and "not found" in exc_msg:
                err = (
                    f"SSH connection to '{canonical_name}' ({host}) refused: host key not in known_hosts. "
                    f"To trust this server for the first time, run: "
                    f"ssh-keyscan -H {host} >> ~/.ssh/known_hosts"
                )
            else:
                err = f"SSH connection to '{canonical_name}' ({host}) failed: {exc_msg}"
            logger.error(f"[SSH] {err}")
            log_remote_command(canonical_name, user, command, 255, err, status="FAILED")
            return 255, "", err

        except (socket.error, TimeoutError, OSError, ConnectionRefusedError) as conn_exc:
            client.close()
            err = f"SSH connection to '{canonical_name}' ({host}) failed: {conn_exc}"
            logger.error(f"[SSH] {err}")
            log_remote_command(canonical_name, user, command, 255, err, status="FAILED")
            return 255, "", err

        # ── 4. Run command over channel ───────────────────────────────────
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out_str = stdout.read().decode("utf-8", errors="replace").strip()
            err_str = stderr.read().decode("utf-8", errors="replace").strip()
        finally:
            client.close()

        log_remote_command(
            server_name=canonical_name,
            user=user,
            command=command,
            exit_code=exit_code,
            result_summary=out_str or err_str,
        )
        return exit_code, out_str, err_str

    except Exception as exc:
        # Last-resort catch — log and return an honest error, never fake data.
        err = f"SSH connection to '{canonical_name}' failed: {exc}"
        logger.error(f"[SSH] Unexpected error: {exc}", exc_info=True)
        try:
            log_remote_command(canonical_name, server.get("user", "?"), command, 255, err, status="FAILED")
        except Exception:
            pass
        return 255, "", err
