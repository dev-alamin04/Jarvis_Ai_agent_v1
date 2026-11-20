"""
jarvis/voice_output.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Text-to-speech: sends text to OpenAI TTS and plays back via sounddevice.

Sets audio_state.speaking while audio is playing so the wake word listener
ignores the microphone and cannot self-trigger.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import io
import os

import numpy as np
import sounddevice as sd

from openai import OpenAI

from jarvis import audio_state
from jarvis.config import TTS_MODEL, TTS_VOICE
from jarvis.logger import logger

_SAMPLE_RATE = 24_000   # OpenAI TTS PCM output is 24 kHz
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set.")
        _client = OpenAI(api_key=api_key)
    return _client


def speak(text: str) -> None:
    """
    Convert text to speech and play it.
    Blocks until playback finishes.
    Sets audio_state.speaking for the full duration.
    """
    if not text:
        return

    logger.info(f"TTS: {text[:80]!r}…")

    try:
        client = _get_client()
        # Request raw PCM (f32le) so we don't need an mp3 decoder
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text,
            response_format="pcm",   # 24kHz, 16-bit signed little-endian mono
        )
        pcm_bytes = response.content
    except Exception as exc:
        logger.error(f"TTS failed: {exc}")
        # Fall back to silent failure — don't crash the main loop
        return

    # Convert 16-bit PCM bytes to float32 array
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # Set speaking flag BEFORE playback (self-trigger guard)
    audio_state.speaking.set()
    try:
        sd.play(audio, samplerate=_SAMPLE_RATE, blocking=True)
    except Exception as exc:
        logger.error(f"Audio playback failed: {exc}")
    finally:
        audio_state.speaking.clear()
