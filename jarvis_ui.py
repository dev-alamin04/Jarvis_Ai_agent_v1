#!/usr/bin/env python3
"""
jarvis_ui.py — Jarvis with the animated UI.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Starts three layers in order:
  1. UI WebSocket server  (daemon thread)
  2. Voice agent          (daemon thread — wake word + brain + TTS)
  3. pywebview window     (MAIN THREAD — GTK requires this)

Usage:
    ./venv/bin/python jarvis_ui.py

Ctrl+C or closing the window shuts everything down.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from jarvis import audio_state, ui_events
from jarvis.config import get
from jarvis.logger import logger
from jarvis import ui_server
from jarvis.ui_window import run_window

_UI_HOTKEY: str = get("ui.toggle_hotkey", "ctrl+shift+j")
_UI_AUTO:   bool = bool(get("ui.auto_start", True))


def _start_voice_agent() -> threading.Thread:
    """Start the voice agent in a background thread."""
    def _run():
        try:
            from jarvis.voice_agent import main as agent_main
            agent_main()
        except Exception as exc:
            logger.error(f"Voice agent crashed: {exc}", exc_info=True)
            ui_events.emit("state", state="error", detail=str(exc))

    t = threading.Thread(target=_run, name="voice-agent", daemon=True)
    t.start()
    return t


def main():
    print("""
╔═══════════════════════════════════════════════════╗
║       J A R V I S  —  Animated UI Mode           ║
║  Ctrl+Shift+J : show / hide the window            ║
║  Ctrl+Shift+M : mute / unmute the microphone      ║
║  Ctrl+C       : quit                              ║
╚═══════════════════════════════════════════════════╝
""")

    # 1. Start WebSocket event server (daemon thread)
    ui_server.start_in_thread()
    logger.info("UI WebSocket server started.")
    time.sleep(0.3)  # small grace period for server to bind

    # 2. Start voice agent (daemon thread)
    _start_voice_agent()
    logger.info("Voice agent thread started.")

    # 3. Graceful shutdown hook
    def _shutdown(sig, frame):
        logger.info("Shutdown signal received.")
        audio_state.shutdown.set()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 4. pywebview window — MUST run on main thread
    if _UI_AUTO:
        run_window(hotkey=_UI_HOTKEY)
    else:
        # UI disabled in config: just run the voice agent
        logger.info("ui.auto_start = false — running voice-only mode.")
        audio_state.shutdown.wait()


if __name__ == "__main__":
    main()
