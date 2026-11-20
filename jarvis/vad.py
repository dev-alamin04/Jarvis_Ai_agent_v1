"""
jarvis/vad.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voice Activity Detection helper.

Uses webrtcvad (Google's WebRTC VAD) to classify 10/20/30 ms frames as
speech or silence. Wraps a simple ring-buffer to decide "speech started"
and "speech ended" with configurable silence timeout.

webrtcvad requires 16 kHz, 16-bit mono PCM.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import collections
from typing import Generator

import webrtcvad  # pip: webrtcvad-wheels

from jarvis.logger import logger

# webrtcvad only accepts these frame durations (ms) at 16 kHz
_VALID_FRAME_MS = {10, 20, 30}
_SAMPLE_RATE = 16_000
_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes per sample


class VADFramer:
    """
    Accepts raw PCM bytes from the microphone, chunks them into VAD frames,
    and returns is_speech decisions.

    Parameters
    ----------
    aggressiveness : int
        0–3. Higher = more aggressive filtering of non-speech. Default 3.
    frame_ms : int
        Frame duration in milliseconds. Must be 10, 20, or 30.
    """

    def __init__(self, aggressiveness: int = 3, frame_ms: int = 30):
        if frame_ms not in _VALID_FRAME_MS:
            raise ValueError(f"frame_ms must be one of {_VALID_FRAME_MS}")
        self._vad = webrtcvad.Vad(aggressiveness)
        self._frame_ms = frame_ms
        self._frame_bytes = int(_SAMPLE_RATE * _SAMPLE_WIDTH * frame_ms / 1000)
        self._buf = b""

    def feed(self, pcm_bytes: bytes) -> Generator[tuple[bytes, bool], None, None]:
        """
        Feed raw PCM bytes. Yields (frame_bytes, is_speech) for each
        complete frame extracted from the buffer.
        """
        self._buf += pcm_bytes
        while len(self._buf) >= self._frame_bytes:
            frame = self._buf[: self._frame_bytes]
            self._buf = self._buf[self._frame_bytes :]
            try:
                is_speech = self._vad.is_speech(frame, _SAMPLE_RATE)
            except Exception:
                is_speech = False
            yield frame, is_speech

    @property
    def frame_bytes(self) -> int:
        return self._frame_bytes


class SpeechCollector:
    """
    Wraps VADFramer and collects speech frames into a complete utterance.

    Uses a sliding window to detect:
      - speech start: N consecutive speech frames
      - speech end  : M consecutive silence frames after speech

    Parameters
    ----------
    silence_timeout_s : float
        Seconds of silence to consider speech complete (default 1.5 s).
    speech_start_frames : int
        Speech frames needed before recording "starts" (default 3).
    aggressiveness : int
        webrtcvad aggressiveness 0–3.
    frame_ms : int
        10 / 20 / 30 ms per VAD frame.
    """

    def __init__(
        self,
        silence_timeout_s: float = 1.5,
        speech_start_frames: int = 3,
        aggressiveness: int = 3,
        frame_ms: int = 30,
    ):
        self._framer = VADFramer(aggressiveness=aggressiveness, frame_ms=frame_ms)
        silence_frames = int(silence_timeout_s * 1000 / frame_ms)
        self._ring_size = max(silence_frames, speech_start_frames + 1)
        self._speech_start_frames = speech_start_frames
        self._silence_frames_needed = silence_frames

        self._ring: collections.deque[bool] = collections.deque(
            maxlen=self._ring_size
        )
        self._speech_started = False
        self._collected: list[bytes] = []

    @property
    def frame_bytes(self) -> int:
        return self._framer.frame_bytes

    def feed(self, pcm_bytes: bytes) -> bytes | None:
        """
        Feed PCM bytes.

        Returns
        -------
        bytes | None
            Complete utterance PCM when speech ends, else None.
        """
        for frame, is_speech in self._framer.feed(pcm_bytes):
            self._ring.append(is_speech)

            if not self._speech_started:
                # Detect start: enough recent frames are speech
                if sum(self._ring) >= self._speech_start_frames:
                    self._speech_started = True
                    logger.debug("VAD: speech started")
                    # Include buffered frames in collection
                    self._collected.extend(list(self._ring))
            else:
                self._collected.append(frame)
                # Detect end: tail of ring is all silence
                tail = list(self._ring)[-self._silence_frames_needed:]
                if len(tail) == self._silence_frames_needed and not any(tail):
                    # Speech ended
                    audio = b"".join(self._collected)
                    logger.debug(f"VAD: speech ended, {len(audio)} bytes collected")
                    self.reset()
                    return audio

        return None

    def reset(self):
        self._ring.clear()
        self._speech_started = False
        self._collected = []

    @property
    def is_collecting(self) -> bool:
        return self._speech_started
