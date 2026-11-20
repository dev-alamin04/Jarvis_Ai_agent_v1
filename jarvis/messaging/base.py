"""
jarvis/messaging/base.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Base Messaging Adapter Interface.

Every platform adapter (WhatsApp, Telegram, Messenger, etc.) inherits from
BaseMessagingAdapter. Adding a new platform only requires creating a new
adapter class implementing this interface.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.config import PROJECT_ROOT, get
from jarvis.logger import logger


@dataclass
class ContactSearchResult:
    """Result of searching for a contact on a messaging platform."""
    status: str  # "exact", "multiple", "none", "not_logged_in", "error"
    contacts: list[str] = field(default_factory=list)
    message: str = ""


class BaseMessagingAdapter(ABC):
    """Abstract base class for all platform adapters."""

    name: str = ""
    display_name: str = ""
    base_url: str = ""

    def __init__(self, profiles_root: Path | None = None):
        self.profiles_root = profiles_root or (PROJECT_ROOT / "data" / "browser_profiles")
        self._playwright = None
        self._context = None
        self._page = None

    @property
    def profile_path(self) -> Path:
        """Dedicated local directory where session cookies & cache are saved."""
        path = self.profiles_root / self.name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_browser_executable(self) -> str | None:
        """Resolve Google Chrome / Chromium executable path."""
        cfg_exec = get("messaging.browser_executable")
        if cfg_exec and Path(cfg_exec).exists():
            return cfg_exec

        # Auto-detect common system binaries
        candidates = ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
        for c in candidates:
            if Path(c).exists():
                return c
        return None

    def sleep_jitter(self, min_s: float = 0.3, max_s: float = 0.8) -> None:
        """Add short human-like delay with random jitter."""
        time.sleep(random.uniform(min_s, max_s))

    def human_type(self, selector: str, text: str, page: Any = None) -> None:
        """
        Type text into an element with human-like keystroke intervals.
        Default ~40-70ms per character to prevent bot detection.
        """
        target_page = page or self._page
        if not target_page:
            return

        min_ms, max_ms = get("messaging.typing_delay_range_ms", [35, 70])
        # Click element to focus
        target_page.click(selector)
        self.sleep_jitter(0.2, 0.4)

        # Type character by character with slight jitter
        for char in text:
            target_page.keyboard.type(char)
            delay = random.uniform(min_ms / 1000.0, max_ms / 1000.0)
            time.sleep(delay)

    def open(self, headless: bool | None = None) -> Any:
        """
        Launch persistent Playwright browser context for this platform
        and navigate to its home web URL.
        """
        if self._page and not self._page.is_closed():
            return self._page

        from playwright.sync_api import sync_playwright

        if headless is None:
            headless = bool(get("messaging.headless", False))

        exec_path = self.get_browser_executable()
        logger.info(
            f"[{self.display_name}] Opening browser (headless={headless}, "
            f"profile={self.profile_path}, exec={exec_path})"
        )

        self._playwright = sync_playwright().start()

        launch_kwargs = {
            "user_data_dir": str(self.profile_path),
            "headless": headless,
            "viewport": {"width": 1280, "height": 800},
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if exec_path:
            launch_kwargs["executable_path"] = exec_path

        self._context = self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

        # Navigate to base URL
        try:
            self._page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
            self.sleep_jitter(1.0, 2.0)
        except Exception as exc:
            logger.warning(f"[{self.display_name}] Navigation note: {exc}")

        return self._page

    @abstractmethod
    def check_login_state(self, page: Any) -> tuple[bool, str]:
        """
        Check if the account is currently logged in.
        Returns:
          (True, "Logged in") or
          (False, "Instructions for user to log in by hand once")
        """
        pass

    @abstractmethod
    def search_contact(self, page: Any, person_name: str) -> ContactSearchResult:
        """
        Search for contact by name.
        If no matches: status='none'
        If multiple matches: status='multiple', contacts=[list of candidate names]
        If exactly 1 match: status='exact', contacts=[candidate], and opens the chat.
        """
        pass

    @abstractmethod
    def select_contact(self, page: Any, contact_name: str) -> bool:
        """
        Select a specific contact candidate after user picks from disambiguation list.
        """
        pass

    @abstractmethod
    def send(self, page: Any, text: str) -> bool:
        """
        Type the text into the active chat message input and press Send.
        """
        pass

    @abstractmethod
    def verify_sent(self, page: Any, text: str) -> bool:
        """
        Verify that the message appeared in the outgoing chat bubbles.
        """
        pass

    def close(self) -> None:
        """Cleanly close context and browser."""
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as exc:
            logger.debug(f"[{self.display_name}] Close note: {exc}")
        finally:
            self._page = None
            self._context = None
            self._playwright = None
