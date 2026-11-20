"""
jarvis/mute_hotkey.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Global mute/unmute hotkey listener (runs in a background thread).

Default hotkey: Ctrl+Shift+M (configurable in config.yaml).
When triggered:
  - Toggles audio_state.muted
  - Plays a short beep and logs the new state
  - Calls an optional callback so the voice output layer can speak a reply

Uses pynput (pure Python, works on both X11 and Wayland via libinput).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import threading
from typing import Callable

from pynput import keyboard

from jarvis import audio_state
from jarvis.config import get
from jarvis.logger import logger

_MUTE_HOTKEY: str = get("wake_word.mute_hotkey", "<ctrl>+<shift>+m")


class MuteHotkeyListener:
    """
    Listens for a global hotkey and toggles the mute state.

    Parameters
    ----------
    on_mute_change : Callable[[bool], None] | None
        Called with True when muted, False when unmuted.
        Use this to play a beep or speak a confirmation.
    """

    def __init__(self, on_mute_change: Callable[[bool], None] | None = None):
        self._on_mute_change = on_mute_change
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        hotkey = _MUTE_HOTKEY
        self._listener = keyboard.GlobalHotKeys(
            {hotkey: self._toggle_mute}
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info(f"Mute hotkey registered: {hotkey}")

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()

    def _toggle_mute(self) -> None:
        if audio_state.muted.is_set():
            audio_state.muted.clear()
            state = False
            logger.info("🔊 MICROPHONE UNMUTED")
        else:
            audio_state.muted.set()
            state = True
            logger.info("🔇 MICROPHONE MUTED")

        if self._on_mute_change:
            try:
                self._on_mute_change(state)
            except Exception as exc:
                logger.debug(f"on_mute_change callback error: {exc}")
