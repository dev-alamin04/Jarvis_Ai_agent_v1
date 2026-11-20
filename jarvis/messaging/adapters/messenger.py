"""
jarvis/messaging/adapters/messenger.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Facebook Messenger Web Adapter.

Uses a dedicated persistent Playwright profile (data/browser_profiles/messenger).
First-time setup: user logs into Facebook Messenger by hand in the opened window.
Jarvis never asks for, reads, or handles user passwords.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.logger import logger
from jarvis.messaging.base import BaseMessagingAdapter, ContactSearchResult


class MessengerAdapter(BaseMessagingAdapter):
    """Adapter for Facebook Messenger Web."""

    name = "messenger"
    display_name = "Facebook Messenger"
    base_url = "https://www.messenger.com"

    LOGIN_SELECTORS = [
        "#email",
        "#pass",
        "button[name='login']",
        "input[name='email']",
        "button:has-text('Log In')",
    ]
    LOGGED_IN_SELECTORS = [
        "input[placeholder*='Search']",
        "div[role='search']",
        "div[role='navigation']",
        "div[aria-label*='Chats']",
    ]
    SEARCH_INPUT_SELECTORS = [
        "input[placeholder*='Search']",
        "input[aria-label*='Search Messenger']",
        "div[role='search'] input",
    ]
    CHAT_INPUT_SELECTORS = [
        "div[role='textbox'][aria-label*='Message']",
        "div[contenteditable='true'][role='textbox']",
        "div[aria-label*='Message'][contenteditable='true']",
    ]
    MSG_CONTAINER_SELECTORS = [
        "div[dir='auto'][style*='background-color']",
        "div[role='row']",
        "div[data-scope='messages_table']",
    ]

    def check_login_state(self, page: Any) -> tuple[bool, str]:
        """Verify whether Messenger is logged in or at the login form."""
        start_time = time.time()
        while time.time() - start_time < 10:
            for sel in self.LOGGED_IN_SELECTORS:
                try:
                    if page.locator(sel).first.is_visible():
                        logger.info("[Messenger] User is logged in.")
                        return True, "Logged in"
                except Exception:
                    pass

            for sel in self.LOGIN_SELECTORS:
                try:
                    if page.locator(sel).first.is_visible():
                        logger.warning("[Messenger] Login screen detected.")
                        return False, (
                            "Facebook Messenger is not logged in. Please log in by hand once "
                            "in the opened browser window. Jarvis never asks for or handles "
                            "your password."
                        )
                except Exception:
                    pass

            time.sleep(1.0)

        content = page.content().lower()
        if "log into facebook" in content or "connect with your favorite people" in content:
            return False, "Facebook Messenger requires login. Please log in in the opened browser window."

        for sel in self.SEARCH_INPUT_SELECTORS:
            if page.locator(sel).count() > 0:
                return True, "Logged in"

        return False, "Messenger did not load completely. Please log in by hand in the opened browser window."

    def search_contact(self, page: Any, person_name: str) -> ContactSearchResult:
        """Search for a contact on Facebook Messenger."""
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
                message="Could not find Messenger search bar. The layout may have changed."
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
            items = page.locator("ul[role='listbox'] li, div[role='row'], div[role='gridcell'] span")
            count = items.count()
            for i in range(min(count, 12)):
                item = items.nth(i)
                text = item.inner_text().strip()
                if not text:
                    continue
                first_line = text.split("\n")[0].strip()
                if first_line and first_line not in candidates and len(first_line) > 1:
                    candidates.append(first_line)
        except Exception as exc:
            logger.debug(f"[Messenger] Candidate extraction note: {exc}")

        query_lower = person_name.strip().lower()
        matched = [c for c in candidates if query_lower in c.lower()]
        if not matched and candidates:
            matched = candidates

        if not matched:
            return ContactSearchResult(
                status="none",
                message=f"No contact named '{person_name}' found on Facebook Messenger."
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
                f"I found {len(matched)} contacts matching '{person_name}' on Messenger: "
                f"{', '.join(matched[:5])}. Which one would you like to message?"
            )
        )

    def _click_contact_row(self, page: Any, contact_name: str) -> bool:
        """Click on the contact result to open chat."""
        try:
            loc = page.locator(f"span:has-text('{contact_name}'), li:has-text('{contact_name}')").first
            if loc.is_visible():
                loc.click()
                self.sleep_jitter(0.8, 1.5)
                return True
        except Exception as exc:
            logger.debug(f"[Messenger] Click contact note: {exc}")
        return False

    def select_contact(self, page: Any, contact_name: str) -> bool:
        return self._click_contact_row(page, contact_name)

    def send(self, page: Any, text: str) -> bool:
        """Type and send message in the open Messenger chat."""
        self.sleep_jitter(0.4, 0.8)

        chat_input = None
        for sel in self.CHAT_INPUT_SELECTORS:
            loc = page.locator(sel).first
            if loc.is_visible():
                chat_input = loc
                break

        if not chat_input:
            logger.error("[Messenger] Message input box not found.")
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
        """Verify message appeared in chat thread."""
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
                            logger.info(f"[Messenger] Verified message delivered: '{snippet}'")
                            return True
            except Exception:
                pass

        if snippet in page.content():
            return True

        return False
