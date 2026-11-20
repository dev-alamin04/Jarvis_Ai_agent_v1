"""
jarvis/audio_state.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shared audio state flags used by multiple modules:
  - wake word listener
  - voice input recorder
  - voice output (TTS player)

All flags use threading.Event so they are thread-safe and zero-cost to poll.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import threading
import time
from typing import Callable

# Set while the TTS engine is playing audio → mic ignored to prevent self-triggering
speaking = threading.Event()

# Timestamp of when speaking finished (for 0.7 second tail drop)
last_spoke_time: float = 0.0

# Set while the user wants the mic fully muted (mute hotkey toggled)
muted = threading.Event()

# Set while a command is actively being recorded after wake word
recording = threading.Event()

# Set when user interrupts ongoing speech (e.g. saying 'stop' or 'quiet')
interrupted = threading.Event()

# Set to signal the wake word thread to stop cleanly (shutdown)
shutdown = threading.Event()

_flush_callbacks: list[Callable[[], None]] = []


def is_speaking(tail_s: float = 0.7) -> bool:
    """Return True if speaking or within tail_s seconds after speaking ends."""
    if speaking.is_set():
        return True
    if tail_s > 0 and (time.time() - last_spoke_time) < tail_s:
        return True
    return False


def mark_speaking_ended() -> None:
    """Mark speaking as ended and record timestamp for tail duration."""
    global last_spoke_time
    last_spoke_time = time.time()
    speaking.clear()


def register_flush_callback(cb: Callable[[], None]) -> None:
    """Register a callback to flush audio/PCM queues after speaking."""
    if cb not in _flush_callbacks:
        _flush_callbacks.append(cb)


def flush_all_pcm() -> None:
    """Flush all registered PCM/audio queues."""
    for cb in list(_flush_callbacks):
        try:
            cb()
        except Exception:
            pass


def check_confirmation_allowed(text_or_prompt: str = "") -> bool:
    """
    Never accept approve, yes, or merge confirmations that arrive while the agent was speaking.
    Returns False if speaking or within tail_s of speaking.
    """
    if is_speaking(tail_s=0.7):
        return False
    return True

