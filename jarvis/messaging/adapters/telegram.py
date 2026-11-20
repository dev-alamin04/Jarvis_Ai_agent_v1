"""
jarvis/messaging/adapters/telegram.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Telegram Web & MTProto Messaging Adapter.

Primary Backend:
  • Telegram Web A (https://web.telegram.org/a/) via Playwright.
  • Uses dedicated persistent profile: data/browser_profiles/telegram.
  • User logs in once via QR code or phone SMS; session is preserved.

Alternative Backend (Telethon MTProto API):
  • Configurable via `messaging.telegram.backend: "telethon"` in config.yaml.
  • Comparison:
      - Telethon connects directly to Telegram MTProto servers via api_id & api_hash.
      - It is significantly faster and completely immune to HTML/DOM changes.
      - However, it requires registering an app on my.telegram.org to get credentials,
        and automated messaging on new accounts can trigger MTProto peer flood limits.
      - Playwright Web A requires no API keys and lets the user visually monitor
        and confirm message dispatch.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.config import get
from jarvis.logger import logger
from jarvis.messaging.base import BaseMessagingAdapter, ContactSearchResult


class TelegramAdapter(BaseMessagingAdapter):
    """Adapter for Telegram Web A."""

    name = "telegram"
    display_name = "Telegram"
    base_url = "https://web.telegram.org/a/"

    LOGIN_SELECTORS = [
        "#sign-in-phone-number",
        "button:has-text('Log in by QR code')",
        "button:has-text('Log in by phone number')",
        ".auth-form",
        ".qr-container",
    ]
    LOGGED_IN_SELECTORS = [
        "#telegram-search-input",
        ".chat-list",
        ".sidebar-header",
        "#MiddleColumn",
        "div.chat-item-clickable",
    ]
    SEARCH_INPUT_SELECTORS = [
        "#telegram-search-input",
        "input.form-control[placeholder*='Search']",
        "input[placeholder*='Search']",
        ".input-search input",
    ]
    CHAT_INPUT_SELECTORS = [
        "#editable-message-text",
        "div.input-message-input[contenteditable='true']",
        ".input-message-text",
        "div[contenteditable='true'][role='textbox']",
    ]
    SEND_BUTTON_SELECTORS = [
        "button.send",
        "button[aria-label*='Send']",
        "button.btn-send",
    ]
    MSG_CONTAINER_SELECTORS = [
        ".Message.own",
        ".message.own",
        ".MessageList .own",
        "div[data-is-own-message='true']",
    ]

    def check_login_state(self, page: Any) -> tuple[bool, str]:
        """Check if Telegram Web is logged in or awaiting login/QR code."""
        start_time = time.time()
        while time.time() - start_time < 10:
            for sel in self.LOGGED_IN_SELECTORS:
                try:
                    if page.locator(sel).first.is_visible():
                        logger.info("[Telegram] User is logged in.")
                        return True, "Logged in"
                except Exception:
                    pass

            for sel in self.LOGIN_SELECTORS:
                try:
                    if page.locator(sel).first.is_visible():
                        logger.warning("[Telegram] Login screen detected.")
                        return False, (
                            "Telegram Web is not logged in. Please log in once in the opened "
                            "browser window (using QR code or phone number). Jarvis will remember "
                            "your session for future commands."
                        )
                except Exception:
                    pass

            time.sleep(1.0)

        # Fallback check
        content = page.content().lower()
        if "sign in to telegram" in content or "log in by qr code" in content:
            return False, "Telegram requires login. Please log in in the opened browser window."

        for sel in self.SEARCH_INPUT_SELECTORS:
            if page.locator(sel).count() > 0:
                return True, "Logged in"

        return False, "Telegram Web did not load completely. Please log in by hand in the opened browser window."

    def search_contact(self, page: Any, person_name: str) -> ContactSearchResult:
        """Search for contact on Telegram Web A."""
        self.sleep_jitter(0.5, 1.0)

        search_elem = None
        for sel in self.SEARCH_INPUT_SELECTORS:
            loc = page.locator(sel).first
            if loc.is_visible():
                search_elem = loc
                break

        if not search_elem:
            return ContactSearchResult(
                status="error",
                message="Could not find Telegram search bar. Layout may have changed."
            )

        search_elem.click()
        self.sleep_jitter(0.2, 0.4)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        self.sleep_jitter(0.2, 0.4)

        for ch in person_name:
            page.keyboard.type(ch)
            time.sleep(0.04)

        self.sleep_jitter(1.0, 1.8)

        candidates: list[str] = []
        try:
            items = page.locator(".ListItem.chat-item-clickable, .search-group .ListItem, .chatlist-top .ListItem")
            count = items.count()
            for i in range(min(count, 10)):
                item = items.nth(i)
                text = item.inner_text().strip()
                if not text:
                    continue
                first_line = text.split("\n")[0].strip()
                if first_line and first_line not in candidates:
                    candidates.append(first_line)
        except Exception as exc:
            logger.debug(f"[Telegram] Candidate extraction note: {exc}")

        query_lower = person_name.strip().lower()
        matched = [c for c in candidates if query_lower in c.lower()]
        if not matched and candidates:
            matched = candidates

        if not matched:
            return ContactSearchResult(
                status="none",
                message=f"No contact named '{person_name}' found on Telegram."
            )

        exact_matches = [c for c in matched if c.strip().lower() == query_lower]
        if len(exact_matches) == 1:
            chosen = exact_matches[0]
            self._click_contact_row(page, chosen)
            return ContactSearchResult(status="exact", contacts=[chosen])

        if len(matched) == 1:
            chosen = matched[0]
            self._click_contact_row(page, chosen)
            return ContactSearchResult(status="exact", contacts=[chosen])

        return ContactSearchResult(
            status="multiple",
            contacts=matched,
            message=(
                f"I found {len(matched)} contacts matching '{person_name}' on Telegram: "
                f"{', '.join(matched[:5])}. Which one would you like to message?"
            )
        )

    def _click_contact_row(self, page: Any, contact_name: str) -> bool:
        """Click on the contact in search results."""
        try:
            loc = page.locator(f".ListItem:has-text('{contact_name}'), .chat-item-clickable:has-text('{contact_name}')").first
            if loc.is_visible():
                loc.click()
                self.sleep_jitter(0.8, 1.5)
                return True
        except Exception as exc:
            logger.debug(f"[Telegram] Click contact note: {exc}")
        return False

    def select_contact(self, page: Any, contact_name: str) -> bool:
        return self._click_contact_row(page, contact_name)

    def send(self, page: Any, text: str) -> bool:
        """Type and send message in active Telegram chat."""
        self.sleep_jitter(0.4, 0.8)

        chat_input = None
        for sel in self.CHAT_INPUT_SELECTORS:
            loc = page.locator(sel).first
            if loc.is_visible():
                chat_input = loc
                break

        if not chat_input:
            logger.error("[Telegram] Message input box not found.")
            return False

        chat_input.click()
        self.sleep_jitter(0.2, 0.4)

        for char in text:
            page.keyboard.type(char)
            time.sleep(0.035)

        self.sleep_jitter(0.3, 0.6)
        page.keyboard.press("Enter")
        self.sleep_jitter(0.8, 1.5)
        return True

    def verify_sent(self, page: Any, text: str) -> bool:
        """Verify message appeared in outgoing bubbles."""
        self.sleep_jitter(0.5, 1.0)
        snippet = text[:40].strip()

        for sel in self.MSG_CONTAINER_SELECTORS:
            try:
                elements = page.locator(sel)
                count = elements.count()
                if count > 0:
                    for i in range(max(0, count - 3), count):
                        msg_text = elements.nth(i).inner_text()
                        if snippet in msg_text:
                            logger.info(f"[Telegram] Verified message delivered: '{snippet}'")
                            return True
            except Exception:
                pass

        if snippet in page.content():
            return True

        return False
