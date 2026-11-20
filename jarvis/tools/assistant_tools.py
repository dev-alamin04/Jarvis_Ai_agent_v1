"""
jarvis/tools/assistant_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool Registry bridge for Personal Assistant tools:
  Gmail, Google Calendar, Reminders, Daily Briefing, and Client Messaging.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.assistant import (
    add_reminder,
    calendar_add_event,
    calendar_list_events,
    cancel_reminder,
    client_draft_reply,
    get_daily_briefing,
    gmail_draft_reply,
    gmail_list_unread,
    gmail_read_thread,
    gmail_send_email,
    list_reminders,
)

__all__ = [
    "gmail_list_unread",
    "gmail_read_thread",
    "gmail_draft_reply",
    "gmail_send_email",
    "calendar_list_events",
    "calendar_add_event",
    "add_reminder",
    "list_reminders",
    "cancel_reminder",
    "get_daily_briefing",
    "client_draft_reply",
]
