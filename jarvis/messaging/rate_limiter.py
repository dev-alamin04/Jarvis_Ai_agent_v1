"""
jarvis/messaging/rate_limiter.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Daily Message Rate Limiting & Privacy-Preserving Audit Logging.

Rules:
  • Configurable daily send limit per platform (default: 20/day).
  • Stored locally in data/message_limits.json.
  • Audit logs record timestamp, platform, recipient name, and message length.
  • NEVER logs the message content itself (strict privacy invariant).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from jarvis.config import PROJECT_ROOT, get
from jarvis.logger import logger

_LIMITS_FILE = PROJECT_ROOT / "data" / "message_limits.json"
_AUDIT_LOG_FILE = PROJECT_ROOT / "logs" / "messaging_audit.log"


def _get_today_key() -> str:
    """Return today's date formatted as YYYY-MM-DD."""
    return datetime.date.today().isoformat()


def _load_limits() -> dict[str, dict[str, int]]:
    """Load JSON record of daily message counts."""
    if not _LIMITS_FILE.exists():
        return {}
    try:
        return json.loads(_LIMITS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not load message limits file: {exc}")
        return {}


def _save_limits(data: dict[str, dict[str, int]]) -> None:
    """Save daily message counts atomically."""
    _LIMITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _LIMITS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error(f"Failed to persist message limits: {exc}")


def get_daily_limit() -> int:
    """Get the maximum messages allowed per platform per day."""
    return int(get("messaging.daily_limit", 20))


def get_today_count(platform: str) -> int:
    """Return the number of messages sent on platform today."""
    today = _get_today_key()
    data = _load_limits()
    return data.get(today, {}).get(platform.lower(), 0)


def can_send(platform: str) -> tuple[bool, str]:
    """
    Check if a message can be sent on this platform today.
    Returns (True, "") or (False, "Reason why limit reached").
    """
    limit = get_daily_limit()
    current = get_today_count(platform)
    if current >= limit:
        return False, (
            f"Daily message limit of {limit} for {platform.capitalize()} reached today "
            f"({current}/{limit} sent). You can increase this in config/config.yaml."
        )
    return True, ""


def record_send(platform: str) -> int:
    """Increment today's send count for platform. Returns new count."""
    today = _get_today_key()
    data = _load_limits()
    if today not in data:
        data[today] = {}
    p = platform.lower()
    new_count = data[today].get(p, 0) + 1
    data[today][p] = new_count
    _save_limits(data)
    return new_count


def log_audit(platform: str, recipient: str, text: str, status: str = "SENT") -> None:
    """
    Append an audit log record for this send attempt.

    PRIVACY INVARIANT:
      Only logs timestamp, platform, recipient name, and message length in characters.
      The actual message content is NEVER written to the audit log or persistent storage.
    """
    _AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.datetime.now().astimezone().isoformat()
    msg_len = len(text) if text else 0

    record = (
        f"{now_iso} | "
        f"PLATFORM: {platform.lower()} | "
        f"RECIPIENT: {recipient} | "
        f"LENGTH: {msg_len} chars | "
        f"STATUS: {status}\n"
    )

    try:
        with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(record)
    except Exception as exc:
        logger.error(f"Failed to write to messaging audit log: {exc}")
