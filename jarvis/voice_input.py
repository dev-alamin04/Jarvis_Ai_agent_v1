"""
jarvis/voice_input.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Speech-to-text: sends 16 kHz PCM bytes to OpenAI Whisper and returns text.

This module is used by the wake-word pipeline in Stage 2+.
It never touches raw audio files unless debug_save_audio is enabled.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import io
import os
import wave

from openai import OpenAI

from jarvis.config import TRANSCRIPTION_MODEL
from jarvis.logger import logger

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set.")
        _client = OpenAI(api_key=api_key)
    return _client


def transcribe(pcm_bytes: bytes, sample_rate: int = 16_000) -> str:
    """
    Send raw 16-bit mono PCM to OpenAI Whisper and return the transcript.

    Parameters
    ----------
    pcm_bytes : bytes
        Raw 16-bit mono PCM audio.
    sample_rate : int
        Sample rate (must be 16000 for OWW pipeline).

    Returns
    -------
    str
        Transcribed text, or empty string on error.
    """
    if not pcm_bytes:
        return ""

    # Wrap PCM in a WAV container in memory (no disk write)
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    wav_buf.seek(0)
    wav_buf.name = "audio.wav"  # OpenAI SDK reads .name for MIME type

    logger.info(
        f"Transcribing {len(pcm_bytes) / sample_rate / 2:.1f}s of audio…"
    )

    try:
        client = _get_client()
        result = client.audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=wav_buf,
            language="en",
            prompt="Voice command for Jarvis desktop assistant.",
            temperature=0.0,
        )
        text = result.text.strip()
        logger.info(f"Transcribed: {text!r}")
        return text
    except Exception as exc:
        logger.error(f"Transcription failed: {exc}")
        return ""
