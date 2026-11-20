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

from jarvis import audio_state, ui_events
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
    # ── UI state hook ──────────────────────────────────────────
    ui_events.emit("state", state="wake")


def _on_command_received(pcm_bytes: bytes) -> None:
    """
    Full pipeline: PCM → STT → Brain → TTS.
    Runs in the wake word thread; brain is thread-safe (stateless per call).
    """
    from jarvis.timing import current_timing
    timing = current_timing
    if timing.recording_end == 0.0:
        timing.mark_recording_end()

    # 1. Transcribe
    ui_events.emit("state", state="listening")          # ← UI hook
    text = transcribe(pcm_bytes, min_words=2)
    timing.mark_stt_end(text)

    # Ignore any transcription shorter than 2 words or empty
    words = text.strip().split() if text else []
    if len(words) < 2:
        logger.info(f"Ignoring short or empty transcription ({len(words)} words): {text!r}")
        ui_events.emit("state", state="idle")           # ← UI hook
        return

    # Never accept approve, yes, or merge confirmations that arrive while the agent was speaking
    import re
    clean_words = set(re.findall(r"\b\w+\b", text.lower()))
    if clean_words & {"approve", "yes", "merge", "approved", "merged"}:
        if audio_state.is_speaking(tail_s=0.7):
            logger.warning(f"Refusing confirmation '{text}' because agent was speaking or within tail.")
            ui_events.emit("state", state="idle")
            return

    logger.info(f"User said: {text!r}")
    print(f"\nYou: {text}")
    ui_events.emit("transcript", text=text)             # ← UI hook

    # ── Check for Spoken Panic or Resume Commands ──────────────
    from jarvis.safety import (
        is_panic_command,
        activate_panic,
        is_resume_command,
        deactivate_panic,
    )
    if is_panic_command(text):
        reply = activate_panic(speak_fn=speak)
        print(f"Jarvis: {reply}\n")
        ui_events.emit("reply", text=reply)
        return

    if is_resume_command(text):
        reply = deactivate_panic(speak_fn=speak)
        print(f"Jarvis: {reply}\n")
        ui_events.emit("reply", text=reply)
        return

    # ── Check for Self-Review or Feature Improvement Commands ──
    from jarvis.self_update import (
        is_self_review_command,
        handle_self_review_voice,
        match_improve_feature_command,
        handle_improve_feature_voice,
    )
    if is_self_review_command(text):
        reply = handle_self_review_voice(speak_fn=speak)
        print(f"Jarvis: {reply}\n")
        ui_events.emit("reply", text=reply)
        return

    feat_target = match_improve_feature_command(text)
    if feat_target:
        reply = handle_improve_feature_voice(
            feature_name=feat_target,
            speak_fn=_speak_with_ui,
        )
        print(f"Jarvis: {reply}\n")
        ui_events.emit("reply", text=reply)
        return

    # 2. Brain (with sentence-level TTS streaming)
    ui_events.emit("state", state="thinking")           # ← UI hook

    # Wrap speak_fn so permission prompts update the UI state
    def _speak_with_ui(spoken_text: str) -> None:
        is_permission = (
            "I want to run" in spoken_text and "Do you approve?" in spoken_text
        )
        if is_permission:
            # Extract tool name from "I want to run `tool_name`…"
            import re
            m = re.search(r"I want to run `([^`]+)`", spoken_text)
            tool = m.group(1) if m else "action"
            ui_events.emit(
                "state", state="permission",
                tool=tool, detail=spoken_text[:200]
            )
        else:
            ui_events.emit("state", state="speaking")
        speak(spoken_text)
        ui_events.emit("state", state="thinking")       # resume thinking after speak

    with _history_lock:
        from jarvis.memory import memory_manager
        # Auto-expires after configurable TTL (default 3 minutes)
        active_history = memory_manager.short_term.get_messages()
        reply = process_turn(
            user_text=text,
            conversation_history=active_history,
            speak_fn=_speak_with_ui,
            stream_to_voice=True,                       # streams sentence 1 immediately
        )

    timing.mark_turn_end()
    timing.log_summary()

    logger.info(f"Jarvis reply: {reply!r}")
    print(f"Jarvis: {reply}\n")
    ui_events.emit("reply", text=reply)                 # ← UI hook
    ui_events.emit("state", state="idle")               # ← UI hook


def _on_mute_change(is_muted: bool) -> None:
    """Called when the mute hotkey is pressed."""
    if is_muted:
        audio_state.interrupted.set()                   # halt ongoing speech immediately
    mute_beep(is_muted)
    state_text = "Microphone muted." if is_muted else "Microphone unmuted."
    logger.info(state_text)
    print(f"[{state_text}]")
    # ── UI state hook ──────────────────────────────────────────
    ui_events.emit("state", state="muted" if is_muted else "idle")
    # Speak the state change only when unmuting (can't speak while muted anyway)
    if not is_muted:
        speak(state_text)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)

    # ── Verify Locked Files Integrity at Startup ──────────────────────────
    from jarvis.self_update import check_locked_files_integrity
    ok, integrity_msg = check_locked_files_integrity()
    if not ok:
        logger.critical(f"FATAL: Startup integrity check failed: {integrity_msg}")
        print(f"\n❌ FATAL: {integrity_msg}\n")
        sys.exit(1)

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

    import threading as _t
    if _t.current_thread() is _t.main_thread():
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Jarvis voice agent running. Waiting for wake word…")
    ui_events.emit("state", state="idle")               # ← UI: initial state
    speak(f"Jarvis online. Say {_WAKE_WORD_TEXT} to give me a command.")

    # Keep main thread alive
    audio_state.shutdown.wait()


if __name__ == "__main__":
    main()
