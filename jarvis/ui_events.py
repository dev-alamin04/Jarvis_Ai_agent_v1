"""
jarvis/ui_events.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Thread-safe event bridge: any agent thread calls emit(); the WebSocket
server drains the queue and broadcasts to the UI.

No imports from other jarvis modules — zero circular-import risk.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import queue

# Queue shared between agent threads (producers) and WS server (consumer).
# maxsize prevents unbounded growth if the UI is disconnected.
_q: queue.SimpleQueue[str] = queue.SimpleQueue()


def emit(event_type: str, **data) -> None:
    """
    Fire-and-forget: put a JSON event on the queue.
    Safe to call from any thread, including audio callbacks.

    Parameters
    ----------
    event_type : str
        One of: state | level | log | transcript | reply
    **data : Any JSON-serialisable keyword arguments.

    Examples
    --------
    emit("state", state="idle")
    emit("state", state="permission", action="rm -rf /tmp", tool="run_shell_command")
    emit("level", value=0.65)
    emit("log",   text="[APPROVED] open_app firefox", ts="12:34:56")
    emit("transcript", text="Open Firefox please")
    emit("reply", text="Opening Firefox now.")
    """
    try:
        _q.put_nowait(json.dumps({"type": event_type, **data}))
    except Exception:
        pass  # Never raise from an event emitter


def drain() -> list[str]:
    """
    Return all queued event strings without blocking.
    Called by the WebSocket broadcast loop on every tick.
    """
    messages: list[str] = []
    while True:
        try:
            messages.append(_q.get_nowait())
        except queue.Empty:
            break
    return messages
