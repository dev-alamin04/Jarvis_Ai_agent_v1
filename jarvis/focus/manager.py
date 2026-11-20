"""
jarvis/focus/manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Focus Mode Manager for Jarvis.

Features:
  • Starts focus timer for specified duration (e.g. 45 minutes).
  • Mutes Linux desktop notifications (via gsettings / dunstctl).
  • Stays quiet during focus mode except for urgent server alerts.
  • Spoken notification when focus session ends + reminder to take a break.
  • Restores desktop notifications upon session completion or stop.
  • Tracks focus session history in local SQLite database (data/focus.db).
  • Provides daily summary of focus sessions completed today.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jarvis.logger import logger

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
FOCUS_DB_PATH = PROJECT_ROOT / "data" / "focus.db"

_db_lock = threading.Lock()
_active_focus_lock = threading.Lock()
_active_session: dict[str, Any] | None = None
_timer_thread: threading.Thread | None = None
_stop_timer_event = threading.Event()


def _get_db() -> sqlite3.Connection:
    """Initialize and connect to SQLite focus database."""
    FOCUS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(FOCUS_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with _db_lock:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time REAL,
                    end_time REAL,
                    duration_minutes INTEGER,
                    day_key TEXT,
                    status TEXT,
                    completed_at TEXT
                )
            """)
    return conn


def _set_desktop_notifications(enabled: bool) -> None:
    """Mute or unmute desktop notifications on Linux."""
    val = "true" if enabled else "false"
    logger.info(f"[Focus Mode] Setting desktop notification banners to: {val}")

    # 1. GNOME Desktop Notifications
    try:
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", val],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        pass

    # 2. Dunst Notification Daemon (if running)
    try:
        dunst_arg = "false" if enabled else "true"
        subprocess.run(
            ["dunstctl", "set-paused", dunst_arg],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        pass


def is_focus_active() -> bool:
    """Return True if a focus session is currently in progress."""
    with _active_focus_lock:
        return _active_session is not None


def get_active_focus_session() -> dict[str, Any] | None:
    """Get metadata of current active focus session."""
    with _active_focus_lock:
        return dict(_active_session) if _active_session else None


def start_focus_mode(
    duration_minutes: int = 45,
    speak_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Start a focus session for the specified number of minutes.
    Mutes notifications and sets up completion timer.
    """
    global _active_session, _timer_thread

    with _active_focus_lock:
        if _active_session is not None:
            rem_sec = max(0, int(_active_session["end_time"] - time.time()))
            rem_min = rem_sec // 60
            msg = f"A focus session is already active ({rem_min} minutes remaining). Say 'stop focus mode' to end it early."
            if speak_fn:
                speak_fn(msg)
            return msg

        now = time.time()
        end_time = now + (duration_minutes * 60)
        day_key = datetime.now().strftime("%Y-%m-%d")

        _active_session = {
            "start_time": now,
            "end_time": end_time,
            "duration_minutes": duration_minutes,
            "day_key": day_key,
        }

    # Mute notifications
    _set_desktop_notifications(enabled=False)

    # Start timer thread
    _stop_timer_event.clear()

    def _timer_worker():
        target_wait = duration_minutes * 60
        # Check every 0.5s so we can abort quickly if stopped
        start_t = time.time()
        while not _stop_timer_event.is_set():
            elapsed = time.time() - start_t
            if elapsed >= target_wait:
                _on_focus_completed(duration_minutes, speak_fn=speak_fn)
                break
            time.sleep(0.5)

    _timer_thread = threading.Thread(target=_timer_worker, daemon=True, name="focus-timer")
    _timer_thread.start()

    spoken = (
        f"Starting {duration_minutes}-minute focus mode. "
        "Desktop notifications are muted. I will stay quiet except for urgent server alerts."
    )
    logger.info(f"[Focus Mode] {spoken}")
    if speak_fn:
        try:
            speak_fn(spoken)
        except Exception:
            pass

    return (
        f"🎯 **Focus Mode Activated** ({duration_minutes} minutes)\n"
        f"- **Desktop Notifications**: 🔇 Muted\n"
        f"- **Audio Level**: 🤫 Quiet mode (urgent server alerts will still alert you)\n"
        f"- **Ends At**: `{datetime.fromtimestamp(end_time).strftime('%I:%M %p')}`\n\n"
        f"📢 *Voice Notice*: \"{spoken}\""
    )


def _on_focus_completed(
    duration_minutes: int,
    speak_fn: Callable[[str], None] | None = None,
) -> None:
    """Invoked when the focus timer completes successfully."""
    global _active_session

    with _active_focus_lock:
        if _active_session is None:
            return
        session_info = dict(_active_session)
        _active_session = None

    # Unmute desktop notifications
    _set_desktop_notifications(enabled=True)

    # Record in database
    now = datetime.now()
    conn = _get_db()
    with _db_lock:
        with conn:
            conn.execute(
                """
                INSERT INTO focus_sessions
                (start_time, end_time, duration_minutes, day_key, status, completed_at)
                VALUES (?, ?, ?, ?, 'completed', ?)
                """,
                (session_info["start_time"], time.time(), duration_minutes, session_info["day_key"], now.isoformat()),
            )

    spoken = (
        f"Alamin, your {duration_minutes}-minute focus session is complete! "
        "Great work. Time to take a 5-minute break and stretch."
    )
    logger.info(f"[Focus Mode] Completed: {spoken}")

    if speak_fn:
        try:
            speak_fn(spoken)
        except Exception:
            pass


def stop_focus_mode(speak_fn: Callable[[str], None] | None = None) -> str:
    """Stop an active focus session early and restore desktop notifications."""
    global _active_session

    _stop_timer_event.set()

    with _active_focus_lock:
        if _active_session is None:
            msg = "No focus session is currently running."
            if speak_fn:
                speak_fn(msg)
            return msg

        session_info = dict(_active_session)
        _active_session = None

    # Unmute notifications
    _set_desktop_notifications(enabled=True)

    elapsed_minutes = max(1, int((time.time() - session_info["start_time"]) / 60))

    # Record partial session in database
    conn = _get_db()
    with _db_lock:
        with conn:
            conn.execute(
                """
                INSERT INTO focus_sessions
                (start_time, end_time, duration_minutes, day_key, status, completed_at)
                VALUES (?, ?, ?, ?, 'stopped_early', ?)
                """,
                (session_info["start_time"], time.time(), elapsed_minutes, session_info["day_key"], datetime.now().isoformat()),
            )

    spoken = f"Focus mode stopped after {elapsed_minutes} minutes. Desktop notifications restored."
    logger.info(f"[Focus Mode] {spoken}")

    if speak_fn:
        try:
            speak_fn(spoken)
        except Exception:
            pass

    return (
        f"🛑 **Focus Mode Stopped**\n"
        f"- **Elapsed Time**: {elapsed_minutes} minutes\n"
        f"- **Desktop Notifications**: 🔔 Restored\n\n"
        f"📢 *Voice Notice*: \"{spoken}\""
    )


def get_focus_summary(day_key: str | None = None) -> dict[str, Any]:
    """Retrieve count and total minutes of focus sessions for today."""
    target_day = day_key or datetime.now().strftime("%Y-%m-%d")
    conn = _get_db()
    with _db_lock:
        cursor = conn.execute(
            """
            SELECT COUNT(*) as session_count, COALESCE(SUM(duration_minutes), 0) as total_minutes
            FROM focus_sessions
            WHERE day_key = ? AND status = 'completed'
            """,
            (target_day,),
        )
        row = cursor.fetchone()

    count = int(row["session_count"]) if row else 0
    minutes = int(row["total_minutes"]) if row else 0

    return {
        "day_key": target_day,
        "completed_sessions": count,
        "total_minutes": minutes,
        "is_active": is_focus_active(),
    }


def format_focus_summary(speak_fn: Callable[[str], None] | None = None) -> str:
    """Format a spoken and markdown summary of today's focus sessions."""
    summary = get_focus_summary()
    count = summary["completed_sessions"]
    minutes = summary["total_minutes"]

    if count == 0:
        spoken = "You have not completed any focus sessions today yet. Say 'focus mode for 45 minutes' to start one."
    else:
        spoken = (
            f"You have completed {count} focus session{'s' if count != 1 else ''} today, "
            f"totaling {minutes} minutes of deep work."
        )

    if summary["is_active"]:
        spoken += " A focus session is currently active."

    if speak_fn:
        try:
            speak_fn(spoken)
        except Exception:
            pass

    return (
        f"### 🎯 Today's Focus Mode Summary ({summary['day_key']})\n\n"
        f"- **Completed Sessions**: **{count}**\n"
        f"- **Total Focused Time**: **{minutes} minutes** ({round(minutes / 60.0, 1)} hrs)\n"
        f"- **Current Status**: {'🟢 Active' if summary['is_active'] else '⚪ Idle'}\n\n"
        f"📢 *Voice Overview*: \"{spoken}\""
    )
