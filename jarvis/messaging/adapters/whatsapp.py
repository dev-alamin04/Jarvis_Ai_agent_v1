"""
jarvis/messaging/adapters/whatsapp.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WhatsApp Web Messaging Adapter.

Uses a dedicated persistent Playwright profile (data/browser_profiles/whatsapp).
First-time setup: user scans the QR code once by hand; Jarvis never handles credentials.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.logger import logger
from jarvis.messaging.base import BaseMessagingAdapter, ContactSearchResult


class WhatsAppAdapter(BaseMessagingAdapter):
    """Adapter for WhatsApp Web."""

    name = "whatsapp"
    display_name = "WhatsApp"
    base_url = "https://web.whatsapp.com"

    # Selectors for WhatsApp Web
    QR_SELECTORS = [
        "canvas[aria-label*='Scan']",
        "div[data-ref]",
        "[data-testid='qrcode']",
        "div._akau",
    ]
    LOGGED_IN_SELECTORS = [
        "#side",
        "div[data-tab='3']",
        "[data-testid='chat-list-search']",
        "header[data-testid='chatlist-header']",
    ]
    SEARCH_INPUT_SELECTORS = [
        "div[contenteditable='true'][data-tab='3']",
        "div[role='textbox'][title*='Search']",
        "[data-testid='chat-list-search']",
        "div._ai08",
    ]
    CHAT_INPUT_SELECTORS = [
        "footer div[contenteditable='true']",
        "div[contenteditable='true'][data-tab='10']",
        "div[role='textbox'][spellcheck='true']",
        "div._ak1r",
    ]
    SEND_BUTTON_SELECTORS = [
        "button[data-testid='compose-btn-send']",
        "span[data-icon='send']",
        "button[aria-label*='Send']",
    ]
    MSG_CONTAINER_SELECTORS = [
        "div.message-out",
        "div[data-testid='msg-container']",
        "div._amk4",
    ]

    def check_login_state(self, page: Any) -> tuple[bool, str]:
        """Verify whether WhatsApp Web is authenticated or waiting for QR code."""
        # Wait up to 10 seconds for either QR code or chat list to appear
        start_time = time.time()
        while time.time() - start_time < 12:
            # Check logged in
            for sel in self.LOGGED_IN_SELECTORS:
                try:
                    if page.locator(sel).first.is_visible():
                        logger.info("[WhatsApp] User is logged in.")
                        return True, "Logged in"
                except Exception:
                    pass

            # Check QR code
            for sel in self.QR_SELECTORS:
                try:
                    if page.locator(sel).first.is_visible():
                        logger.warning("[WhatsApp] QR code detected - login required.")
                        return False, (
                            "WhatsApp Web is not logged in. Please scan the QR code displayed "
                            "in the opened browser window with your WhatsApp mobile app (Linked Devices). "
                            "You only need to do this once."
                        )
                except Exception:
                    pass

            time.sleep(1.0)

        # Fallback check
        content = page.content().lower()
        if "to use whatsapp on your computer" in content or "scan this qr code" in content:
            return False, "WhatsApp requires a one-time QR code scan. Please scan it in the browser window."

        # If chat search exists
        for sel in self.SEARCH_INPUT_SELECTORS:
            if page.locator(sel).count() > 0:
                return True, "Logged in"

        return False, "WhatsApp Web did not load or is not logged in. Please log in by hand in the opened browser window."

    def search_contact(self, page: Any, person_name: str) -> ContactSearchResult:
        """Search for a contact or group by name on WhatsApp Web."""
        self.sleep_jitter(0.5, 1.0)

        # Find search box
        search_elem = None
        for sel in self.SEARCH_INPUT_SELECTORS:
            loc = page.locator(sel).first
            if loc.is_visible():
                search_elem = loc
                break

        if not search_elem:
            return ContactSearchResult(
                status="error",
                message="Could not find WhatsApp contact search bar. The web layout may have changed."
            )

        # Focus and clear search box
        search_elem.click()
        self.sleep_jitter(0.2, 0.4)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        self.sleep_jitter(0.2, 0.4)

        # Type search query
        for ch in person_name:
            page.keyboard.type(ch)
            time.sleep(0.04)

        self.sleep_jitter(1.0, 1.8)

        # Look for search result rows in side pane
        candidates: list[str] = []
        try:
            # Query visible chat list / search result items
            items = page.locator("#pane-side div[role='listitem'], #pane-side div[data-testid='cell-frame-container'], div[aria-label='Search results.'] div[role='listitem']")
            count = items.count()

            for i in range(min(count, 10)):
                item = items.nth(i)
                text = item.inner_text().strip()
                if not text:
                    continue
                # First line is usually contact name
                first_line = text.split("\n")[0].strip()
                if first_line and first_line not in candidates:
                    candidates.append(first_line)
        except Exception as exc:
            logger.debug(f"[WhatsApp] Result extraction note: {exc}")

        # Filter candidates matching query
        query_lower = person_name.strip().lower()
        matched = [c for c in candidates if query_lower in c.lower()]
        if not matched and candidates:
            matched = candidates

        if not matched:
            return ContactSearchResult(
                status="none",
                message=f"No contact named '{person_name}' found on WhatsApp."
            )

        # Exact match or single candidate
        exact_matches = [c for c in matched if c.strip().lower() == query_lower]
        if len(exact_matches) == 1:
            chosen = exact_matches[0]
            self._click_contact_row(page, chosen)
            return ContactSearchResult(status="exact", contacts=[chosen])

        if len(matched) == 1:
            chosen = matched[0]
            self._click_contact_row(page, chosen)
            return ContactSearchResult(status="exact", contacts=[chosen])

        # Multiple candidates: never guess! Ask user
        return ContactSearchResult(
            status="multiple",
            contacts=matched,
            message=(
                f"I found {len(matched)} contacts matching '{person_name}' on WhatsApp: "
                f"{', '.join(matched[:5])}. Which one would you like to message?"
            )
        )

    def _click_contact_row(self, page: Any, contact_name: str) -> bool:
        """Click on the contact row to open their chat."""
        try:
            loc = page.locator(f"span[title='{contact_name}'], span:has-text('{contact_name}')").first
            if loc.is_visible():
                loc.click()
                self.sleep_jitter(0.8, 1.5)
                return True
        except Exception as exc:
            logger.debug(f"[WhatsApp] Click row note: {exc}")
        return False

    def select_contact(self, page: Any, contact_name: str) -> bool:
        """Select specific contact chosen by user."""
        return self._click_contact_row(page, contact_name)

    def send(self, page: Any, text: str) -> bool:
        """Type and send message in the active WhatsApp chat."""
        self.sleep_jitter(0.4, 0.8)

        # Locate chat input
        chat_input = None
        for sel in self.CHAT_INPUT_SELECTORS:
            loc = page.locator(sel).first
            if loc.is_visible():
                chat_input = loc
                break

        if not chat_input:
            logger.error("[WhatsApp] Could not find message input box.")
            return False

        chat_input.click()
        self.sleep_jitter(0.2, 0.4)

        # Type message with human typing interval
        for char in text:
            page.keyboard.type(char)
            time.sleep(0.035)

        self.sleep_jitter(0.3, 0.6)

        # Press Enter to send
        page.keyboard.press("Enter")
        self.sleep_jitter(0.8, 1.5)
        return True

    def verify_sent(self, page: Any, text: str) -> bool:
        """Verify message appears in outgoing messages."""
        self.sleep_jitter(0.5, 1.0)
        snippet = text[:40].strip()

        # Check outgoing message containers
        for sel in self.MSG_CONTAINER_SELECTORS:
            try:
                elements = page.locator(sel)
                count = elements.count()
                if count > 0:
                    # Check the last 3 outgoing messages
                    for i in range(max(0, count - 3), count):
                        msg_text = elements.nth(i).inner_text()
                        if snippet in msg_text:
                            logger.info(f"[WhatsApp] Verified outgoing message delivered: '{snippet}'")
                            return True
            except Exception:
                pass

        # Fallback check page text
        if snippet in page.content():
            return True

        return False
