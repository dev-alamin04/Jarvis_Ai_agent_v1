"""
jarvis/ui_window.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pywebview window manager + pystray system-tray icon.

DESIGN CHOICE — pywebview over Electron/Tauri:
  • Zero additional runtime — pywebview uses the system's GTK+WebKit2 4.1
    which is already installed on this machine.
  • Pure Python — no Node.js, no Rust, no extra build steps.
  • Lightweight: ~5 MB vs Electron's ~200 MB.
  • The HTML/JS/CSS UI is framework-agnostic; it would work in Electron
    too, but that adds no value here.

GTK note: pywebview's GTK backend MUST run on the main thread. The voice
agent and WS server run in daemon threads. The entry point (jarvis_ui.py)
starts background threads first, then blocks on webview.start().
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import threading
from pathlib import Path

import webview

from jarvis.config import get, PROJECT_ROOT
from jarvis.logger import logger

# ── Config ────────────────────────────────────────────────────────────────────
_UI_HTML   = str(PROJECT_ROOT / "jarvis" / "ui" / "index.html")
_WIN_W     = int(get("ui.width",  420))
_WIN_H     = int(get("ui.height", 680))
_WIN_X     = get("ui.x", None)   # None → centred by WM
_WIN_Y     = get("ui.y", None)
_ON_TOP    = bool(get("ui.always_on_top", True))
_FRAMELESS = bool(get("ui.frameless", True))

_window: webview.Window | None = None
_visible = True


# ── Window API ────────────────────────────────────────────────────────────────

def show() -> None:
    """Show the UI window."""
    global _visible
    if _window:
        _window.show()
        _visible = True


def hide() -> None:
    """Hide the UI window (agent keeps running)."""
    global _visible
    if _window:
        _window.hide()
        _visible = False


def toggle() -> None:
    """Toggle visibility — bound to hotkey / tray icon."""
    if _visible:
        hide()
    else:
        show()


def destroy() -> None:
    if _window:
        _window.destroy()


# ── Tray icon ─────────────────────────────────────────────────────────────────

def _start_tray() -> None:
    """
    Start a system-tray icon (pystray). Runs in its own daemon thread.
    Provides a menu to show/hide/quit Jarvis.
    """
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Procedurally generate a small cyan circle icon
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, size-4, size-4], fill=(0, 180, 255, 220))
        draw.ellipse([18, 18, size-18, size-18], fill=(0, 60, 120, 200))

        icon = pystray.Icon(
            "jarvis",
            img,
            "Jarvis",
            menu=pystray.Menu(
                pystray.MenuItem("Show / Hide", lambda: toggle()),
                pystray.MenuItem("Quit Jarvis", lambda: _quit_all()),
            ),
        )

        def run_tray():
            icon.run()

        t = threading.Thread(target=run_tray, name="tray-icon", daemon=True)
        t.start()
        logger.info("Tray icon started.")
    except Exception as exc:
        logger.warning(f"Tray icon unavailable: {exc} — continuing without it.")


def _quit_all() -> None:
    """Clean shutdown from tray."""
    from jarvis import audio_state
    audio_state.shutdown.set()
    if _window:
        _window.destroy()


# ── Main entry (call from main thread) ────────────────────────────────────────

def run_window(hotkey: str = "ctrl+shift+j") -> None:
    """
    Create the pywebview window and start the GTK main loop.
    MUST be called from the main thread.
    Blocks until the window is closed.

    Parameters
    ----------
    hotkey : str
        Keyboard shortcut to toggle window visibility.
        Handled by pynput GlobalHotKeys in a daemon thread.
    """
    global _window

    _start_tray()
    _start_toggle_hotkey(hotkey)

    _window = webview.create_window(
        title      = "Jarvis",
        url        = f"file://{_UI_HTML}",
        width      = _WIN_W,
        height     = _WIN_H,
        x          = _WIN_X,
        y          = _WIN_Y,
        on_top     = _ON_TOP,
        frameless  = _FRAMELESS,
        background_color = "#000814",
        min_size   = (320, 500),
    )

    logger.info(f"UI window created ({_WIN_W}×{_WIN_H}, always_on_top={_ON_TOP})")

    # pywebview GTK main loop — blocks here
    webview.start(debug=False, gui="gtk")


def _start_toggle_hotkey(hotkey: str) -> None:
    """Listen for the toggle hotkey in a daemon thread."""
    try:
        from pynput import keyboard

        hk_map = {hotkey.lower().replace(" ", ""): toggle}
        listener = keyboard.GlobalHotKeys(hk_map)
        listener.daemon = True
        listener.start()
        logger.info(f"UI toggle hotkey: {hotkey}")
    except Exception as exc:
        logger.warning(f"Could not register UI hotkey '{hotkey}': {exc}")
