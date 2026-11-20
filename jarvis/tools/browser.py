"""
jarvis/tools/browser.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Browser Automation Tools.

Provides:
  • browser_open: open any URL in the system browser.
  • browser_search: search Google, DuckDuckGo, or Bing.
  • browser_fill_form: fill simple form inputs and optionally submit.
    (Note: Submitting forms requires spoken confirmation via Permission Gate).
  • play_youtube: retained in jarvis/tools/system.py for YouTube playback.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import time
import urllib.parse
from jarvis.logger import logger
from jarvis.tools.system import open_url


def browser_open(url: str) -> str:
    """
    Open a web page URL in the default browser.

    Parameters
    ----------
    url : str
        The full website URL (must start with http:// or https://).
    """
    return open_url(url)


def browser_search(query: str, engine: str = "google") -> str:
    """
    Perform a web search using the specified search engine and open results in browser.

    Parameters
    ----------
    query : str
        Search query or topic.
    engine : str
        Search engine: 'google', 'duckduckgo', or 'bing'.
    """
    logger.info(f"browser_search: query={query!r} engine={engine}")

    cleaned = (query or "").strip()
    if not cleaned:
        return "Search query cannot be empty."

    encoded = urllib.parse.quote_plus(cleaned)
    eng = engine.lower().strip()

    if "duck" in eng:
        search_url = f"https://duckduckgo.com/?q={encoded}"
    elif "bing" in eng:
        search_url = f"https://www.bing.com/search?q={encoded}"
    else:
        search_url = f"https://www.google.com/search?q={encoded}"

    return open_url(search_url)


def browser_fill_form(fields: dict[str, str], submit: bool = False) -> str:
    """
    Fill out form fields in the active browser window.
    Submitting forms requires spoken confirmation via the permission gate.

    Parameters
    ----------
    fields : dict[str, str]
        Key-value mapping of field names/labels and values to enter.
    submit : bool
        Whether to submit the form after filling (e.g. pressing Enter or clicking submit).
        Requires spoken confirmation before proceeding.
    """
    logger.info(f"browser_fill_form: fields={list(fields.keys())} submit={submit}")

    from jarvis.tools.computer import type_text, press_hotkey, click_element

    filled = []
    for field_name, value in fields.items():
        # Try locating field visually first
        click_res = click_element(f"input field for {field_name}")
        if "Could not find" in click_res:
            # Fall back to tab navigation
            press_hotkey("tab")
            time.sleep(0.05)

        type_text(str(value), press_enter=False)
        filled.append(f"{field_name}='{value}'")
        time.sleep(0.1)

    if submit:
        time.sleep(0.1)
        # Attempt to click submit button or press Enter
        sub_res = click_element("submit button")
        if "Could not find" in sub_res:
            press_hotkey("enter")
        return f"Filled form fields ({', '.join(filled)}) and submitted the form."

    return f"Filled form fields: {', '.join(filled)}. (Did not submit)."
