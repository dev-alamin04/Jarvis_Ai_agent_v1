"""
jarvis/routines/voice.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Natural language voice commands handler for Routines:
  • Trigger matching: "work mode", "end of day", "server check", custom routines
  • Routine creation: "make a routine called study mode that opens..."
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from typing import Any, Callable

from jarvis.logger import logger
from jarvis.routines.config import get_routine
from jarvis.routines.creator import create_routine
from jarvis.routines.executor import execute_routine


_CREATE_PATTERNS = [
    # "make a routine called study mode that opens chrome to google.com"
    r"^(?:make|create|add|set\s*up)\s+(?:a\s+)?routine\s+(?:called|named)\s+['\"]?([a-zA-Z0-9_\-\s]+?)['\"]?\s+that\s+(.+)$",
    # "new routine study mode that opens ..."
    r"^new\s+routine\s+(?:called|named\s+)?['\"]?([a-zA-Z0-9_\-\s]+?)['\"]?\s+that\s+(.+)$",
]


def is_create_routine_command(user_text: str) -> bool:
    """Return True if user text matches a routine creation request."""
    clean = user_text.strip()
    for pat in _CREATE_PATTERNS:
        if re.search(pat, clean, flags=re.IGNORECASE):
            return True
    return False


def match_routine_trigger(user_text: str) -> dict[str, Any] | None:
    """
    Check if user text matches any registered routine trigger phrase.
    e.g. 'work mode', 'end of day', 'check all servers'.
    """
    clean = user_text.strip()

    # Check for direct 'run routine <name>' or 'start routine <name>'
    m_direct = re.match(r"^(?:run|start|execute)\s+(?:the\s+)?(?:routine\s+)?['\"]?([a-zA-Z0-9_\-\s]+?)['\"]?$", clean, flags=re.IGNORECASE)
    if m_direct:
        name_cand = m_direct.group(1).strip()
        found = get_routine(name_cand)
        if found:
            return found

    # Check trigger phrases across all routines
    found = get_routine(clean)
    if found:
        return found

    return None


def handle_create_routine_voice(
    user_text: str,
    speak_fn: Callable[[str], None] | None = None,
    ask_user_fn: Callable[[str], bool] | None = None,
) -> str:
    """Handle voice creation of a routine with readback and confirmation."""
    clean = user_text.strip()
    for pat in _CREATE_PATTERNS:
        m = re.search(pat, clean, flags=re.IGNORECASE)
        if m:
            routine_name = m.group(1).strip()
            steps_desc = m.group(2).strip()
            return create_routine(
                name=routine_name,
                steps_description=steps_desc,
                speak_fn=speak_fn,
                ask_user_fn=ask_user_fn,
            )

    return f"I could not parse the routine name and steps from: '{user_text}'."


def handle_run_routine_voice(
    routine: dict[str, Any],
    speak_fn: Callable[[str], None] | None = None,
    ask_user_fn: Callable[[str], bool] | None = None,
) -> str:
    """Execute a matched routine from voice."""
    return execute_routine(
        name_or_routine=routine,
        speak_fn=speak_fn,
        ask_user_fn=ask_user_fn,
    )
