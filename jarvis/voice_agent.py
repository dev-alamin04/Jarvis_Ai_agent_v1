"""
jarvis/voice_agent.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voice agent entry point (Stage 2+).

Wires together:
  WakeWordListener → voice_input.transcribe → brain.process_turn
  → voice_output.speak → back to WakeWordListener

Also starts the MuteHotkeyListener.

Run with:
    python voice_agent.py
Or via:
    ./venv/bin/python -m jarvis.voice_agent
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import signal
import sys
import threading

from jarvis import audio_state
from jarvis.beep import activation_beep, mute_beep
from jarvis.brain import process_turn
from jarvis.config import get
from jarvis.logger import logger
from jarvis.mute_hotkey import MuteHotkeyListener
from jarvis.voice_input import transcribe
from jarvis.voice_output import speak
from jarvis.wake_word import WakeWordListener

# ── Mode config ───────────────────────────────────────────────────────────────
_WAKE_WORD_MODE: bool = bool(get("wake_word.enabled", True))
_WAKE_WORD_TEXT: str = get("wake_word.word", "hey jarvis")

BANNER = """
╔════════════════════════════════════════════════╗
║        J A R V I S  —  Voice Mode             ║
║  Say "{wake_word}" to start a command.         ║
║  Ctrl+Shift+M to mute/unmute the microphone.   ║
║  Ctrl+C to exit.                               ║
╚════════════════════════════════════════════════╝
""".format(wake_word=_WAKE_WORD_TEXT.title())


# ── Shared conversation history (kept for multi-turn context) ─────────────────
_conversation_history: list[dict] = []
_history_lock = threading.Lock()


# ── Core pipeline ─────────────────────────────────────────────────────────────

def _on_activated() -> None:
    """Called the instant the wake word fires — before recording starts."""
    activation_beep()
    logger.info("Activation beep played. Listening for command…")


def _on_command_received(pcm_bytes: bytes) -> None:
    """
    Full pipeline: PCM → STT → Brain → TTS.
    Runs in the wake word thread; brain is thread-safe (stateless per call).
    """
    # 1. Transcribe
    text = transcribe(pcm_bytes)
    if not text:
        speak("Sorry, I didn't catch that.")
        return

    logger.info(f"User said: {text!r}")
    print(f"\nYou: {text}")

    # 2. Brain
    with _history_lock:
        reply = process_turn(
            user_text=text,
            conversation_history=_conversation_history,
            speak_fn=speak,   # voice permission prompts
        )

    logger.info(f"Jarvis reply: {reply!r}")
    print(f"Jarvis: {reply}\n")

    # 3. Speak
    speak(reply)


def _on_mute_change(is_muted: bool) -> None:
    """Called when the mute hotkey is pressed."""
    mute_beep(is_muted)
    state_text = "Microphone muted." if is_muted else "Microphone unmuted."
    logger.info(state_text)
    print(f"[{state_text}]")
    # Speak the state change only when unmuting (can't speak while muted anyway)
    if not is_muted:
        speak(state_text)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)

    if not _WAKE_WORD_MODE:
        logger.warning(
            "wake_word.enabled is False in config — start push-to-talk mode instead."
        )
        sys.exit(0)

    # ── Mute hotkey ───────────────────────────────────────────────────────
    mute_listener = MuteHotkeyListener(on_mute_change=_on_mute_change)
    mute_listener.start()

    # ── Wake word listener ─────────────────────────────────────────────────
    ww_listener = WakeWordListener(
        on_wake=_on_command_received,
        on_activated=_on_activated,
    )
    ww_listener.start()

    # ── Graceful shutdown on Ctrl+C ───────────────────────────────────────
    def _shutdown(sig, frame):
        print("\nShutting down Jarvis…")
        audio_state.shutdown.set()
        ww_listener.stop()
        mute_listener.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Jarvis voice agent running. Waiting for wake word…")
    speak(f"Jarvis online. Say {_WAKE_WORD_TEXT} to give me a command.")

    # Keep main thread alive
    audio_state.shutdown.wait()


if __name__ == "__main__":
    main()
