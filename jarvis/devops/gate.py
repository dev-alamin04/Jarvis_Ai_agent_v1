"""
jarvis/devops/gate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DevOps Permission Gate.

Enforces user-specified rules:
  1. Read-only commands run freely (health check, backup inspection, logs).
  2. Restarting services, deploying, editing server files, and anything with
     sudo require spoken confirmation.
  3. Deleting data, dropping databases, and firewall changes require spoken
     confirmation with the EXACT command read aloud first.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from typing import Callable
from jarvis.logger import logger
from jarvis.permission_gate import PermissionDenied, _ask_user

# High-risk patterns requiring exact command announcement aloud first
_DESTRUCTIVE_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|\s)", re.I),
    re.compile(r"\bshred\b", re.I),
    re.compile(r"\bdrop\s+database\b", re.I),
    re.compile(r"\btruncate\b", re.I),
    re.compile(r"\bufw\b", re.I),
    re.compile(r"\biptables\b", re.I),
    re.compile(r"\bfirewall-cmd\b", re.I),
    re.compile(r"\bmkfs\b", re.I),
]

_STATE_CHANGING_COMMAND_PATTERNS = [
    re.compile(r"\bsudo\b", re.I),
    re.compile(r"\bsystemctl\s+(restart|stop|disable)\b", re.I),
    re.compile(r"\bservice\s+\S+\s+(restart|stop)\b", re.I),
    re.compile(r"\bcomposer\s+install\b", re.I),
    re.compile(r"\bphp\s+artisan\s+migrate\b", re.I),
    re.compile(r"\bgit\s+pull\b", re.I),
]


def is_destructive_remote_command(command: str) -> tuple[bool, str]:
    """Check if remote command deletes data, drops databases, or modifies firewall."""
    for pat in _DESTRUCTIVE_COMMAND_PATTERNS:
        if pat.search(command):
            return True, pat.pattern
    return False, ""


def is_state_changing_remote_command(command: str) -> tuple[bool, str]:
    """Check if command modifies services, uses sudo, or alters state."""
    for pat in _STATE_CHANGING_COMMAND_PATTERNS:
        if pat.search(command):
            return True, pat.pattern
    return False, ""


def check_devops_permission(
    tool_name: str,
    args: dict,
    speak_fn: Callable[[str], None] | None = None,
    ask_user_fn: Callable[[str], bool] | None = None,
) -> None:
    """
    Evaluate DevOps tool invocation and prompt for approval where required.
    Raises PermissionDenied if denied.
    """
    ask = ask_user_fn or _ask_user

    # 1. Read-only tools run completely freely
    if tool_name in (
        "server_health_check",
        "server_check_backups",
        "server_analyze_logs",
        "server_list_sites",
    ):
        return

    server = args.get("server_name") or args.get("server") or "remote server"

    # 2. Destructive data, DB drop, firewall: EXACT command read aloud first
    if tool_name == "server_run_remote_command":
        cmd = str(args.get("command", ""))
        is_destr, reason = is_destructive_remote_command(cmd)
        if is_destr:
            prompt = (
                f"Dangerous remote action detected on server `{server}`. "
                f"I am about to run exact command: '{cmd}'. Do you approve?"
            )
            logger.warning(f"[DevOps Gate] {prompt}")
            if speak_fn:
                speak_fn(f"Dangerous remote action on {server}. Command: {cmd}. Do you approve?")
            if not ask(prompt):
                raise PermissionDenied(f"Remote command on `{server}` was denied by user: '{cmd}'")
            return

        # Sudo or state-changing command confirmation
        is_state, s_reason = is_state_changing_remote_command(cmd)
        if is_state:
            prompt = (
                f"I want to run state-changing remote command on server `{server}`: "
                f"'{cmd}'. Do you approve?"
            )
            logger.warning(f"[DevOps Gate] {prompt}")
            if speak_fn:
                speak_fn(f"I want to run remote command on {server}: {cmd}. Do you approve?")
            if not ask(prompt):
                raise PermissionDenied(f"Remote command on `{server}` was denied by user: '{cmd}'")
            return

    # 3. Restarting services requires spoken confirmation
    if tool_name == "server_restart_service":
        service = args.get("service", "service")
        prompt = f"I want to restart `{service}` on server `{server}`. Do you approve?"
        logger.warning(f"[DevOps Gate] {prompt}")
        if speak_fn:
            speak_fn(prompt)
        if not ask(prompt):
            raise PermissionDenied(f"Service restart of `{service}` on `{server}` was denied.")
        return

    # 4. Deploying project requires spoken confirmation
    if tool_name == "server_deploy":
        proj = args.get("project_name", "project")
        branch = args.get("branch", "main")
        prompt = (
            f"I want to deploy project `{proj}` (branch `{branch}`) to server `{server}` "
            f"(pre-migration database backup will be taken). Do you approve?"
        )
        logger.warning(f"[DevOps Gate] {prompt}")
        if speak_fn:
            speak_fn(prompt)
        if not ask(prompt):
            raise PermissionDenied(f"Deploy of `{proj}` on `{server}` was denied.")
        return

    # 5. Editing server files requires spoken confirmation
    if tool_name == "server_edit_file":
        path = args.get("file_path", "file")
        prompt = f"I want to edit remote file `{path}` on server `{server}`. Do you approve?"
        logger.warning(f"[DevOps Gate] {prompt}")
        if speak_fn:
            speak_fn(prompt)
        if not ask(prompt):
            raise PermissionDenied(f"Remote file edit on `{server}` ({path}) was denied.")
        return
