"""
jarvis/assistant/notifier.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Background Notification Daemon for Reminders and Calendar Events.

Runs a daemon thread periodically checking:
  1. Reminders due now -> Speaks "Alamin, here is your reminder: ..."
  2. Calendar events starting in 10 minutes -> Speaks "Alamin, you have '...' in 10 minutes"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable

from jarvis import audio_state
from jarvis.assistant.calendar import check_upcoming_event_reminders
from jarvis.assistant.reminders import check_due_reminders
from jarvis.logger import logger


class PersonalAssistantDaemon:
    """
    Background daemon thread monitoring due reminders and upcoming calendar events.
    """

    def __init__(
        self,
        speak_callback: Callable[[str], None] | None = None,
        poll_interval_seconds: int = 5,
    ):
        self._speak_cb = speak_callback
        self._interval = poll_interval_seconds
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the background reminder and calendar watcher thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="PersonalAssistantDaemon",
            daemon=True,
        )
        self._thread.start()
        logger.info("[Assistant Daemon] Started background reminder and calendar watcher.")

    def stop(self) -> None:
        """Signal the daemon thread to terminate."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("[Assistant Daemon] Stopped.")

    def poll_now(self) -> dict[str, Any]:
        """
        Run an immediate check for due reminders and 10-minute calendar warnings.
        """
        due_reminders = check_due_reminders(speak_fn=self._speak_cb)
        cal_alerts = check_upcoming_event_reminders(speak_fn=self._speak_cb)
        return {
            "due_reminders": due_reminders,
            "calendar_alerts": cal_alerts,
        }

    def _run_loop(self) -> None:
        """Main daemon loop."""
        while not self._stop_event.is_set():
            try:
                self.poll_now()
            except Exception as exc:
                logger.debug(f"[Assistant Daemon] Loop check error: {exc}")

            # Sleep in 0.5s increments to respond promptly to stop requests
            for _ in range(self._interval * 2):
                if self._stop_event.is_set() or audio_state.shutdown.is_set():
                    return
                time.sleep(0.5)


# Global singleton daemon instance
assistant_daemon = PersonalAssistantDaemon()
