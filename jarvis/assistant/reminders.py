"""
jarvis/assistant/reminders.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Persistent Reminders and Timers Engine.

Features:
  • Stores reminders locally in data/reminders.db (SQLite)
  • Natural language due time parser:
      - "in 20 minutes", "in 1 hour", "in 45 seconds"
      - "tomorrow at 9", "tomorrow at 14:30"
      - "today at 18:00", "at 5pm"
  • Spoken voice announcement when due, persisting across restarts.
  • Catches up on overdue reminders immediately after startup.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

REMINDERS_DB_PATH = PROJECT_ROOT / "data" / "reminders.db"


def _get_db() -> sqlite3.Connection:
    """Initialize and return SQLite connection for reminders."""
    REMINDERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(REMINDERS_DB_PATH))
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                due_timestamp REAL NOT NULL,
                due_iso TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status_due ON reminders(status, due_timestamp)")
    return conn


def parse_due_time(due_time_str: str) -> tuple[float, str]:
    """
    Parse natural language relative or absolute due time into
    (unix_timestamp, readable_iso_string).
    """
    s = due_time_str.strip().lower()
    now = datetime.now()

    # 1. Relative: "in X minutes", "in X hours", "in X seconds"
    m_rel = re.search(r"in\s+(\d+)\s*(m|min|minute|minutes|h|hr|hour|hours|s|sec|second|seconds)", s)
    if m_rel:
        val = int(m_rel.group(1))
        unit = m_rel.group(2)
        if unit.startswith("m"):
            delta = timedelta(minutes=val)
        elif unit.startswith("h"):
            delta = timedelta(hours=val)
        else:
            delta = timedelta(seconds=val)
        target_dt = now + delta
        return target_dt.timestamp(), target_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 2. "tomorrow at H[:M] [am|pm]"
    if "tomorrow" in s:
        target_date = now.date() + timedelta(days=1)
        # Extract time
        m_time = re.search(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s.replace("tomorrow", ""))
        if m_time:
            hour = int(m_time.group(1))
            minute = int(m_time.group(2)) if m_time.group(2) else 0
            meridiem = m_time.group(3)
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            target_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
            return target_dt.timestamp(), target_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            # Default tomorrow at 9:00 AM
            target_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=9, minute=0)
            return target_dt.timestamp(), target_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 3. "today at H[:M] [am|pm]" or "at H[:M] [am|pm]"
    m_today = re.search(r"(?:today\s+)?(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if m_today and m_today.group(1):
        hour = int(m_today.group(1))
        minute = int(m_today.group(2)) if m_today.group(2) else 0
        meridiem = m_today.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        target_dt = datetime.combine(now.date(), datetime.min.time()).replace(hour=hour, minute=minute)
        if target_dt <= now:
            # If specified time today has already passed, schedule for tomorrow
            target_dt += timedelta(days=1)
        return target_dt.timestamp(), target_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 4. Standard ISO or date format
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            target_dt = datetime.strptime(s, fmt)
            return target_dt.timestamp(), target_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    # Default fallback: 1 hour from now
    target_dt = now + timedelta(hours=1)
    return target_dt.timestamp(), target_dt.strftime("%Y-%m-%d %H:%M:%S")


def add_reminder(text: str, due_time: str) -> str:
    """
    Set a local persistent reminder or timer.
    Examples: 'check the oven' due 'in 20 minutes', or 'call client' due 'tomorrow at 9'.
    """
    due_ts, readable_due = parse_due_time(due_time)
    created_at = datetime.now(timezone.utc).isoformat()

    conn = _get_db()
    with conn:
        cursor = conn.execute(
            "INSERT INTO reminders (text, due_timestamp, due_iso, created_at, status) VALUES (?, ?, ?, ?, 'pending')",
            (text.strip(), due_ts, readable_due, created_at),
        )
        reminder_id = cursor.lastrowid

    logger.info(f"[Reminders] Created reminder #{reminder_id}: '{text}' due at {readable_due}")
    msg = f"Reminder set for {readable_due}: \"{text}\""
    return f"⏰ **Reminder Scheduled (ID #{reminder_id})**:\n\"{text}\"\n**Due**: {readable_due}\n\n📢 *Voice Summary*: \"{msg}\""


def list_reminders(include_completed: bool = False) -> str:
    """List pending reminders, sorted by due time."""
    conn = _get_db()
    query = "SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_timestamp ASC"
    if include_completed:
        query = "SELECT * FROM reminders ORDER BY due_timestamp DESC LIMIT 25"

    cursor = conn.execute(query)
    rows = cursor.fetchall()

    if not rows:
        return "⏰ You have no pending reminders."

    now_ts = time.time()
    lines = []
    for r in rows:
        diff_secs = r["due_timestamp"] - now_ts
        if diff_secs < 0:
            rel = "overdue"
        elif diff_secs < 3600:
            rel = f"in {int(diff_secs / 60)} min"
        elif diff_secs < 86400:
            rel = f"in {int(diff_secs / 3600)} hour(s)"
        else:
            rel = f"in {int(diff_secs / 86400)} day(s)"

        stat_icon = "⏳" if r["status"] == "pending" else "✅"
        lines.append(f"- **#{r['id']}** {stat_icon} `{r['text']}` — Due **{r['due_iso']}** ({rel})")

    count = len(rows)
    spoken_summary = f"You have {count} pending reminder{'s' if count != 1 else ''}. The next one is: {rows[0]['text']}."

    return (
        f"### ⏰ Pending Reminders ({count})\n\n"
        + "\n".join(lines)
        + f"\n\n📢 *Voice Summary*: \"{spoken_summary}\""
    )


def cancel_reminder(reminder_id: int) -> str:
    """Cancel a pending reminder by ID."""
    conn = _get_db()
    with conn:
        cursor = conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
            (reminder_id,),
        )
        if cursor.rowcount > 0:
            logger.info(f"[Reminders] Cancelled reminder #{reminder_id}")
            return f"✅ Reminder #{reminder_id} has been cancelled."
        else:
            return f"Reminder #{reminder_id} not found or was already completed."


def check_due_reminders(speak_fn: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
    """
    Check for due reminders in the database.
    Speaks each due reminder aloud and marks it as completed.
    Returns list of triggered reminders.
    """
    now_ts = time.time()
    conn = _get_db()
    cursor = conn.execute(
        "SELECT * FROM reminders WHERE status = 'pending' AND due_timestamp <= ? ORDER BY due_timestamp ASC",
        (now_ts,),
    )
    due_rows = cursor.fetchall()
    triggered = []

    for r in due_rows:
        r_id = r["id"]
        text = r["text"]
        logger.info(f"[Reminders] Reminder #{r_id} is DUE: '{text}'")

        spoken_msg = f"Alamin, here is your reminder: {text}"

        # Speak reminder aloud (stay quiet during focus mode)
        from jarvis.focus.manager import is_focus_active
        if is_focus_active():
            logger.info(f"[Reminders] Focus mode active - staying quiet: {spoken_msg}")
        elif speak_fn:
            try:
                speak_fn(spoken_msg)
            except Exception as exc:
                logger.debug(f"[Reminders] Speak error: {exc}")
        elif os.environ.get("JARVIS_TEST_MODE") != "1":
            try:
                from jarvis.voice_output import speak
                speak(spoken_msg)
            except Exception:
                pass

        # Mark as completed in DB
        with conn:
            conn.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (r_id,))

        triggered.append({"id": r_id, "text": text, "due_iso": r["due_iso"], "spoken": spoken_msg})

    return triggered
