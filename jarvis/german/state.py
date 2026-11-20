"""
jarvis/german/state.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Session language state for the German Study Companion.

Manages:
  • Active German practice mode flag.
  • STT language switching (Whisper: 'de' vs 'en').
  • Thread-safe state transitions.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import threading

_state_lock = threading.Lock()
_german_mode_active: bool = False


def is_german_mode_active() -> bool:
    """Return True if German practice conversation mode is currently active."""
    with _state_lock:
        return _german_mode_active


def set_german_mode(active: bool) -> None:
    """Enable or disable German practice conversation mode."""
    global _german_mode_active
    with _state_lock:
        _german_mode_active = bool(active)


def get_stt_language() -> str:
    """
    Return the ISO-639-1 language code for speech recognition.
    Returns 'de' during German practice sessions, 'en' otherwise.
    """
    with _state_lock:
        return "de" if _german_mode_active else "en"


def get_stt_prompt() -> str:
    """Return speech recognition contextual prompt based on current language."""
    with _state_lock:
        if _german_mode_active:
            return "Konversation auf Deutsch auf B1-Niveau für Sprachpraxis mit Jarvis."
        return "Voice command for Jarvis desktop assistant."
