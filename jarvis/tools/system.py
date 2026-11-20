"""
jarvis/tools/system.py
Stage-1 tools: run_shell_command, open_app, open_url.
"""

from __future__ import annotations

import shlex
import subprocess
import urllib.parse
from pathlib import Path

from jarvis.config import APPS, PROJECT_ROOT
from jarvis.logger import logger


# ── run_shell_command ─────────────────────────────────────────────────────────

def run_shell_command(
    command: str,
    working_dir: str | None = None,
    timeout: int = 30,
) -> str:
    """
    Execute a shell command and return combined stdout + stderr.
    The permission gate is applied by the brain before calling this.
    """
    cwd = Path(working_dir).expanduser().resolve() if working_dir else PROJECT_ROOT

    logger.info(f"run_shell_command: {command!r}  cwd={cwd}")

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return output if output else f"(exit code {result.returncode}, no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout} seconds."
    except Exception as exc:
        return f"Error running command: {exc}"


# ── open_app ──────────────────────────────────────────────────────────────────

def open_app(app_name: str, file_or_args: str | None = None) -> str:
    """
    Launch a desktop application. Looks up friendly names from config.
    Falls back to treating app_name as a raw executable.
    """
    # Resolve friendly name → executable
    cmd_base = APPS.get(app_name.lower(), app_name)

    parts = shlex.split(cmd_base)
    if file_or_args:
        parts.append(file_or_args)

    logger.info(f"open_app: {parts}")

    try:
        subprocess.Popen(
            parts,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Launched `{app_name}` successfully."
    except FileNotFoundError:
        return (
            f"Could not find executable for `{app_name}`. "
            f"Is it installed? Tried: {parts[0]!r}"
        )
    except Exception as exc:
        return f"Failed to launch `{app_name}`: {exc}"


# ── open_url ──────────────────────────────────────────────────────────────────

def open_url(url: str) -> str:
    """
    Open a URL in the system default browser using xdg-open.
    Validates that the URL looks like http(s).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return (
            f"Refused to open `{url}`: only http/https URLs are allowed. "
            "Please provide a full URL."
        )

    logger.info(f"open_url: {url}")

    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Opened URL: {url}"
    except Exception as exc:
        return f"Failed to open URL `{url}`: {exc}"
