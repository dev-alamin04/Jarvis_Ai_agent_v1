"""
jarvis/tools/system.py
Stage-1 tools: run_shell_command, open_app, open_url.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
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

    # Track in active project history
    try:
        from jarvis.memory import memory_manager
        memory_manager.record_command(command)
    except Exception:
        pass

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


# ── play_youtube ──────────────────────────────────────────────────────────────

def play_youtube(query: str = "") -> str:
    """
    Search YouTube using yt-dlp and open the top video in the default web browser.
    If query is empty or generic 'play music', searches for 'popular songs'.
    """
    cleaned = (query or "").strip()
    if not cleaned or cleaned.lower() in ("play music", "music", "play some music", "songs", "popular music"):
        cleaned = "popular songs"

    logger.info(f"play_youtube: searching for {cleaned!r}")

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--get-id",
        "--no-playlist",
        f"ytsearch1:{cleaned}",
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
        )
        video_id = res.stdout.strip()
        if not video_id or res.returncode != 0:
            err = res.stderr.strip() or "No video found"
            logger.error(f"yt-dlp error: {err}")
            return f"Failed to find a YouTube video for '{cleaned}': {err}"

        # If multiple lines are returned, take the first one
        video_id = video_id.splitlines()[0].strip()
        url = f"https://www.youtube.com/watch?v={video_id}"
        return open_url(url)
    except subprocess.TimeoutExpired:
        return f"Searching YouTube for '{cleaned}' timed out."
    except Exception as exc:
        return f"Failed to play YouTube video: {exc}"
