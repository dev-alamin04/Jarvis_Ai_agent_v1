"""
jarvis/tools/focus_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool Registry bridge for Focus Mode tools:
  start_focus_mode, stop_focus_mode, get_focus_summary.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.focus.manager import (
    format_focus_summary,
    start_focus_mode as _start_focus,
    stop_focus_mode as _stop_focus,
)


def start_focus_mode(duration_minutes: int = 45) -> str:
    """
    Start a timed focus mode session (default 45 minutes).
    Mutes desktop notifications and keeps quiet except for urgent server alerts.
    """
    return _start_focus(duration_minutes=duration_minutes)


def stop_focus_mode() -> str:
    """
    Stop the current active focus session early and restore desktop notifications.
    """
    return _stop_focus()


def get_focus_summary() -> str:
    """
    Get a summary of focus mode sessions completed today.
    """
    return format_focus_summary()


__all__ = [
    "start_focus_mode",
    "stop_focus_mode",
    "get_focus_summary",
]
