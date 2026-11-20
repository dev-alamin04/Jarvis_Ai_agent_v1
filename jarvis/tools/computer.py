"""
jarvis/tools/computer.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Computer Control Tools (Mouse & Keyboard).

Provides:
  • click_at: click mouse at specific screen coordinates (x, y).
  • click_element: describe a UI element, locate it via vision, and click it.
  • type_text: type text into the active window (supports unicode & enters).
  • press_hotkey: press key combinations (e.g. ctrl+c, alt+tab, super).
  • scroll_screen: scroll the screen or window up or down.

Platform Support:
  • Automatically detects X11 vs Wayland and Mutter Xwayland auth.
  • Supports pyautogui, pynput, and delegates to xdotool/ydotool when installed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time
from typing import Any

from jarvis.logger import logger

# Try importing pyautogui and pynput
try:
    import pyautogui
    pyautogui.PAUSE = 0.05
    pyautogui.FAILSAFE = False
except Exception as _e:
    pyautogui = None
    logger.warning(f"pyautogui import warning: {_e}")


_AUTH_CHECKED = False


def ensure_display_auth() -> None:
    """
    Ensure DISPLAY and Mutter Xwayland authentication cookie are registered
    so X11 / Xwayland tools like pyautogui and xdotool can connect.
    """
    global _AUTH_CHECKED
    if _AUTH_CHECKED:
        return

    # Set DISPLAY default to :0 if unset
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"

    uid = os.getuid()
    mutter_matches = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth.*")
    if mutter_matches:
        auth_file = mutter_matches[0]
        try:
            res = subprocess.run(
                ["xauth", "-f", auth_file, "list"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 3:
                    cookie = parts[2]
                    subprocess.run(
                        ["xauth", "add", ":0", "MIT-MAGIC-COOKIE-1", cookie],
                        capture_output=True,
                        timeout=2,
                    )
                    break
        except Exception as exc:
            logger.debug(f"Mutter xauth registration note: {exc}")

    _AUTH_CHECKED = True


def get_session_type() -> str:
    """Return 'wayland' or 'x11'."""
    xdg = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if "wayland" in xdg or os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11"


def get_active_window_geometry() -> dict[str, int] | None:
    """
    Attempt to get the bounding box of the active window.
    Returns {"top": int, "left": int, "width": int, "height": int} or None.
    """
    ensure_display_auth()
    # Try xdotool if available
    if shutil.which("xdotool"):
        try:
            r = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowgeometry", "--shell"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if r.returncode == 0:
                data = {}
                for line in r.stdout.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        data[k.strip()] = int(v.strip())
                if "X" in data and "Y" in data and "WIDTH" in data and "HEIGHT" in data:
                    return {
                        "left": max(0, data["X"]),
                        "top": max(0, data["Y"]),
                        "width": data["WIDTH"],
                        "height": data["HEIGHT"],
                    }
        except Exception:
            pass
    return None


def is_sensitive_context(description: str = "", app_name: str = "") -> tuple[bool, str]:
    """
    Check if an action touches sensitive applications:
      • Password managers (Bitwarden, KeePass, 1Password, LastPass, Enpass)
      • Banking & payment sites (Chase, Bank, PayPal, Stripe, etc.)
      • Terminals running sudo
    """
    combined = f"{description} {app_name}".lower()

    # Password managers
    pwd_managers = ["keepass", "bitwarden", "1password", "lastpass", "enpass", "keychain", "password manager"]
    for pm in pwd_managers:
        if pm in combined:
            return True, f"target relates to password manager '{pm}'"

    # Banking keywords
    banking_words = ["bank", "banking", "chase", "paypal", "stripe", "wells fargo", "account number", "credit card", "transfer"]
    for bw in banking_words:
        if bw in combined:
            return True, f"target relates to banking/financial service '{bw}'"

    # Check for active sudo processes
    if "sudo" in combined:
        return True, "target involves sudo or root privileges"

    try:
        # Check if any active process is sudo
        ps_out = subprocess.run(
            ["pgrep", "-x", "sudo"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if ps_out.returncode == 0 and ps_out.stdout.strip():
            # If the description references terminal or console while sudo is running
            if any(w in combined for w in ["terminal", "console", "shell", "window", "click"]):
                return True, "a terminal session running sudo is currently active"
    except Exception:
        pass

    return False, ""


# ── Mouse Tools ──────────────────────────────────────────────────────────────

def click_at(x: int, y: int, clicks: int = 1, button: str = "left") -> str:
    """
    Click the mouse at absolute pixel coordinates (x, y).

    Parameters
    ----------
    x : int
        Horizontal pixel coordinate (0 = left).
    y : int
        Vertical pixel coordinate (0 = top).
    clicks : int
        Number of clicks (1 for single click, 2 for double click).
    button : str
        'left', 'right', or 'middle'.
    """
    ensure_display_auth()
    logger.info(f"click_at: ({x}, {y}) clicks={clicks} button={button}")

    btn = button.lower().strip()
    if btn not in ("left", "right", "middle"):
        btn = "left"

    # Try ydotool on Wayland if installed
    if get_session_type() == "wayland" and shutil.which("ydotool"):
        try:
            # ydotool mousemove -a <x> <y>
            subprocess.run(["ydotool", "mousemove", "-a", str(x), str(y)], check=True, timeout=2)
            btn_code = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}.get(btn, "0xC0")
            for _ in range(clicks):
                subprocess.run(["ydotool", "click", btn_code], check=True, timeout=2)
            return f"Clicked {btn} button {clicks} time(s) at ({x}, {y}) using ydotool."
        except Exception as e:
            logger.debug(f"ydotool click attempt: {e}")

    # Fall back to pyautogui
    if pyautogui:
        try:
            pyautogui.moveTo(x, y)
            pyautogui.click(x=x, y=y, clicks=clicks, button=btn)
            return f"Clicked {btn} button {clicks} time(s) at ({x}, {y})."
        except Exception as exc:
            return f"Failed to click at ({x}, {y}): {exc}"

    return "No mouse control backend available."


def click_element(description: str) -> str:
    """
    Find a UI element by visual description and click it.

    Parameters
    ----------
    description : str
        Natural language description of what to click (e.g. 'the blue Submit button',
        'the close icon on the top right', 'the search input field').
    """
    ensure_display_auth()
    logger.info(f"click_element: finding '{description}'")

    from jarvis.tools.vision import locate_element
    result = locate_element(description)

    if not result.get("found"):
        err = result.get("error") or "Element not found in screenshot"
        return f"Could not find element '{description}' on screen: {err}"

    x = result.get("x", 0)
    y = result.get("y", 0)
    label = result.get("label", description)

    click_res = click_at(x=x, y=y, clicks=1, button="left")
    return f"Located '{label}' at ({x}, {y}). {click_res}"


def scroll_screen(clicks: int = 3, direction: str = "down") -> str:
    """
    Scroll the mouse wheel up or down.

    Parameters
    ----------
    clicks : int
        Number of scroll units (default 3).
    direction : str
        'down' or 'up'.
    """
    ensure_display_auth()
    logger.info(f"scroll_screen: clicks={clicks} direction={direction}")

    d = direction.lower().strip()
    amount = abs(clicks)

    # In X11 / Linux pyautogui: negative scrolls down, positive scrolls up
    scroll_val = -amount * 100 if d == "down" else amount * 100

    if pyautogui:
        try:
            pyautogui.scroll(scroll_val)
            return f"Scrolled {d} by {amount} units."
        except Exception as exc:
            return f"Failed to scroll screen: {exc}"

    return "Mouse scrolling backend unavailable."


# ── Keyboard Tools ───────────────────────────────────────────────────────────

def type_text(text: str, press_enter: bool = False) -> str:
    """
    Type text into the currently focused window or element.

    Parameters
    ----------
    text : str
        The string to type.
    press_enter : bool
        If True, press Enter immediately after typing.
    """
    ensure_display_auth()
    logger.info(f"type_text: typing {len(text)} chars (enter={press_enter})")

    import pyperclip

    # Try clipboard paste for full unicode / multi-line safety
    try:
        pyperclip.copy(text)
        press_hotkey("ctrl+v")
        if press_enter:
            time.sleep(0.05)
            press_hotkey("enter")
        return f"Typed {len(text)} characters into active window."
    except Exception as exc:
        logger.debug(f"Clipboard typing failed, falling back to pyautogui: {exc}")

    if pyautogui:
        try:
            pyautogui.write(text, interval=0.01)
            if press_enter:
                pyautogui.press("enter")
            return f"Typed {len(text)} characters into active window."
        except Exception as exc:
            return f"Failed to type text: {exc}"

    return "No keyboard typing backend available."


def press_hotkey(keys: list[str] | str) -> str:
    """
    Press a key or key combination.

    Parameters
    ----------
    keys : list[str] | str
        A hotkey string like 'ctrl+c', 'alt+tab', 'super', or a list like ['ctrl', 'shift', 't'].
    """
    ensure_display_auth()

    if isinstance(keys, str):
        key_list = [k.strip().lower() for k in keys.split("+") if k.strip()]
    else:
        key_list = [str(k).strip().lower() for k in keys if str(k).strip()]

    if not key_list:
        return "No keys provided to press."

    logger.info(f"press_hotkey: {key_list}")

    # Remap common friendly names to pyautogui keysyms
    remap = {
        "control": "ctrl",
        "super": "win",
        "windows": "win",
        "return": "enter",
        "escape": "esc",
    }
    normalized = [remap.get(k, k) for k in key_list]

    if pyautogui:
        try:
            pyautogui.hotkey(*normalized)
            return f"Pressed key combination: {' + '.join(normalized)}"
        except Exception as exc:
            return f"Failed to press keys {'+'.join(normalized)}: {exc}"

    return "No keyboard hotkey backend available."
