"""
jarvis/timing.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Latency Measurement and Profiling for Jarvis Voice Pipeline.

Measures:
  • STT duration (recording end → transcription text)
  • TTFT (Time To First Token from LLM)
  • TTFA (Time To First Audio Out from speaker)
  • Total turn duration (recording end → turn completion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from jarvis.logger import logger


@dataclass
class TurnTiming:
    command_id: str = ""
    recording_end: float = 0.0
    stt_end: float = 0.0
    llm_first_token: float = 0.0
    first_audio_out: float = 0.0
    turn_end: float = 0.0
    model_used: str = ""
    transcription_text: str = ""
    tools_called: list[str] = None

    def __post_init__(self):
        if self.tools_called is None:
            self.tools_called = []

    def mark_recording_end(self) -> None:
        self.recording_end = time.perf_counter()

    def mark_stt_end(self, text: str = "") -> None:
        self.stt_end = time.perf_counter()
        self.transcription_text = text

    def mark_first_token(self) -> None:
        if self.llm_first_token == 0.0:
            self.llm_first_token = time.perf_counter()

    def mark_first_audio(self) -> None:
        if self.first_audio_out == 0.0:
            self.first_audio_out = time.perf_counter()

    def mark_turn_end(self) -> None:
        self.turn_end = time.perf_counter()

    @property
    def stt_ms(self) -> float:
        return max(0.0, (self.stt_end - self.recording_end) * 1000)

    @property
    def ttft_ms(self) -> float:
        start = self.stt_end if self.stt_end > 0 else self.recording_end
        return max(0.0, (self.llm_first_token - start) * 1000) if self.llm_first_token > 0 else 0.0

    @property
    def ttfa_ms(self) -> float:
        if self.first_audio_out == 0.0 or self.recording_end == 0.0:
            return 0.0
        return max(0.0, (self.first_audio_out - self.recording_end) * 1000)

    @property
    def total_ms(self) -> float:
        if self.turn_end == 0.0 or self.recording_end == 0.0:
            return 0.0
        return max(0.0, (self.turn_end - self.recording_end) * 1000)

    def summary(self) -> str:
        ttfa_str = f"{self.ttfa_ms:.0f}ms" if self.ttfa_ms > 0 else "n/a"
        ttft_str = f"{self.ttft_ms:.0f}ms" if self.ttft_ms > 0 else "n/a"
        tools_str = f" | Tools: {','.join(self.tools_called)}" if self.tools_called else ""
        return (
            f"⏱️ [TIMING] STT: {self.stt_ms:.0f}ms | "
            f"LLM 1st token: {ttft_str} | "
            f"1st Audio (TTFA): {ttfa_str} | "
            f"Total: {self.total_ms:.0f}ms | "
            f"Model: {self.model_used}{tools_str}"
        )

    def log_summary(self) -> None:
        msg = self.summary()
        logger.info(msg)
        print(f"\n{msg}\n")
        try:
            from jarvis import ui_events
            ui_events.emit("log", text=msg, ts=time.strftime("%H:%M:%S"))
        except Exception:
            pass


# Active timing tracker instance
current_timing = TurnTiming()
