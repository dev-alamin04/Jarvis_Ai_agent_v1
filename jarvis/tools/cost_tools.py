"""
jarvis/tools/cost_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool Registry bridge for Cost Tracking tools:
  get_cost_today and get_cost_month.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.cost.voice_commands import handle_cost_inquiry


def get_cost_today() -> str:
    """
    Get the total tokens and estimated spending for today.
    Returns a breakdown of model queries, transcription, and speech synthesis costs.
    """
    return handle_cost_inquiry("how much have I spent today")


def get_cost_month() -> str:
    """
    Get the total tokens and estimated spending for the current month.
    Returns a breakdown of monthly spending against the monthly budget limit.
    """
    return handle_cost_inquiry("how much this month")


__all__ = [
    "get_cost_today",
    "get_cost_month",
]
