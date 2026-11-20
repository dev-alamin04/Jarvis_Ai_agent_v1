"""
jarvis/assistant/__init__.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Jarvis Personal Assistant Package.

Exports:
  • Email (Gmail): gmail_list_unread, gmail_read_thread, gmail_draft_reply, gmail_send_email
  • Calendar: calendar_list_events, calendar_add_event, check_upcoming_event_reminders
  • Reminders: add_reminder, list_reminders, cancel_reminder, check_due_reminders
  • Daily Briefing: get_daily_briefing ("good morning Jarvis")
  • Client Messages: client_draft_reply (Fiverr / Upwork / direct)
  • Background Daemon: assistant_daemon, PersonalAssistantDaemon
  • OAuth: get_google_credentials, is_google_authenticated
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.assistant.briefing import get_daily_briefing
from jarvis.assistant.calendar import (
    calendar_add_event,
    calendar_list_events,
    check_upcoming_event_reminders,
)
from jarvis.assistant.client_messages import client_draft_reply
from jarvis.assistant.gmail import (
    gmail_draft_reply,
    gmail_list_unread,
    gmail_read_thread,
    gmail_send_email,
)
from jarvis.assistant.notifier import PersonalAssistantDaemon, assistant_daemon
from jarvis.assistant.oauth import get_google_credentials, is_google_authenticated
from jarvis.assistant.reminders import (
    add_reminder,
    cancel_reminder,
    check_due_reminders,
    list_reminders,
    parse_due_time,
)

# Dynamically register tools in Central Tool Risk Table
try:
    from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel
    CENTRAL_TOOL_RISK_TABLE["gmail_list_unread"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["gmail_read_thread"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["gmail_draft_reply"] = RiskLevel.SAFE
    # Sending email strictly requires spoken confirmation after draft read-aloud
    CENTRAL_TOOL_RISK_TABLE["gmail_send_email"] = RiskLevel.NEEDS_CONFIRMATION
    CENTRAL_TOOL_RISK_TABLE["calendar_list_events"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["calendar_add_event"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["add_reminder"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["list_reminders"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["cancel_reminder"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["get_daily_briefing"] = RiskLevel.SAFE
    CENTRAL_TOOL_RISK_TABLE["client_draft_reply"] = RiskLevel.SAFE
except Exception:
    pass

__all__ = [
    "gmail_list_unread",
    "gmail_read_thread",
    "gmail_draft_reply",
    "gmail_send_email",
    "calendar_list_events",
    "calendar_add_event",
    "check_upcoming_event_reminders",
    "add_reminder",
    "list_reminders",
    "cancel_reminder",
    "check_due_reminders",
    "get_daily_briefing",
    "client_draft_reply",
    "assistant_daemon",
    "PersonalAssistantDaemon",
    "get_google_credentials",
    "is_google_authenticated",
    "parse_due_time",
]
