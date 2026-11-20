"""
jarvis/ui_server.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WebSocket server for the Jarvis UI.

SECURITY:
  • Binds to 127.0.0.1 ONLY — never 0.0.0.0.
  • Rejects connections that don't come from 127.0.0.1.
  • The UI is display-only: it receives events, it cannot send commands
    back that reach the brain, tools, or permission gate.
  • No secrets are ever placed in emitted events.

Architecture:
  • Runs on its own asyncio event loop in a daemon thread.
  • Drains ui_events._q at ~60fps and broadcasts to all connected clients.
  • Auto-reconnect is handled on the client (browser) side.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import websockets
from websockets.server import WebSocketServerProtocol

from jarvis import ui_events
from jarvis.config import get
from jarvis.logger import logger

_HOST = "127.0.0.1"           # never expose outside localhost
_PORT: int = int(get("ui.ws_port", 7779))
_TICK_S: float = 1 / 60       # 60 fps broadcast cadence

_clients: set[WebSocketServerProtocol] = set()
_loop: asyncio.AbstractEventLoop | None = None


# ── Connection handler ────────────────────────────────────────────────────────

async def _handler(ws: WebSocketServerProtocol) -> None:
    """Accept a new WebSocket connection (localhost only)."""
    remote = ws.remote_address[0] if ws.remote_address else ""
    if remote != _HOST:
        logger.warning(f"UI: rejected non-localhost connection from {remote}")
        await ws.close(code=1008, reason="localhost only")
        return

    _clients.add(ws)
    logger.info(f"UI: client connected ({len(_clients)} total)")
    try:
        # Send current state so the page syncs immediately on reconnect
        await ws.send('{"type":"state","state":"idle"}')
        try:
            import json
            from jarvis.cost.tracker import get_cost_today, get_cost_month
            td = get_cost_today()
            mo = get_cost_month()
            cost_event = json.dumps({
                "type": "cost",
                "today": f"${td['total_cost']:.2f}",
                "month": f"${mo['total_cost']:.2f}",
                "today_cost": td["total_cost"],
                "month_cost": mo["total_cost"],
            })
            await ws.send(cost_event)
        except Exception:
            pass
        # Keep connection open — we don't process inbound messages
        # (UI is display-only; ignore anything the browser sends)
        async for _ in ws:
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _clients.discard(ws)
        logger.info(f"UI: client disconnected ({len(_clients)} remaining)")


# ── Broadcast loop ────────────────────────────────────────────────────────────

async def _broadcast_loop() -> None:
    """Drain the event queue and push to all connected clients at 60fps."""
    while True:
        messages = ui_events.drain()
        if messages and _clients:
            dead: set[WebSocketServerProtocol] = set()
            for msg in messages:
                for ws in list(_clients):
                    try:
                        await ws.send(msg)
                    except Exception:
                        dead.add(ws)
            _clients.difference_update(dead)
        await asyncio.sleep(_TICK_S)


# ── Server startup ────────────────────────────────────────────────────────────

async def _run_server() -> None:
    async with websockets.serve(_handler, _HOST, _PORT):
        logger.info(f"UI WebSocket server listening on ws://{_HOST}:{_PORT}")
        await _broadcast_loop()


def start_in_thread() -> threading.Thread:
    """
    Start the WebSocket server in a daemon thread with its own event loop.
    Returns the thread (already started).
    """
    global _loop

    def _thread_main():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_run_server())

    t = threading.Thread(target=_thread_main, name="ui-ws-server", daemon=True)
    t.start()
    return t
