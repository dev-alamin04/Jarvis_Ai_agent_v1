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
from jarvis.vad import VADFramer

_SAMPLE_RATE = 24_000   # OpenAI TTS PCM output is 24 kHz
_client: OpenAI | None = None
_INTERRUPT_KEYWORDS = {
    "stop", "quiet", "hush", "shut up", "silence", "pause", "cancel",
    "hey jarvis", "jarvis", "wait", "enough"
}


def _interrupt_monitor(stop_event: threading.Event) -> None:
    """
    Listens on the microphone while the agent is speaking.
    If the user says 'stop', 'quiet', etc., sets audio_state.interrupted to halt speech.
    """
    try:
        from jarvis.voice_input import transcribe
        vad = VADFramer(aggressiveness=2, frame_ms=30)

        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=480) as mic_stream:
            collected_frames = []
            speech_frames_count = 0

            while not stop_event.is_set() and audio_state.speaking.is_set() and not audio_state.interrupted.is_set():
                data, _ = mic_stream.read(480)
                raw_bytes = data.tobytes()

                for frame, is_speech in vad.feed(raw_bytes):
                    if is_speech:
                        speech_frames_count += 1
                        collected_frames.append(frame)
                    elif speech_frames_count > 0:
                        collected_frames.append(frame)
                        # Once we have ~450ms of speech followed by silence, check keyword
                        if len(collected_frames) >= 15:
                            audio_pcm = b"".join(collected_frames)
                            collected_frames = []
                            speech_frames_count = 0
                            try:
                                text = transcribe(audio_pcm)
                                text_lower = text.lower()
                                if any(kw in text_lower for kw in _INTERRUPT_KEYWORDS):
                                    logger.info(f"Speech interrupted: detected '{text}'")
                                    audio_state.interrupted.set()
                                    return
                            except Exception as exc:
                                logger.debug(f"Interrupt transcribe error: {exc}")
                            break

                    # Cap continuous collection at ~1.5s
                    if len(collected_frames) >= 50:
                        audio_pcm = b"".join(collected_frames)
                        collected_frames = []
                        speech_frames_count = 0
                        try:
                            text = transcribe(audio_pcm)
                            if any(kw in text.lower() for kw in _INTERRUPT_KEYWORDS):
                                logger.info(f"Speech interrupted: detected '{text}'")
                                audio_state.interrupted.set()
                                return
                        except Exception:
                            pass
    except Exception as exc:
        logger.debug(f"Interrupt monitor error: {exc}")


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
    Sets audio_state.speaking for the full duration including API request and playback.
    """
    if not text:
        return

    # Set speaking flag for the whole duration of TTS generation and playback
    audio_state.speaking.set()
    audio_state.interrupted.clear()

    logger.info(f"TTS: {text[:80]!r}…")

    try:
        from jarvis.cost.tracker import track_speech
        track_speech(text_or_chars=text, model=TTS_MODEL)
    except Exception as exc:
        logger.debug(f"[Cost Tracking] Speech tracking error: {exc}")

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
        audio_state.mark_speaking_ended()
        audio_state.flush_all_pcm()
        return

    # Convert 16-bit PCM bytes to float32 array
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        from jarvis import ui_events
        chunk_size = 1024
        with sd.OutputStream(samplerate=_SAMPLE_RATE, channels=1, dtype='float32') as stream:
            for i in range(0, len(audio), chunk_size):
                if audio_state.interrupted.is_set():
                    logger.info("Speech playback stopped by interruption.")
                    break
                chunk = audio[i:i + chunk_size]
                stream.write(chunk)
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                ui_events.emit("level", value=min(1.0, rms * 3.5))
    except Exception as exc:
        logger.error(f"Audio playback failed: {exc}")
    finally:
        audio_state.mark_speaking_ended()
        audio_state.flush_all_pcm()
