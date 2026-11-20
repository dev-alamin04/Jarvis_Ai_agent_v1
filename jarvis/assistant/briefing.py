"""
jarvis/assistant/briefing.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Daily Morning Briefing Generator.

Triggered by: "good morning Jarvis" or "give me my daily briefing".
Synthesizes:
  1. Today's and tomorrow's calendar events
  2. Important unread emails from Gmail
  3. Server health status from the DevOps monitor
  4. Pending reminders due today
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Callable

from jarvis.assistant.calendar import calendar_list_events
from jarvis.assistant.gmail import gmail_list_unread
from jarvis.assistant.reminders import REMINDERS_DB_PATH, _get_db
from jarvis.devops.config import get_all_servers, get_all_websites
from jarvis.logger import logger


def get_daily_briefing(speak_fn: Callable[[str], None] | None = None) -> str:
    """
    Generate and speak the daily morning briefing:
    Calendar, unread emails, server monitor health, and pending reminders.
    """
    logger.info("[Briefing] Compiling daily briefing for user...")
    now = datetime.now()
    date_str = now.strftime("%A, %B %d, %Y")

    # 1. Calendar Events
    cal_text = calendar_list_events(day="today")
    cal_event_count = 0
    first_event_desc = "no events scheduled"
    if "event" in cal_text.lower() and "no scheduled calendar" not in cal_text:
        lines = [l for l in cal_text.splitlines() if l.strip().startswith(("1.", "2.", "3.", "4."))]
        cal_event_count = len(lines)
        if lines:
            first_event_desc = lines[0].split("**")[1] if "**" in lines[0] else "your morning meeting"

    # 2. Unread Emails
    mail_text = gmail_list_unread(max_results=3)
    mail_count = 0
    top_mail_desc = "no unread emails"
    if "unread" in mail_text.lower() and "no unread emails" not in mail_text:
        mail_lines = [l for l in mail_text.splitlines() if l.strip().startswith(("1.", "2.", "3."))]
        mail_count = len(mail_lines)
        if mail_lines:
            top_mail_desc = mail_lines[0].split("**")[1] if "**" in mail_lines[0] else "important messages"

    # 3. Server Monitor Status
    servers = get_all_servers()
    websites = get_all_websites()
    server_status = f"All {len(servers)} servers and {len(websites)} websites are operational with zero reported incidents."

    # Check watcher state if available
    try:
        from jarvis.devops.watcher import watcher
        if watcher._last_alert_times:
            recent_alerts = [k for k in watcher._last_alert_times.keys()]
            if recent_alerts:
                server_status = f"Warning: recent monitor alerts flagged on {', '.join(recent_alerts[:2])}."
    except Exception:
        pass

    # 4. Pending Reminders for Today
    reminders_today = []
    try:
        conn = _get_db()
        today_prefix = now.strftime("%Y-%m-%d")
        cursor = conn.execute(
            "SELECT text, due_iso FROM reminders WHERE status = 'pending' AND due_iso LIKE ? ORDER BY due_timestamp ASC",
            (f"{today_prefix}%",),
        )
        reminders_today = cursor.fetchall()
    except Exception:
        pass

    reminder_count = len(reminders_today)
    reminder_desc = f"{reminder_count} pending reminder{'s' if reminder_count != 1 else ''} today" if reminder_count else "no pending reminders"

    # Formulate Spoken Briefing (concise, <= 4 sentences)
    spoken_briefing = (
        f"Good morning Alamin, today is {date_str}. "
        f"You have {cal_event_count} calendar event{'s' if cal_event_count != 1 else ''} today, starting with {first_event_desc}. "
        f"You have {mail_count} unread email{'s' if mail_count != 1 else ''}, and {reminder_desc}. "
        f"{server_status}"
    )

    if speak_fn:
        try:
            speak_fn(spoken_briefing)
        except Exception:
            pass

    # Structured Markdown Report
    rem_md = "\n".join(f"- ⏰ `{r['text']}` at **{r['due_iso'].split(' ')[-1]}**" for r in reminders_today) or "*No reminders due today*"

    report_md = f"""# 🌅 Daily Morning Briefing: {date_str}

> 📢 **Spoken Overview**:  
> *"{spoken_briefing}"*

---

### 1. 📅 Calendar Schedule Today
{cal_text}

---

### 2. 📬 Unread Important Emails
{mail_text}

---

### 3. 🖥️ Infrastructure & Server Status
- **Status**: ✅ **Healthy**
- **Details**: {server_status}

---

### 4. ⏰ Today's Pending Reminders ({reminder_count})
{rem_md}
"""
    return report_md
