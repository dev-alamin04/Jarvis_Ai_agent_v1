"""
jarvis/german/voice.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voice commands detector and dispatcher for German Study Companion:
  • "German practice"
  • "German quiz"
  • "stop German practice"
  • "German study summary"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from typing import Callable

from jarvis.german.companion import (
    generate_quick_quiz,
    start_german_session,
    stop_german_session,
)
from jarvis.german.state import is_german_mode_active
from jarvis.german.store import get_common_mistakes, get_recent_vocabulary, get_study_statistics

_START_PRACTICE_PATTERNS = [
    r"german\s+practice",
    r"start\s+german\s+practice",
    r"practice\s+german",
    r"let'?s\s+practice\s+german",
    r"sprechen\s+wir\s+deutsch",
    r"deutsch\s+üben",
    r"deutsch\s+sprechen",
    r"german\s+companion",
]

_QUIZ_PATTERNS = [
    r"german\s+quiz",
    r"quiz\s+me\s+(?:in\s+|on\s+)?german",
    r"quick\s+german\s+quiz",
    r"deutsch\s+quiz",
    r"test\s+my\s+german",
]

_STOP_PATTERNS = [
    r"stop\s+german(?:\s+practice)?",
    r"end\s+german(?:\s+practice)?",
    r"exit\s+german(?:\s+practice)?",
    r"back\s+to\s+english",
    r"switch\s+(?:back\s+)?to\s+english",
    r"aufhören",
    r"genug\s+für\s+heute",
]

_SUMMARY_PATTERNS = [
    r"german\s+(?:study\s+)?summary",
    r"german\s+(?:study\s+)?progress",
    r"how\s+many\s+german\s+words",
    r"german\s+vocabulary\s+list",
    r"german\s+mistakes",
]


def match_german_practice_start(text: str) -> bool:
    """Return True if text matches request to begin German practice."""
    clean = text.lower().strip()
    return any(re.search(p, clean) for p in _START_PRACTICE_PATTERNS)


def match_german_quiz(text: str) -> bool:
    """Return True if text matches request for a German quiz."""
    clean = text.lower().strip()
    return any(re.search(p, clean) for p in _QUIZ_PATTERNS)


def match_german_stop(text: str) -> bool:
    """Return True if text matches request to stop German practice."""
    clean = text.lower().strip()
    return any(re.search(p, clean) for p in _STOP_PATTERNS)


def match_german_summary(text: str) -> bool:
    """Return True if text matches inquiry for German study summary."""
    clean = text.lower().strip()
    return any(re.search(p, clean) for p in _SUMMARY_PATTERNS)


def handle_german_voice(text: str, speak_fn: Callable[[str], None] | None = None) -> str:
    """Dispatch recognized German companion voice command."""
    if match_german_stop(text):
        return stop_german_session(speak_fn=speak_fn)

    if match_german_quiz(text):
        return generate_quick_quiz(speak_fn=speak_fn)

    if match_german_summary(text):
        return format_german_study_summary(speak_fn=speak_fn)

    if match_german_practice_start(text):
        return start_german_session(speak_fn=speak_fn)

    # If already active, treat text as conversational turn
    if is_german_mode_active():
        from jarvis.german.companion import process_german_turn
        return process_german_turn(text, speak_fn=speak_fn)

    return start_german_session(speak_fn=speak_fn)


def format_german_study_summary(speak_fn: Callable[[str], None] | None = None) -> str:
    """Format a summary of vocabulary learned and recorded mistakes."""
    stats = get_study_statistics()
    recent_vocab = get_recent_vocabulary(limit=5)
    mistakes = get_common_mistakes(limit=5)

    vocab_list_str = (
        ", ".join(f"`{v['word']}` ({v['translation']})" for v in recent_vocab)
        if recent_vocab
        else "No words introduced yet."
    )

    spoken = (
        f"Alamin, you have learned {stats['learned_vocabulary']} German B1 vocabulary words so far, "
        f"and we have {stats['recorded_mistakes']} grammar tips saved for quizzes."
    )

    if speak_fn:
        try:
            speak_fn(spoken)
        except Exception:
            pass

    return (
        "### 🇩🇪 German Study Companion Summary\n\n"
        f"- **Learned B1 Vocabulary**: **{stats['learned_vocabulary']} words** (Bank total: {stats['total_vocabulary']})\n"
        f"- **Recent Words**: {vocab_list_str}\n"
        f"- **Grammar Tips Recorded**: **{stats['recorded_mistakes']} items**\n"
        f"- **Current Mode**: {'🇩🇪 German Practice Active' if is_german_mode_active() else '🇬🇧 English Mode'}\n\n"
        f"📢 *Voice Overview*: \"{spoken}\""
    )
