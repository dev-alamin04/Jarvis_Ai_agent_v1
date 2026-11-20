"""
jarvis/german/__init__.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
German Study Companion Suite for Jarvis.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.german.companion import (
    generate_quick_quiz,
    get_active_session_info,
    process_german_turn,
    start_german_session,
    stop_german_session,
)
from jarvis.german.state import (
    get_stt_language,
    get_stt_prompt,
    is_german_mode_active,
    set_german_mode,
)
from jarvis.german.store import (
    add_custom_vocabulary,
    get_common_mistakes,
    get_recent_vocabulary,
    get_study_statistics,
    record_mistake,
)
from jarvis.german.voice import (
    format_german_study_summary,
    handle_german_voice,
    match_german_practice_start,
    match_german_quiz,
    match_german_stop,
    match_german_summary,
)
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel

# Register tool risk levels: all German study tools are SAFE
CENTRAL_TOOL_RISK_TABLE["start_german_practice"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["stop_german_practice"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["get_german_quiz"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["get_german_study_summary"] = RiskLevel.SAFE

__all__ = [
    "start_german_session",
    "stop_german_session",
    "process_german_turn",
    "generate_quick_quiz",
    "get_active_session_info",
    "is_german_mode_active",
    "set_german_mode",
    "get_stt_language",
    "get_stt_prompt",
    "record_mistake",
    "get_recent_vocabulary",
    "get_common_mistakes",
    "get_study_statistics",
    "add_custom_vocabulary",
    "match_german_practice_start",
    "match_german_quiz",
    "match_german_stop",
    "match_german_summary",
    "handle_german_voice",
    "format_german_study_summary",
]
