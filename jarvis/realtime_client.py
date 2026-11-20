"""
jarvis/realtime_client.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenAI Realtime API Client (Optional Experimental Mode).

Connects to `wss://api.openai.com/v1/realtime` for ultra-low-latency,
full-duplex speech-in / speech-out.

TRADE-OFF ANALYSIS:
  • Latency: ~300ms round-trip (vs ~700-900ms for our streaming sentence pipeline).
  • Cost:
      - Realtime audio input:  $100 / 1M tokens (~$0.06 / min)
      - Realtime audio output: $200 / 1M tokens (~$0.24 / min)
      - Compared to our streaming pipeline:
          Whisper ($0.006/min) + gpt-4o-mini ($0.15/1M text) + tts-1 ($0.015/1K chars)
          Our streaming pipeline is **12x to 20x cheaper**!
  • Tool Calling & Security:
      - Realtime API tool execution requires bi-directional WebSocket framing and
        asynchronous cancellation.
      - Our local Permission Gate with spoken confirmation fits Chat Completions
        streaming much more cleanly and reliably.
  • Privacy:
      - Realtime API requires continuously streaming audio to OpenAI servers,
        violating our local-first offline wake-word guarantee.

Verdict: The sentence-streaming pipeline (gpt-4o-mini + Whisper + TTS-1) is the
recommended default for desktop assistants. This module serves as an optional
mode when `pipeline.mode: "realtime"` is set in config.yaml.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Callable

from jarvis.config import get
from jarvis.logger import logger

_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"


class RealtimeVoiceSession:
    """
    Manages an optional full-duplex session with the OpenAI Realtime API over WebSocket.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.ws = None
        self.is_connected = False

    async def connect(self) -> bool:
        if not self.api_key:
            logger.error("Realtime API: OPENAI_API_KEY is not set.")
            return False

        try:
            import websockets
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "OpenAI-Beta": "realtime=v1",
            }
            self.ws = await websockets.connect(_REALTIME_URL, extra_headers=headers)
            self.is_connected = True
            logger.info("Realtime API: WebSocket connection established.")
            await self._configure_session()
            return True
        except Exception as exc:
            logger.warning(f"Realtime API connection failed: {exc}. Falling back to streaming pipeline.")
            self.is_connected = False
            return False

    async def _configure_session(self) -> None:
        """Send session.update with tool schemas and voice settings."""
        if not self.ws:
            return

        from jarvis.tools.registry import get_tool_schemas
        tools = [t["function"] for t in get_tool_schemas()]

        event = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": get("openai.tts_voice", "echo"),
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "tools": tools,
            },
        }
        await self.ws.send(json.dumps(event))

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
            self.is_connected = False
            logger.info("Realtime API: connection closed.")
