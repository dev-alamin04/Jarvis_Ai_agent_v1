"""
tests/test_personal_assistant.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unit and integration test suite for Jarvis Personal Assistant:
  1. OAuth token protection, file permissions (0600), and credentials security
  2. Gmail: list unread emails, read threads, draft replies
  3. Gmail send email: draft read-aloud verbatim & spoken confirmation gate
  4. Calendar: list events (today/tomorrow), add event from voice
  5. Calendar 10-minute proactive event reminders
  6. Reminders: natural language parser, SQLite persistence across restarts,
     due reminder spoken alerts
  7. Daily Briefing: morning summary combining calendar, email, servers, reminders
  8. Client Messages: drafting Fiverr / client replies in custom tones
  9. Background assistant daemon (reminders + calendar watcher)
  10. Tool registry & Central Tool Risk Table integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
os.environ["JARVIS_TEST_MODE"] = "1"

import json
import re
import stat
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
from jarvis.assistant.oauth import (
    TOKEN_FILE,
    ensure_token_file_permissions,
    is_google_authenticated,
)
from jarvis.assistant.reminders import (
    _get_db,
    add_reminder,
    cancel_reminder,
    check_due_reminders,
    list_reminders,
    parse_due_time,
)
from jarvis.permission_gate import PermissionDenied
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel
from jarvis.tools import TOOL_REGISTRY, get_tool_schemas


# ── 1. OAuth Token Security & Permissions ─────────────────────────────────────

def test_oauth_token_security():
    print("[TEST] OAuth token security and file permissions...")
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        t_path = Path(tf.name)

    try:
        t_path.write_text('{"token": "test_token_secret"}', encoding="utf-8")
        ensure_token_file_permissions(t_path)

        file_stat = t_path.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)

        # Invariant: File must be readable/writable ONLY by the owner (0600)
        assert file_mode & stat.S_IRUSR != 0, "Owner should have read permissions"
        assert file_mode & stat.S_IWUSR != 0, "Owner should have write permissions"
        assert file_mode & stat.S_IRGRP == 0, "Group should NOT have read permissions"
        assert file_mode & stat.S_IROTH == 0, "Others should NOT have read permissions"

        # Verify token file location is under data/tokens/
        assert "data/tokens" in str(TOKEN_FILE)

    finally:
        t_path.unlink(missing_ok=True)

    print("  ✓ OAuth token security and permissions (0600) verified.")


# ── 2. Gmail Unread, Thread, and Draft Reply ──────────────────────────────────

def test_gmail_read_and_draft():
    print("[TEST] Gmail: list unread, read thread, and draft replies...")
    # 1. List unread emails
    unread_res = gmail_list_unread(max_results=3)
    assert "Unread Important Emails" in unread_res
    assert "Fiverr" in unread_res or "Order" in unread_res
    assert "Voice Summary" in unread_res

    # 2. Read thread
    thread_res = gmail_read_thread("msg_001")
    assert "Email:" in thread_res
    assert "Body:" in thread_res
    assert "Voice Summary" in thread_res

    # 3. Create draft reply
    draft_res = gmail_draft_reply(
        to="client@example.com",
        subject="Re: Project Update",
        body="Hi Alex, Everything is on schedule for deployment tomorrow.",
    )
    assert "Draft Created in Gmail" in draft_res
    assert "client@example.com" in draft_res
    assert "Re: Project Update" in draft_res
    assert "Voice Summary" in draft_res

    print("  ✓ Gmail unread, read thread, and drafting verified.")


# ── 3. Gmail Send Email with Spoken Confirmation Gate ─────────────────────────

def test_gmail_send_email_confirmation_gate():
    print("[TEST] Gmail send email: draft read-aloud & spoken confirmation gate...")
    spoken_prompts = []

    def mock_speak(msg):
        spoken_prompts.append(msg)

    # 1. User says "no" -> PermissionDenied
    with pytest.raises(PermissionDenied):
        gmail_send_email(
            to="client@example.com",
            subject="Invoice for Laravel Milestone",
            body="Hi Alex, please find the invoice attached.",
            speak_fn=mock_speak,
            ask_user_fn=lambda _: False,  # User denies
        )

    # Invariant: Draft MUST be read aloud verbatim before asking for confirmation
    assert len(spoken_prompts) > 0
    prompt_text = spoken_prompts[0]
    assert "client@example.com" in prompt_text
    assert "Invoice for Laravel Milestone" in prompt_text
    assert "Hi Alex, please find the invoice attached." in prompt_text
    assert "Shall I send this email?" in prompt_text

    # 2. User says "yes" -> Send email succeeds
    spoken_prompts.clear()
    res = gmail_send_email(
        to="client@example.com",
        subject="Invoice for Laravel Milestone",
        body="Hi Alex, please find the invoice attached.",
        speak_fn=mock_speak,
        ask_user_fn=lambda _: True,  # User approves
    )
    assert "Email Sent Successfully" in res
    assert "client@example.com" in res
    assert "Voice Summary" in res

    print("  ✓ Gmail send email draft read-aloud & confirmation gate verified.")


# ── 4. Calendar Events Listing & Scheduling ───────────────────────────────────

def test_calendar_events_and_scheduling():
    print("[TEST] Calendar: list today/tomorrow events and add event from voice...")
    # 1. List events
    cal_today = calendar_list_events(day="today")
    assert "Calendar Schedule" in cal_today
    assert "Voice Summary" in cal_today

    cal_tomorrow = calendar_list_events(day="tomorrow")
    assert "Calendar Schedule" in cal_tomorrow

    # 2. Schedule new event from natural language
    res_add = calendar_add_event(
        summary="Client Strategy Call",
        start_time="tomorrow at 3pm",
        duration_minutes=45,
        description="Discuss backend milestones",
    )
    assert "Event Scheduled on Calendar" in res_add
    assert "Client Strategy Call" in res_add
    assert "Voice Summary" in res_add

    print("  ✓ Calendar list events and scheduling verified.")


# ── 5. Calendar 10-Minute Proactive Event Reminders ────────────────────────────

def test_calendar_ten_minute_reminders():
    print("[TEST] Calendar 10-minute proactive event reminders...")
    spoken_alerts = []

    def mock_speak(msg):
        spoken_alerts.append(msg)

    # Create mock event starting in 8 minutes
    now = datetime.now()
    event_start = now + timedelta(minutes=8)
    mock_events = [
        {
            "id": "evt_urgent_01",
            "summary": "Livewire Demo with Rahim",
            "start": event_start.strftime("%Y-%m-%d %H:%M:%S"),
        }
    ]

    with patch("jarvis.assistant.calendar._SIMULATED_EVENTS", mock_events):
        alerts = check_upcoming_event_reminders(speak_fn=mock_speak)
        assert len(alerts) > 0
        assert alerts[0]["summary"] == "Livewire Demo with Rahim"
        assert len(spoken_alerts) > 0
        assert "Alamin" in spoken_alerts[0]
        assert "Livewire Demo with Rahim" in spoken_alerts[0]
        assert "10 minutes" in spoken_alerts[0]

        # Invariant: Second check should NOT trigger duplicate alarm
        initial_count = len(spoken_alerts)
        check_upcoming_event_reminders(speak_fn=mock_speak)
        assert len(spoken_alerts) == initial_count

    print("  ✓ Calendar 10-minute proactive event reminders verified.")


# ── 6. Reminders: Natural Language, SQLite, Restarts, Spoken Alerts ───────────

def test_reminders_engine_and_persistence():
    print("[TEST] Reminders: natural language parser, SQLite persistence across restarts...")
    # 1. Test Natural Language Parser
    now = datetime.now()

    # "in 20 minutes"
    ts_20m, iso_20m = parse_due_time("in 20 minutes")
    diff_20m = ts_20m - now.timestamp()
    assert 1180 <= diff_20m <= 1220

    # "in 1 hour"
    ts_1h, _ = parse_due_time("in 1 hour")
    diff_1h = ts_1h - now.timestamp()
    assert 3580 <= diff_1h <= 3620

    # "tomorrow at 9"
    ts_tom, iso_tom = parse_due_time("tomorrow at 9")
    tom_dt = datetime.fromtimestamp(ts_tom)
    assert tom_dt.hour == 9
    assert tom_dt.minute == 0
    assert tom_dt.date() == (now.date() + timedelta(days=1))

    # 2. Add Reminder to SQLite DB
    res_add = add_reminder(text="Check Laravel queue workers", due_time="in 20 minutes")
    assert "Reminder Scheduled" in res_add
    assert "Check Laravel queue workers" in res_add

    # List reminders
    res_list = list_reminders()
    assert "Pending Reminders" in res_list
    assert "Check Laravel queue workers" in res_list

    # 3. Simulate Restart & Due Reminder Triggering
    conn = _get_db()
    with conn:
        # Insert a reminder that was due 5 seconds ago (simulating time passing while Jarvis was restarted)
        past_ts = time.time() - 5
        past_iso = (now - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "INSERT INTO reminders (text, due_timestamp, due_iso, created_at, status) VALUES (?, ?, ?, ?, 'pending')",
            ("Deploy security patch to production", past_ts, past_iso, now.isoformat()),
        )
        urgent_id = cursor.lastrowid

    spoken_reminders = []

    def mock_speak(msg):
        spoken_reminders.append(msg)

    # Check due reminders (survives restart)
    triggered = check_due_reminders(speak_fn=mock_speak)
    assert any(t["text"] == "Deploy security patch to production" for t in triggered)
    assert any("Alamin" in m and "Deploy security patch to production" in m for m in spoken_reminders)

    # Verify status in DB updated to 'completed'
    cursor = conn.execute("SELECT status FROM reminders WHERE id = ?", (urgent_id,))
    row = cursor.fetchone()
    assert row["status"] == "completed"

    # Cancel a reminder
    res_add2 = add_reminder(text="Temporary reminder to cancel", due_time="in 50 minutes")
    m_id = re.search(r"ID #(\d+)", res_add2)
    assert m_id is not None
    rem_id = int(m_id.group(1))

    res_cancel = cancel_reminder(rem_id)
    assert "cancelled" in res_cancel

    print("  ✓ Reminders natural language parsing, SQLite persistence, and spoken alerts verified.")


# ── 7. Daily Briefing ("good morning Jarvis") ──────────────────────────────────

def test_daily_briefing():
    print("[TEST] Daily briefing: morning synthesis of calendar, emails, servers, reminders...")
    spoken_briefings = []

    def mock_speak(msg):
        spoken_briefings.append(msg)

    briefing_md = get_daily_briefing(speak_fn=mock_speak)
    assert "# 🌅 Daily Morning Briefing" in briefing_md
    assert "Calendar Schedule" in briefing_md
    assert "Unread Important Emails" in briefing_md
    assert "Infrastructure & Server Status" in briefing_md
    assert "Pending Reminders" in briefing_md

    # Voice summary brevity and greeting
    assert len(spoken_briefings) > 0
    spoken = spoken_briefings[0]
    assert "Good morning Alamin" in spoken
    assert "calendar event" in spoken
    assert "unread email" in spoken
    assert "server" in spoken.lower()
    sentences = [s.strip() for s in spoken.split(". ") if s.strip()]
    assert len(sentences) <= 5

    print("  ✓ Daily morning briefing verified.")


# ── 8. Client Messages (Fiverr / Client communication) ─────────────────────────

def test_client_draft_reply():
    print("[TEST] Client message drafting in various tones...")
    # 1. Professional and friendly (Fiverr)
    fiverr_draft = client_draft_reply(
        client_name="Alex",
        platform="Fiverr",
        inquiry_or_context="Can you optimize our MySQL queries for the products table?",
        tone="professional and friendly",
    )
    assert "Client Reply Draft: `Alex` (Fiverr)" in fiverr_draft
    assert "professional and friendly" in fiverr_draft
    assert "Alex" in fiverr_draft
    assert "never sends client messages automatically" in fiverr_draft

    # 2. Technical and concise
    tech_draft = client_draft_reply(
        client_name="Sarah",
        platform="Upwork",
        inquiry_or_context="Status on the Redis queue worker setup",
        tone="technical and concise",
    )
    assert "technical and concise" in tech_draft
    assert "Implementation completed and tested on staging" in tech_draft

    # 3. Reassuring tone
    reassure_draft = client_draft_reply(
        client_name="Michael",
        platform="Direct Client",
        inquiry_or_context="The 502 Bad Gateway error on the checkout page",
        tone="reassuring",
    )
    assert "reassuring" in reassure_draft
    assert "Don't worry at all" in reassure_draft

    print("  ✓ Client message drafting in various tones verified.")


# ── 9. Assistant Daemon Loop ──────────────────────────────────────────────────

def test_assistant_daemon():
    print("[TEST] Assistant background daemon polling...")
    daemon = PersonalAssistantDaemon(poll_interval_seconds=1)
    status = daemon.poll_now()
    assert "due_reminders" in status
    assert "calendar_alerts" in status

    # Start and stop cleanly
    daemon.start()
    time.sleep(0.2)
    assert daemon._thread is not None and daemon._thread.is_alive()
    daemon.stop()
    assert not daemon._thread.is_alive()

    print("  ✓ Assistant background daemon verified.")


# ── 10. Tool Registry & Central Tool Risk Table Integration ───────────────────

def test_assistant_tools_and_risk_table():
    print("[TEST] Tool registry and Central Tool Risk Table integration...")
    assistant_tools = [
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

    # Verify in TOOL_REGISTRY
    for t in assistant_tools:
        assert t in TOOL_REGISTRY, f"Tool `{t}` missing from TOOL_REGISTRY"

    # Verify in tool schemas
    schemas = get_tool_schemas()
    schema_names = [s["function"]["name"] for s in schemas]
    for t in assistant_tools:
        assert t in schema_names, f"Tool `{t}` missing from schemas"

    # Verify Central Risk Table
    for t in assistant_tools:
        if t == "gmail_send_email":
            assert CENTRAL_TOOL_RISK_TABLE[t] == RiskLevel.NEEDS_CONFIRMATION
        else:
            assert CENTRAL_TOOL_RISK_TABLE[t] == RiskLevel.SAFE

    print("  ✓ Tool registry and Central Risk Table integration verified.")


if __name__ == "__main__":
    test_oauth_token_security()
    test_gmail_read_and_draft()
    test_gmail_send_email_confirmation_gate()
    test_calendar_events_and_scheduling()
    test_calendar_ten_minute_reminders()
    test_reminders_engine_and_persistence()
    test_daily_briefing()
    test_client_draft_reply()
    test_assistant_daemon()
    test_assistant_tools_and_risk_table()
    print("\n🎉 ALL PERSONAL ASSISTANT TESTS PASSED SUCCESSFULLY! 🎉")
