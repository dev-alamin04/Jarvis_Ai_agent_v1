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
    "delete_files",
    "overwrite_file",
    "send_message",
}

# Tools that are always safe
_ALWAYS_SAFE_TOOLS: set[str] = {
    "open_app",
    "open_url",
    "play_youtube",
    "read_file",
    "list_directory",
    "read_laravel_log",
    "switch_project",
    "remember_fact",
    "recall_facts",
    "get_project_context",
    "set_project_context",
    # Vision & Screen tools
    "take_screenshot",
    "fix_screen_error",
    # File search & Clipboard tools
    "search_files",
    "read_clipboard",
    "write_clipboard",
    # Browser safe navigation
    "browser_open",
    "browser_search",
    # Mouse & Keyboard non-sensitive controls
    "scroll_screen",
    "type_text",
    "press_hotkey",
    # Laravel Assistant safe tools
    "laravel_debug_and_fix",
    "laravel_run_tests",
    "laravel_write_test",
    "laravel_git_status",
    "laravel_git_diff",
    "laravel_git_create_branch",
    "laravel_git_commit",
    "laravel_git_pr_description",
    "laravel_backup_database",
    "laravel_table_schema",
    "laravel_scaffold",
    "laravel_code_review",
}

# Pattern for strictly blocked environment and secret files
_ENV_SECRET_PATTERN = re.compile(
    r"(^|[/\s\"'])(\.env(?:\.[a-zA-Z0-9_-]+)?|id_rsa|id_ed25519|\.pem|\.key|\.pfx|\.keystore)(?:['\"\s]|$)",
    re.IGNORECASE,
)


def _touches_env_or_secrets(args: dict, command: str = "") -> bool:
    """Detect if any argument or shell command targets .env or secret keys."""
    for val in args.values():
        if isinstance(val, str) and _ENV_SECRET_PATTERN.search(val):
            return True
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and _ENV_SECRET_PATTERN.search(item):
                    return True

    if command and _ENV_SECRET_PATTERN.search(command):
        return True

    return False


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
    # 0. Strict Invariant: Never edit or read .env files or secrets.
    cmd = str(args.get("command", ""))
    if _touches_env_or_secrets(args, command=cmd):
        msg = "Access to .env files and secrets is blocked for security reasons."
        logger.warning(f"BLOCKED — {msg} (tool={tool_name})")
        if speak_fn:
            speak_fn(msg)
        raise PermissionDenied(msg)

    # 1. Always-safe tools: pass through
    if tool_name in _ALWAYS_SAFE_TOOLS:
        return

    # 2. Sending messages on messaging platforms ALWAYS requires explicit spoken confirmation
    if tool_name == "send_message":
        raw_platform = str(args.get("platform", "messaging platform"))
        platform = {"whatsapp": "WhatsApp", "telegram": "Telegram", "messenger": "Facebook Messenger"}.get(
            raw_platform.lower(), raw_platform.capitalize()
        )
        recipient = str(args.get("person_name", "the recipient"))
        text = str(args.get("text", ""))
        custom_prompt = f"Send on {platform} to {recipient}: {text}. Shall I send?"
        _handle_dangerous(
            tool_name,
            args,
            reason=f"delivering message on {platform}",
            speak_fn=speak_fn,
            custom_prompt=custom_prompt,
        )
        return

    # 3. Always-dangerous tools
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

    # 7. Memory deletion requires spoken confirmation
    if tool_name == "forget_fact":
        query = args.get("query", "")
        reason = f"it will delete stored memories matching `{query}`"
        _handle_dangerous(tool_name, args, reason, speak_fn)
        return

    # 8. Mouse clicks in sensitive applications (password managers, banking, terminals running sudo)
    if tool_name in ("click_at", "click_element"):
        desc = str(args.get("description", ""))
        app_name = str(args.get("app_name", ""))
        sensitive = False
        detail = ""
        try:
            from jarvis.tools.computer import is_sensitive_context
            sensitive, detail = is_sensitive_context(description=desc, app_name=app_name)
        except Exception as exc:
            logger.debug(f"is_sensitive_context check error: {exc}")

        if sensitive:
            reason = f"clicking inside a sensitive application or privileged terminal ({detail})"
            _handle_dangerous(tool_name, args, reason, speak_fn)
            return

    # 9. Moving many files (>3 files) requires confirmation
    if tool_name == "move_files":
        sources = args.get("sources", [])
        if len(sources) > 3:
            reason = f"moving {len(sources)} files (bulk file operation)"
            _handle_dangerous(tool_name, args, reason, speak_fn)
            return

    # 10. Submitting forms requires confirmation
    if tool_name == "browser_fill_form":
        if args.get("submit", False) is True:
            reason = "submitting a web form"
            _handle_dangerous(tool_name, args, reason, speak_fn)
            return

    # 11. Laravel Git dangerous operations (Force push, hard reset, branch deletion)
    if tool_name == "laravel_git_push":
        if args.get("force", False) is True:
            branch = args.get("branch") or "current branch"
            _handle_dangerous(tool_name, args, f"force-pushing branch `{branch}` to remote (can overwrite history)", speak_fn)
            return
        return  # Standard non-force push is safe

    if tool_name == "laravel_git_reset_hard":
        target = args.get("target", "HEAD")
        _handle_dangerous(tool_name, args, f"performing a hard git reset to `{target}` (discards uncommitted work)", speak_fn)
        return

    if tool_name == "laravel_git_delete_branch":
        branch = args.get("branch_name", "branch")
        _handle_dangerous(tool_name, args, f"deleting git branch `{branch}`", speak_fn)
        return

    # 12. Laravel Database destructive migrations (fresh, reset, rollback)
    if tool_name == "laravel_run_migrations":
        action = str(args.get("action", "")).lower().strip()
        if action in ("fresh", "reset", "rollback"):
            _handle_dangerous(
                tool_name,
                args,
                f"running destructive migration `{action}` (a database backup will be created first)",
                speak_fn,
            )
            return
        return  # migrate, status are safe


def _handle_dangerous(tool_name: str, args: dict, reason: str, speak_fn, custom_prompt: str | None = None) -> None:
    """
    Announce the dangerous action and wait for user approval.
    Raises PermissionDenied if denied.
    """
    if custom_prompt:
        prompt = custom_prompt
    else:
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
    """Remove any secrets from args before logging (and do not log message text)."""
    sensitive_keys = {"api_key", "password", "secret", "token", "key"}
    scrubbed = {}
    for k, v in args.items():
        if any(s in k.lower() for s in sensitive_keys):
            scrubbed[k] = "***"
        elif k == "text" and "platform" in args:
            # Privacy rule: Never log private message text
            scrubbed[k] = f"<{len(str(v))} chars>"
        else:
            scrubbed[k] = v
    return scrubbed
