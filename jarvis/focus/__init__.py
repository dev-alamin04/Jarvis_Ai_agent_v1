"""
jarvis/focus/__init__.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Jarvis Focus Mode Suite.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.focus.manager import (
    format_focus_summary,
    get_active_focus_session,
    get_focus_summary,
    is_focus_active,
    start_focus_mode,
    stop_focus_mode,
)
from jarvis.focus.voice import handle_focus_voice, match_focus_command
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel

# Register tool risk levels: all focus tools are SAFE
CENTRAL_TOOL_RISK_TABLE["start_focus_mode"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["stop_focus_mode"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["get_focus_summary"] = RiskLevel.SAFE

__all__ = [
    "start_focus_mode",
    "stop_focus_mode",
    "is_focus_active",
    "get_active_focus_session",
    "get_focus_summary",
    "format_focus_summary",
    "match_focus_command",
    "handle_focus_voice",
]
