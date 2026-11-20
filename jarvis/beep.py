"""
jarvis/beep.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tiny audio feedback module: plays a short synthesised beep via sounddevice
(PipeWire backend).  No files, no network — pure numpy sine wave.

Two beeps:
  • activation_beep() — ascending two-tone: "I'm listening"
  • mute_beep(muted)  — high tone (muted) or low tone (unmuted)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import numpy as np
import sounddevice as sd

_SAMPLE_RATE = 44_100
_AMPLITUDE = 0.25     # 0–1; keep quiet so it doesn't clip TTS


def _sine(freq: float, duration_s: float, fade_ms: int = 10) -> np.ndarray:
    """Generate a mono sine wave with a short fade-in/fade-out to avoid clicks."""
    n = int(_SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)
    wave = (_AMPLITUDE * np.sin(2 * np.pi * freq * t)).astype(np.float32)

    # Fade in/out
    fade = int(_SAMPLE_RATE * fade_ms / 1000)
    if fade > 0 and len(wave) >= 2 * fade:
        wave[:fade] *= np.linspace(0, 1, fade)
        wave[-fade:] *= np.linspace(1, 0, fade)

    return wave


def _play(audio: np.ndarray) -> None:
    """Play audio synchronously (blocking until done)."""
    try:
        sd.play(audio, samplerate=_SAMPLE_RATE, blocking=True)
    except Exception:
        pass  # Silently skip if audio device unavailable


def activation_beep() -> None:
    """
    Two ascending tones played when the wake word is detected.
    Sounds like a subtle "dun-DUN" notification.
    """
    low = _sine(880.0, 0.08)
    gap = np.zeros(int(_SAMPLE_RATE * 0.03), dtype=np.float32)
    high = _sine(1320.0, 0.12)
    _play(np.concatenate([low, gap, high]))


def mute_beep(is_muted: bool) -> None:
    """
    Single tone: high = muted, low = unmuted.
    """
    freq = 1500.0 if is_muted else 600.0
    _play(_sine(freq, 0.15))
