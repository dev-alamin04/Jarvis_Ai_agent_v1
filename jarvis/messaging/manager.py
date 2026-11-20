"""
jarvis/messaging/manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unified Messaging Manager.

Manages platform adapters (WhatsApp, Telegram, Facebook Messenger),
coordinates persistent Playwright browser sessions, enforces rate limits,
handles contact disambiguation, and ensures verification of delivered messages.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from typing import Type

from jarvis.logger import logger
from jarvis.messaging.adapters import MessengerAdapter, TelegramAdapter, WhatsAppAdapter
from jarvis.messaging.base import BaseMessagingAdapter
from jarvis.messaging.rate_limiter import can_send, log_audit, record_send


class MessagingManager:
    """Central registry and coordinator for messaging adapters."""

    def __init__(self):
        self._adapters: dict[str, BaseMessagingAdapter] = {}
        # Register standard default adapters
        self.register_adapter(WhatsAppAdapter)
        self.register_adapter(TelegramAdapter)
        self.register_adapter(MessengerAdapter)

    def register_adapter(self, adapter_cls: Type[BaseMessagingAdapter]) -> None:
        """Register a new platform adapter."""
        instance = adapter_cls()
        self._adapters[instance.name.lower()] = instance
        logger.info(f"Registered messaging adapter: {instance.name} ({instance.display_name})")

    def get_adapter(self, platform: str) -> BaseMessagingAdapter | None:
        """Look up adapter by platform name."""
        p = platform.lower().strip()
        # Aliases
        if p in ("fb", "facebook", "facebook messenger"):
            p = "messenger"
        elif p in ("wa", "whats app"):
            p = "whatsapp"
        elif p in ("tg", "tele"):
            p = "telegram"
        return self._adapters.get(p)

    def send_message(self, platform: str, person_name: str, text: str) -> str:
        """
        Execute message delivery on the specified platform.

        Flow:
          1. Validate inputs (ask for platform if omitted).
          2. Check daily rate limit per platform.
          3. Launch dedicated persistent browser profile.
          4. Check login/checkpoint status.
          5. Search contact (never guesses between similar names).
          6. Send message with human-like delays.
          7. Verify message delivery in chat view.
          8. Audit log (without logging message text).
        """
        if not platform or not platform.strip():
            return "Which platform would you like to send this message on: WhatsApp, Messenger, or Telegram?"

        if not person_name or not person_name.strip():
            return "Who would you like to send this message to?"

        if not text or not text.strip():
            return "What message would you like to send?"

        adapter = self.get_adapter(platform)
        if not adapter:
            supported = ", ".join(sorted(a.display_name for a in self._adapters.values()))
            return f"Platform '{platform}' is not supported. Supported platforms are: {supported}."

        clean_recipient = person_name.strip()
        clean_text = text.strip()

        # 1. Check daily rate limit
        allowed, reason = can_send(adapter.name)
        if not allowed:
            log_audit(adapter.name, clean_recipient, clean_text, status="RATE_LIMITED")
            return reason

        # 2. Open persistent browser profile
        try:
            page = adapter.open()
        except Exception as exc:
            logger.error(f"[{adapter.display_name}] Failed to open browser: {exc}")
            log_audit(adapter.name, clean_recipient, clean_text, status="ERROR_BROWSER")
            return f"Failed to open {adapter.display_name} in browser: {exc}"

        # 3. Check login state
        is_logged_in, login_msg = adapter.check_login_state(page)
        if not is_logged_in:
            log_audit(adapter.name, clean_recipient, clean_text, status="NOT_LOGGED_IN")
            return login_msg

        # 4. Search contact
        search_res = adapter.search_contact(page, clean_recipient)
        if search_res.status == "none":
            log_audit(adapter.name, clean_recipient, clean_text, status="CONTACT_NOT_FOUND")
            return search_res.message or f"No contact named '{clean_recipient}' found on {adapter.display_name}."

        if search_res.status == "multiple":
            # Never guess between similar names; ask user for exact person
            log_audit(adapter.name, clean_recipient, clean_text, status="AMBIGUOUS_CONTACT")
            return search_res.message

        if search_res.status == "error":
            log_audit(adapter.name, clean_recipient, clean_text, status="ERROR_SEARCH")
            return search_res.message or "An error occurred while searching for the contact."

        # 5. Type and send message
        send_ok = adapter.send(page, clean_text)
        if not send_ok:
            log_audit(adapter.name, clean_recipient, clean_text, status="ERROR_SEND")
            return f"Failed to send the message to {clean_recipient} on {adapter.display_name}."

        # 6. Verify delivery
        verified = adapter.verify_sent(page, clean_text)
        if verified:
            record_send(adapter.name)
            log_audit(adapter.name, clean_recipient, clean_text, status="SENT")
            return f"Message sent on {adapter.display_name} to {clean_recipient} and verified."

        # Message sent but verification couldn't immediately confirm
        record_send(adapter.name)
        log_audit(adapter.name, clean_recipient, clean_text, status="SENT_UNVERIFIED")
        return (
            f"Message sent to {clean_recipient} on {adapter.display_name}, "
            "but could not confirm checkmark receipt. Please check the open chat window."
        )


messaging_manager = MessagingManager()
