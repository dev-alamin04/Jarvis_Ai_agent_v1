"""
jarvis/cost/__init__.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Jarvis Cost Tracking & Spending Limits Suite.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.cost.config import (
    get_cheaper_model,
    get_daily_limit,
    get_expensive_tools,
    get_monthly_limit,
    get_rates,
    load_cost_config,
)
from jarvis.cost.gate import check_expensive_action_confirmation
from jarvis.cost.tracker import (
    calculate_model_cost,
    calculate_speech_cost,
    calculate_transcription_cost,
    check_and_notify_thresholds,
    get_cost_month,
    get_cost_today,
    is_hard_limit_reached,
    reset_threshold_warnings,
    track_model_call,
    track_speech,
    track_transcription,
)
from jarvis.cost.voice_commands import (
    handle_cost_inquiry,
    is_cost_inquiry,
)
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel

# Register tool risk classifications: querying costs is always SAFE
CENTRAL_TOOL_RISK_TABLE["get_cost_today"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["get_cost_month"] = RiskLevel.SAFE

__all__ = [
    "load_cost_config",
    "get_daily_limit",
    "get_monthly_limit",
    "get_cheaper_model",
    "get_expensive_tools",
    "get_rates",
    "track_model_call",
    "track_transcription",
    "track_speech",
    "calculate_model_cost",
    "calculate_transcription_cost",
    "calculate_speech_cost",
    "get_cost_today",
    "get_cost_month",
    "is_hard_limit_reached",
    "check_and_notify_thresholds",
    "reset_threshold_warnings",
    "is_cost_inquiry",
    "handle_cost_inquiry",
    "check_expensive_action_confirmation",
]
