"""
jarvis/permission_gate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOCKED MODULE — the agent (brain) must never modify, disable, or bypass this
file. The self-update system enforces this invariant at the git level.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Classifies every tool call and either:
  • lets it run immediately (SAFE), or
  • asks the user for spoken/typed confirmation (DANGEROUS).

The gate is the single choke-point between the brain's decisions and the OS.
"""

import re
import sys
from pathlib import Path

from jarvis.config import PROTECTED_PATHS
from jarvis.logger import logger

# ── Dangerous pattern rules ──────────────────────────────────────────────────

# Shell-command patterns that require confirmation
_DANGEROUS_SHELL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\b"),                   # remove files
    re.compile(r"\bmv\b"),                   # move (can overwrite)
    re.compile(r"\bdd\b"),                   # disk dump
    re.compile(r"\bchmod\b"),                # permission change
    re.compile(r"\bchown\b"),                # ownership change
    re.compile(r"\bsudo\b"),                 # privilege escalation
    re.compile(r"\bkill\b"),                 # kill processes
    re.compile(r"\bpkill\b"),
    re.compile(r"\bkillall\b"),
    re.compile(r"\bsystemctl\s+(stop|disable|mask)\b"),
    re.compile(r"\bgit\s+push\s+.*--force"),  # force push
    re.compile(r"\bgit\s+reset\s+--hard"),    # hard reset
    re.compile(r"\bdrop\s+database\b", re.I), # drop DB
    re.compile(r"\btruncate\b", re.I),        # truncate table
    re.compile(r">\s*\S+"),                   # output redirect (overwrite)
    re.compile(r"\bshred\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bparted\b"),
    re.compile(r"\bfdisk\b"),
    re.compile(r"\bformat\b"),
]

# Tools that are always dangerous regardless of arguments
_ALWAYS_DANGEROUS_TOOLS: set[str] = {
    "delete_file",
    "overwrite_file",
}

# Tools that are always safe
_ALWAYS_SAFE_TOOLS: set[str] = {
    "open_app",
    "open_url",
    "read_file",
    "list_directory",
    "read_laravel_log",
    "switch_project",
}


# ── Path protection ──────────────────────────────────────────────────────────

def _touches_protected_path(args: dict) -> str | None:
    """
    Returns the matched protected path if any arg value starts with a
    protected path, else None.
    """
    for protected in PROTECTED_PATHS:
        p = Path(protected).expanduser().resolve()
        for val in args.values():
            if isinstance(val, str):
                try:
                    candidate = Path(val).expanduser().resolve()
                    if candidate == p or p in candidate.parents:
                        return str(p)
                except Exception:
                    pass
    return None


# ── Shell command classification ─────────────────────────────────────────────

def _shell_is_dangerous(command: str) -> str | None:
    """
    Returns a human-readable reason if the command is dangerous, else None.
    """
    for pattern in _DANGEROUS_SHELL_PATTERNS:
        if pattern.search(command):
            return f"matches dangerous pattern `{pattern.pattern}`"
    return None


# ── Public interface ─────────────────────────────────────────────────────────

class PermissionDenied(Exception):
    """Raised when the user denies a dangerous action."""


def _ask_user(prompt: str) -> bool:
    """
    Ask the user for confirmation. In text mode this is a simple stdin prompt.
    In voice mode, the brain replaces this with a spoken prompt + spoken reply.
    Returns True if the user approves.
    """
    # The voice layer monkey-patches this function at startup; the text
    # fallback below is used during Stage 1 (text-only mode).
    print(f"\n⚠️  PERMISSION REQUIRED: {prompt}")
    try:
        answer = input("   Type 'yes' to approve, anything else to deny: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("yes", "y")


def check(tool_name: str, args: dict, speak_fn=None) -> None:
    """
    Evaluate a tool call before execution.

    Parameters
    ----------
    tool_name : str
        The registered tool name.
    args : dict
        The arguments the brain wants to pass to the tool.
    speak_fn : callable | None
        If provided, used to voice the permission request (Stage 2+).

    Raises
    ------
    PermissionDenied
        If the action is dangerous and the user does not approve.
    """
    # 1. Always-safe tools: pass through
    if tool_name in _ALWAYS_SAFE_TOOLS:
        return

    # 2. Always-dangerous tools
    if tool_name in _ALWAYS_DANGEROUS_TOOLS:
        reason = f"tool `{tool_name}` is always restricted"
        _handle_dangerous(tool_name, args, reason, speak_fn)
        return

    # 3. Protected path check (applies to all tools)
    protected = _touches_protected_path(args)
    if protected:
        reason = f"path is inside protected location `{protected}`"
        _handle_dangerous(tool_name, args, reason, speak_fn)
        return

    # 4. Shell command pattern check
    if tool_name == "run_shell_command":
        command = args.get("command", "")
        danger = _shell_is_dangerous(command)
        if danger:
            reason = f"shell command {danger}"
            _handle_dangerous(tool_name, args, reason, speak_fn)
            return

    # 5. Write / edit tools require confirmation
    if tool_name in ("write_file", "edit_file"):
        reason = f"tool `{tool_name}` will modify the filesystem"
        _handle_dangerous(tool_name, args, reason, speak_fn)
        return

    # 6. Service control: stop/disable is dangerous
    if tool_name == "control_service":
        action = args.get("action", "").lower()
        if action in ("stop", "disable", "kill"):
            reason = f"stopping/disabling a service (`{args.get('service', '?')}`)"
            _handle_dangerous(tool_name, args, reason, speak_fn)
            return


def _handle_dangerous(tool_name: str, args: dict, reason: str, speak_fn) -> None:
    """
    Announce the dangerous action and wait for user approval.
    Raises PermissionDenied if denied.
    """
    prompt = (
        f"I want to run `{tool_name}` because {reason}. "
        f"Arguments: {_scrub(args)}. Do you approve?"
    )
    logger.warning(f"PERMISSION CHECK — {prompt}")

    if speak_fn:
        speak_fn(prompt)

    approved = _ask_user(prompt)
    if not approved:
        logger.warning(f"DENIED — {tool_name} with args {_scrub(args)}")
        raise PermissionDenied(
            f"Action `{tool_name}` was denied by the user."
        )

    logger.info(f"APPROVED — {tool_name} with args {_scrub(args)}")


def _scrub(args: dict) -> dict:
    """Remove any secrets from args before logging."""
    sensitive_keys = {"api_key", "password", "secret", "token", "key"}
    return {
        k: ("***" if any(s in k.lower() for s in sensitive_keys) else v)
        for k, v in args.items()
    }
