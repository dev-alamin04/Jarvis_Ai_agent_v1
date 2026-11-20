"""
jarvis/tools/german_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool Registry bridge for German Study Companion:
  start_german_practice, stop_german_practice, get_german_quiz, get_german_study_summary.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.german.companion import (
    generate_quick_quiz as _quiz,
    start_german_session as _start_session,
    stop_german_session as _stop_session,
)
from jarvis.german.voice import format_german_study_summary as _summary


def start_german_practice() -> str:
    """
    Start an interactive German conversation practice session at B1 level.
    Switches speech recognition and TTS language to German.
    """
    return _start_session()


def stop_german_practice() -> str:
    """
    End the current German practice session and return to English conversation.
    """
    return _stop_session()


def get_german_quiz() -> str:
    """
    Generate a quick quiz question based on learned B1 vocabulary and recorded grammar mistakes.
    """
    return _quiz()


def get_german_study_summary() -> str:
    """
    Get a summary of German B1 vocabulary learned, common mistakes recorded, and study statistics.
    """
    return _summary()


__all__ = [
    "start_german_practice",
    "stop_german_practice",
    "get_german_quiz",
    "get_german_study_summary",
]
