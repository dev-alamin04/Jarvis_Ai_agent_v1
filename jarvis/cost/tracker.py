"""
jarvis/cost/tracker.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cost & Token Tracker for Jarvis.

Tracks:
  • Token counts and USD costs for all LLM calls (gpt-4o, gpt-4o-mini, etc.)
  • Audio durations and USD costs for Whisper speech-to-text
  • Character counts and USD costs for OpenAI TTS speech generation
  • Local SQLite database persistence (daily and monthly totals)
  • Real-time UI synchronization via ui_events
  • 80% voice warning and 100% hard limit enforcement
  • STRICT SECURITY: NEVER logs or stores OpenAI API keys.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jarvis.cost.config import (
    get_cheaper_model,
    get_daily_limit,
    get_hard_limit_threshold,
    get_monthly_limit,
    get_rates,
    get_warning_threshold,
)
from jarvis.logger import logger
from jarvis import ui_events

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DB_PATH = PROJECT_ROOT / "data" / "cost.db"

_db_lock = threading.Lock()
_warned_daily_80: set[str] = set()    # Set of day_keys that have been warned
_warned_monthly_80: set[str] = set()  # Set of month_keys that have been warned


def _sanitize_secrets(text: str) -> str:
    """Ensure no API keys (sk-...) or tokens are logged or persisted."""
    if not text:
        return ""
    # Redact OpenAI API keys
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED_API_KEY]", str(text))
    # Redact current environment key if present
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key and len(env_key) > 6:
        sanitized = sanitized.replace(env_key, "[REDACTED_API_KEY]")
    return sanitized


def _get_db() -> sqlite3.Connection:
    """Initialize and connect to SQLite cost database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with _db_lock:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cost_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    iso_timestamp TEXT,
                    event_type TEXT,
                    model TEXT,
                    input_units REAL,
                    output_units REAL,
                    cost_usd REAL,
                    day_key TEXT,
                    month_key TEXT,
                    details TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_totals (
                    day_key TEXT PRIMARY KEY,
                    total_cost REAL DEFAULT 0.0,
                    model_cost REAL DEFAULT 0.0,
                    transcription_cost REAL DEFAULT 0.0,
                    speech_cost REAL DEFAULT 0.0,
                    total_tokens INTEGER DEFAULT 0,
                    call_count INTEGER DEFAULT 0,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_totals (
                    month_key TEXT PRIMARY KEY,
                    total_cost REAL DEFAULT 0.0,
                    model_cost REAL DEFAULT 0.0,
                    transcription_cost REAL DEFAULT 0.0,
                    speech_cost REAL DEFAULT 0.0,
                    total_tokens INTEGER DEFAULT 0,
                    call_count INTEGER DEFAULT 0,
                    updated_at TEXT
                )
            """)
    return conn


def calculate_model_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in USD for a model completion."""
    rates = get_rates()
    clean_model = model.lower().strip()
    rate_info = rates.get(clean_model, rates.get("gpt-4o-mini", {}))

    prompt_rate = rate_info.get("prompt_per_million", 0.15)
    completion_rate = rate_info.get("completion_per_million", 0.60)

    prompt_cost = (prompt_tokens / 1_000_000.0) * prompt_rate
    completion_cost = (completion_tokens / 1_000_000.0) * completion_rate
    return round(prompt_cost + completion_cost, 6)


def calculate_transcription_cost(audio_seconds: float, model: str = "whisper-1") -> float:
    """Calculate cost in USD for audio transcription."""
    rates = get_rates()
    clean_model = model.lower().strip()
    rate_info = rates.get(clean_model, rates.get("whisper-1", {}))
    per_minute = rate_info.get("per_minute", 0.006)

    duration_minutes = max(audio_seconds, 0.0) / 60.0
    return round(duration_minutes * per_minute, 6)


def calculate_speech_cost(chars: int, model: str = "tts-1") -> float:
    """Calculate cost in USD for text-to-speech generation."""
    rates = get_rates()
    clean_model = model.lower().strip()
    rate_info = rates.get(clean_model, rates.get("tts-1", {}))
    per_million = rate_info.get("per_million_chars", 15.00)

    return round((max(chars, 0) / 1_000_000.0) * per_million, 6)


def _record_event(
    event_type: str,
    model: str,
    input_units: float,
    output_units: float,
    cost_usd: float,
    tokens: int = 0,
    details: dict | None = None,
    speak_fn: Callable[[str], None] | None = None,
) -> float:
    """Record a cost event and update daily & monthly totals."""
    now = datetime.now()
    day_key = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    ts = now.timestamp()
    iso_ts = now.isoformat()

    sanitized_details = _sanitize_secrets(json.dumps(details or {}))

    conn = _get_db()
    with _db_lock:
        with conn:
            # 1. Insert detailed event
            conn.execute(
                """
                INSERT INTO cost_events 
                (timestamp, iso_timestamp, event_type, model, input_units, output_units, cost_usd, day_key, month_key, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, iso_ts, event_type, model, input_units, output_units, cost_usd, day_key, month_key, sanitized_details),
            )

            # 2. Update daily totals
            m_cost = cost_usd if event_type == "model" else 0.0
            t_cost = cost_usd if event_type == "transcription" else 0.0
            s_cost = cost_usd if event_type == "speech" else 0.0

            conn.execute(
                """
                INSERT INTO daily_totals 
                (day_key, total_cost, model_cost, transcription_cost, speech_cost, total_tokens, call_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(day_key) DO UPDATE SET
                    total_cost = total_cost + excluded.total_cost,
                    model_cost = model_cost + excluded.model_cost,
                    transcription_cost = transcription_cost + excluded.transcription_cost,
                    speech_cost = speech_cost + excluded.speech_cost,
                    total_tokens = total_tokens + excluded.total_tokens,
                    call_count = call_count + 1,
                    updated_at = excluded.updated_at
                """,
                (day_key, cost_usd, m_cost, t_cost, s_cost, tokens, iso_ts),
            )

            # 3. Update monthly totals
            conn.execute(
                """
                INSERT INTO monthly_totals 
                (month_key, total_cost, model_cost, transcription_cost, speech_cost, total_tokens, call_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(month_key) DO UPDATE SET
                    total_cost = total_cost + excluded.total_cost,
                    model_cost = model_cost + excluded.model_cost,
                    transcription_cost = transcription_cost + excluded.transcription_cost,
                    speech_cost = speech_cost + excluded.speech_cost,
                    total_tokens = total_tokens + excluded.total_tokens,
                    call_count = call_count + 1,
                    updated_at = excluded.updated_at
                """,
                (month_key, cost_usd, m_cost, t_cost, s_cost, tokens, iso_ts),
            )

    # 4. Check budget warnings and notify UI
    check_and_notify_thresholds(speak_fn=speak_fn)
    return cost_usd


def track_model_call(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    details: dict | None = None,
    speak_fn: Callable[[str], None] | None = None,
) -> float:
    """Track token usage and estimated cost for an LLM call."""
    cost = calculate_model_cost(model, prompt_tokens, completion_tokens)
    total_tokens = prompt_tokens + completion_tokens
    logger.info(
        f"[Cost Tracker] Model `{model}`: {prompt_tokens} prompt + {completion_tokens} completion = "
        f"{total_tokens} tokens (~${cost:.5f})"
    )
    return _record_event(
        event_type="model",
        model=model,
        input_units=prompt_tokens,
        output_units=completion_tokens,
        cost_usd=cost,
        tokens=total_tokens,
        details=details,
        speak_fn=speak_fn,
    )


def track_transcription(
    audio_seconds: float,
    model: str = "whisper-1",
    details: dict | None = None,
    speak_fn: Callable[[str], None] | None = None,
) -> float:
    """Track audio transcription duration and estimated cost."""
    cost = calculate_transcription_cost(audio_seconds, model)
    logger.info(
        f"[Cost Tracker] Transcription `{model}`: {audio_seconds:.2f}s audio (~${cost:.5f})"
    )
    return _record_event(
        event_type="transcription",
        model=model,
        input_units=audio_seconds,
        output_units=0.0,
        cost_usd=cost,
        tokens=0,
        details=details,
        speak_fn=speak_fn,
    )


def track_speech(
    text_or_chars: str | int,
    model: str = "tts-1",
    details: dict | None = None,
    speak_fn: Callable[[str], None] | None = None,
) -> float:
    """Track speech synthesis character count and estimated cost."""
    chars = len(text_or_chars) if isinstance(text_or_chars, str) else int(text_or_chars)
    cost = calculate_speech_cost(chars, model)
    logger.info(
        f"[Cost Tracker] Speech `{model}`: {chars} characters (~${cost:.5f})"
    )
    return _record_event(
        event_type="speech",
        model=model,
        input_units=chars,
        output_units=0.0,
        cost_usd=cost,
        tokens=0,
        details=details,
        speak_fn=speak_fn,
    )


def get_cost_today(day_key: str | None = None) -> dict[str, Any]:
    """Retrieve cost and token totals for today (or specified day_key)."""
    target_day = day_key or datetime.now().strftime("%Y-%m-%d")
    conn = _get_db()
    with _db_lock:
        cursor = conn.execute("SELECT * FROM daily_totals WHERE day_key = ?", (target_day,))
        row = cursor.fetchone()

    daily_limit = get_daily_limit()
    if not row:
        return {
            "day_key": target_day,
            "total_cost": 0.0,
            "model_cost": 0.0,
            "transcription_cost": 0.0,
            "speech_cost": 0.0,
            "total_tokens": 0,
            "call_count": 0,
            "daily_limit": daily_limit,
            "percent_used": 0.0,
        }

    total_cost = float(row["total_cost"])
    pct_used = (total_cost / daily_limit * 100.0) if daily_limit > 0 else 0.0

    return {
        "day_key": row["day_key"],
        "total_cost": round(total_cost, 6),
        "model_cost": round(float(row["model_cost"]), 6),
        "transcription_cost": round(float(row["transcription_cost"]), 6),
        "speech_cost": round(float(row["speech_cost"]), 6),
        "total_tokens": int(row["total_tokens"]),
        "call_count": int(row["call_count"]),
        "daily_limit": daily_limit,
        "percent_used": round(pct_used, 1),
    }


def get_cost_month(month_key: str | None = None) -> dict[str, Any]:
    """Retrieve cost and token totals for the current month (or specified month_key)."""
    target_month = month_key or datetime.now().strftime("%Y-%m")
    conn = _get_db()
    with _db_lock:
        cursor = conn.execute("SELECT * FROM monthly_totals WHERE month_key = ?", (target_month,))
        row = cursor.fetchone()

    monthly_limit = get_monthly_limit()
    if not row:
        return {
            "month_key": target_month,
            "total_cost": 0.0,
            "model_cost": 0.0,
            "transcription_cost": 0.0,
            "speech_cost": 0.0,
            "total_tokens": 0,
            "call_count": 0,
            "monthly_limit": monthly_limit,
            "percent_used": 0.0,
        }

    total_cost = float(row["total_cost"])
    pct_used = (total_cost / monthly_limit * 100.0) if monthly_limit > 0 else 0.0

    return {
        "month_key": row["month_key"],
        "total_cost": round(total_cost, 6),
        "model_cost": round(float(row["model_cost"]), 6),
        "transcription_cost": round(float(row["transcription_cost"]), 6),
        "speech_cost": round(float(row["speech_cost"]), 6),
        "total_tokens": int(row["total_tokens"]),
        "call_count": int(row["call_count"]),
        "monthly_limit": monthly_limit,
        "percent_used": round(pct_used, 1),
    }


def is_hard_limit_reached() -> bool:
    """Return True if daily limit or monthly limit has reached 100%."""
    today = get_cost_today()
    month = get_cost_month()
    hard_thresh = get_hard_limit_threshold()

    daily_ratio = today["total_cost"] / today["daily_limit"] if today["daily_limit"] > 0 else 0.0
    monthly_ratio = month["total_cost"] / month["monthly_limit"] if month["monthly_limit"] > 0 else 0.0

    return daily_ratio >= hard_thresh or monthly_ratio >= hard_thresh


def check_and_notify_thresholds(speak_fn: Callable[[str], None] | None = None) -> dict[str, Any]:
    """
    Check spending thresholds (80% warning and 100% hard limit).
    Emits real-time WebSocket events for the UI and warns by voice at 80%.
    """
    global _warned_daily_80, _warned_monthly_80

    today = get_cost_today()
    month = get_cost_month()

    warn_thresh = get_warning_threshold()
    hard_thresh = get_hard_limit_threshold()

    day_key = today["day_key"]
    month_key = month["month_key"]

    daily_ratio = today["total_cost"] / today["daily_limit"] if today["daily_limit"] > 0 else 0.0
    monthly_ratio = month["total_cost"] / month["monthly_limit"] if month["monthly_limit"] > 0 else 0.0

    # Determine UI warning tags
    daily_warn = "normal"
    if daily_ratio >= hard_thresh:
        daily_warn = "limit"
    elif daily_ratio >= warn_thresh:
        daily_warn = "warn"

    monthly_warn = "normal"
    if monthly_ratio >= hard_thresh:
        monthly_warn = "limit"
    elif monthly_ratio >= warn_thresh:
        monthly_warn = "warn"

    # Emit real-time UI cost update
    try:
        ui_events.emit(
            "cost",
            today=f"${today['total_cost']:.2f}",
            month=f"${month['total_cost']:.2f}",
            today_cost=today["total_cost"],
            month_cost=month["total_cost"],
            daily_limit=today["daily_limit"],
            monthly_limit=month["monthly_limit"],
            daily_warn=daily_warn,
            monthly_warn=monthly_warn,
        )
    except Exception as exc:
        logger.debug(f"[Cost Tracker] UI emit error: {exc}")

    # Voice warning at 80%
    warning_spoken = None
    if daily_ratio >= warn_thresh and day_key not in _warned_daily_80:
        _warned_daily_80.add(day_key)
        warning_spoken = (
            f"Alamin, you have reached {int(daily_ratio * 100)}% of your daily spending limit. "
            f"You have spent ${today['total_cost']:.2f} of your ${today['daily_limit']:.2f} budget."
        )
        logger.warning(f"[Cost Limit Alert] {warning_spoken}")
        if speak_fn:
            try:
                speak_fn(warning_spoken)
            except Exception:
                pass

    if monthly_ratio >= warn_thresh and month_key not in _warned_monthly_80:
        _warned_monthly_80.add(month_key)
        warning_spoken = (
            f"Alamin, you have reached {int(monthly_ratio * 100)}% of your monthly spending limit. "
            f"You have spent ${month['total_cost']:.2f} of your ${month['monthly_limit']:.2f} budget."
        )
        logger.warning(f"[Cost Limit Alert] {warning_spoken}")
        if speak_fn:
            try:
                speak_fn(warning_spoken)
            except Exception:
                pass

    return {
        "daily_ratio": daily_ratio,
        "monthly_ratio": monthly_ratio,
        "daily_warn": daily_warn,
        "monthly_warn": monthly_warn,
        "warning_spoken": warning_spoken,
        "hard_limit_reached": (daily_ratio >= hard_thresh or monthly_ratio >= hard_thresh),
    }


def reset_threshold_warnings() -> None:
    """Reset warned cache (primarily for tests)."""
    global _warned_daily_80, _warned_monthly_80
    _warned_daily_80.clear()
    _warned_monthly_80.clear()
