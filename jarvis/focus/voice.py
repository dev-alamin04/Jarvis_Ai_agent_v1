"""
jarvis/focus/voice.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voice commands handler for Focus Mode:
  • "focus mode for 45 minutes"
  • "how many focus sessions today"
  • "stop focus mode"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from typing import Callable

from jarvis.focus.manager import (
    format_focus_summary,
    start_focus_mode,
    stop_focus_mode,
)


_START_FOCUS_PATTERN = re.compile(
    r"(?:start\s+)?focus\s*(?:mode)?\s*(?:for\s+(\d+)\s*(?:minutes?|mins?)?)?",
    re.IGNORECASE,
)

_SUMMARY_PATTERNS = [
    r"how many focus sessions",
    r"focus (?:sessions? )?today",
    r"focus summary",
    r"focus mode summary",
]

_STOP_PATTERNS = [
    r"stop focus(?: mode)?",
    r"end focus(?: mode)?",
    r"cancel focus(?: mode)?",
]


def match_focus_command(text: str) -> bool:
    """Return True if text matches any focus mode command."""
    clean = text.lower().strip()
    if any(re.search(p, clean) for p in _STOP_PATTERNS):
        return True
    if any(re.search(p, clean) for p in _SUMMARY_PATTERNS):
        return True
    if "focus" in clean and ("mode" in clean or "minute" in clean or "start" in clean):
        return True
    return False


def handle_focus_voice(text: str, speak_fn: Callable[[str], None] | None = None) -> str:
    """Handle focus mode voice commands."""
    clean = text.lower().strip()

    # 1. Stop focus mode
    if any(re.search(p, clean) for p in _STOP_PATTERNS):
        return stop_focus_mode(speak_fn=speak_fn)

    # 2. Focus summary
    if any(re.search(p, clean) for p in _SUMMARY_PATTERNS):
        return format_focus_summary(speak_fn=speak_fn)

    # 3. Start focus mode (with duration parsing)
    m = _START_FOCUS_PATTERN.search(clean)
    duration = 45
    if m and m.group(1):
        try:
            duration = int(m.group(1))
        except ValueError:
            duration = 45

    return start_focus_mode(duration_minutes=duration, speak_fn=speak_fn)
