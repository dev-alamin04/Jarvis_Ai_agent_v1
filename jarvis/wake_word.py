"""
jarvis/wake_word.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Always-listening wake word detector using openWakeWord (OWW).

Runs in its own daemon thread. Architecture:

  [mic]─→[16kHz PCM ring buffer]─→[OWW model]─→wake trigger
                                       ↓
                              [SpeechCollector/VAD]─→complete utterance
                                       ↓
                              callback(audio_bytes)

Safety rules enforced here:
  • Audio never sent to any network — OWW runs entirely locally.
  • Mic silenced while audio_state.speaking is set (self-trigger guard).
  • Mic silenced while audio_state.muted is set (hotkey).
  • Raw audio not saved unless config debug_save_audio = true.
  • Every detection is logged with a timestamp.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import io
import queue
import struct
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd

from jarvis import audio_state
from jarvis.config import get, PROJECT_ROOT
from jarvis.logger import logger
from jarvis.vad import SpeechCollector

# ── Config ────────────────────────────────────────────────────────────────────
_WAKE_WORD: str = get("wake_word.word", "hey jarvis")
_SENSITIVITY: float = float(get("wake_word.sensitivity", 0.5))
_SAMPLE_RATE: int = 16_000          # OWW requires 16 kHz
_CHANNELS: int = 1
_DTYPE: str = "int16"
_CHUNK_MS: int = 80                  # OWW processes 80 ms chunks
_CHUNK_SAMPLES: int = int(_SAMPLE_RATE * _CHUNK_MS / 1000)  # 1280 samples
_SILENCE_TIMEOUT: float = float(get("wake_word.silence_timeout_s", 4.0))
_COMMAND_SILENCE: float = float(get("wake_word.command_silence_s", 1.5))
_DEBUG_SAVE_AUDIO: bool = bool(get("wake_word.debug_save_audio", False))
_VAD_AGGRESSIVENESS: int = int(get("wake_word.vad_aggressiveness", 3))

# OWW model map: friendly name in config → OWW model identifier
_OWW_MODEL_MAP: dict[str, str] = {
    "hey jarvis": "hey_jarvis",
    "alexa": "alexa",
    "hey mycroft": "hey_mycroft",
    "timmy": "timmy",
}


# ── Wake word listener ────────────────────────────────────────────────────────

class WakeWordListener:
    """
    Always-on wake word listener running in a background daemon thread.

    Parameters
    ----------
    on_wake : Callable[[bytes], None]
        Called with the recorded command PCM bytes (16 kHz, 16-bit, mono)
        after the user finishes speaking.
    on_activated : Callable[[], None]
        Called the moment the wake word is detected (before recording starts),
        so the caller can play a beep or say "yes?".
    """

    def __init__(
        self,
        on_wake: Callable[[bytes], None],
        on_activated: Callable[[], None] | None = None,
    ):
        self._on_wake = on_wake
        self._on_activated = on_activated
        self._oww_model = None
        self._thread: threading.Thread | None = None
        self._pcm_queue: queue.Queue[bytes] = queue.Queue(maxsize=200)

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Load model and start background thread."""
        self._load_model()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="wake-word-listener",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"WakeWordListener started — wake word: '{_WAKE_WORD}', "
            f"sensitivity: {_SENSITIVITY}"
        )

    def stop(self) -> None:
        """Signal the loop to stop."""
        audio_state.shutdown.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("WakeWordListener stopped.")

    # ── Model loading ───────────────────────────────────────────────────────

    def _load_model(self) -> None:
        """
        Load the openWakeWord model. OWW downloads model files on first use
        to ~/.cache/openwakeword/ — entirely local, no API calls.
        """
        try:
            import openwakeword
            from openwakeword.model import Model

            # Resolve model name
            model_key = _WAKE_WORD.lower().strip()
            oww_name = _OWW_MODEL_MAP.get(model_key, "hey_jarvis")

            logger.info(f"Loading OWW model: '{oww_name}' …")
            # inference_framework="onnx" avoids tflite dependency
            self._oww_model = Model(
                wakeword_models=[oww_name],
                inference_framework="onnx",
            )
            logger.info("OWW model loaded OK.")
        except Exception as exc:
            logger.error(
                f"Failed to load openWakeWord model: {exc}\n"
                "Falling back to keyword-spotting stub — OWW is not active."
            )
            self._oww_model = None

    # ── Mic capture ─────────────────────────────────────────────────────────

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status,
    ) -> None:
        """sounddevice callback — runs in C audio thread, must be fast."""
        if status:
            logger.debug(f"sounddevice status: {status}")
        # Drop audio while speaking (self-trigger guard) or muted
        if audio_state.speaking.is_set() or audio_state.muted.is_set():
            return
        try:
            self._pcm_queue.put_nowait(indata.tobytes())
        except queue.Full:
            pass  # Drop oldest chunk rather than block

    # ── Main listener loop ───────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main daemon thread: OWW detection → command recording → callback."""
        with sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=_CHANNELS,
            dtype=_DTYPE,
            blocksize=_CHUNK_SAMPLES,
            callback=self._audio_callback,
        ):
            logger.info("Microphone open — listening for wake word…")
            self._detection_loop()

    def _detection_loop(self) -> None:
        """Read chunks, run OWW inference, trigger on detection."""
        # Keep a sliding window of the last ~1 s of audio for OWW
        oww_buffer: list[np.ndarray] = []

        while not audio_state.shutdown.is_set():
            try:
                raw = self._pcm_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            chunk = np.frombuffer(raw, dtype=np.int16)
            oww_buffer.append(chunk)

            if self._oww_model is None:
                # Stub mode: skip OWW, never trigger automatically
                continue

            # OWW needs chunks fed as float32 normalised
            audio_f32 = chunk.astype(np.float32) / 32768.0

            try:
                prediction = self._oww_model.predict(audio_f32)
            except Exception as exc:
                logger.debug(f"OWW predict error: {exc}")
                continue

            # prediction is {model_name: score}
            score = max(prediction.values()) if prediction else 0.0

            if score >= _SENSITIVITY:
                self._handle_detection()

    # ── Post-detection: record command ───────────────────────────────────────

    def _handle_detection(self) -> None:
        """Wake word detected — announce, record command, deliver to callback."""
        timestamp = datetime.now(timezone.utc).isoformat()
        logger.info(f"[WAKE WORD DETECTED] {timestamp} word='{_WAKE_WORD}'")

        # Flush stale chunks so command recording starts clean
        while not self._pcm_queue.empty():
            try:
                self._pcm_queue.get_nowait()
            except queue.Empty:
                break

        # Notify caller (play beep / say "yes?")
        if self._on_activated:
            try:
                self._on_activated()
            except Exception as exc:
                logger.debug(f"on_activated callback error: {exc}")

        # Record command with VAD
        audio_state.recording.set()
        command_audio = self._record_command()
        audio_state.recording.clear()

        if command_audio:
            if _DEBUG_SAVE_AUDIO:
                _save_debug_wav(command_audio)
            self._on_wake(command_audio)
        else:
            logger.info("Wake word triggered but no speech detected — returning to listen.")

    def _record_command(self) -> bytes | None:
        """
        Record audio until silence_timeout_s of silence, or _SILENCE_TIMEOUT
        seconds with no speech at all (cancellation).

        Returns raw 16-bit mono PCM bytes, or None if cancelled.
        """
        collector = SpeechCollector(
            silence_timeout_s=_COMMAND_SILENCE,
            aggressiveness=_VAD_AGGRESSIVENESS,
        )

        deadline = time.monotonic() + _SILENCE_TIMEOUT

        while time.monotonic() < deadline:
            if audio_state.shutdown.is_set():
                return None

            try:
                raw = self._pcm_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Extend deadline once speech starts
            if collector.is_collecting:
                deadline = time.monotonic() + _SILENCE_TIMEOUT

            result = collector.feed(raw)
            if result is not None:
                return result

        logger.info("Command timeout — no speech detected after wake word.")
        return None


# ── Debug audio save ─────────────────────────────────────────────────────────

def _save_debug_wav(pcm: bytes) -> None:
    """Write a debug WAV to logs/debug_audio/ — only when debug_save_audio = true."""
    out_dir = PROJECT_ROOT / "logs" / "debug_audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"cmd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16_000)
        wf.writeframes(pcm)
    fname.write_bytes(buf.getvalue())
    logger.debug(f"Debug audio saved: {fname}")
