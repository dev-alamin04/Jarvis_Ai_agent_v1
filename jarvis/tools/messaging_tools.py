"""
jarvis/tools/messaging_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unified Messaging Tool for Jarvis.

Exposes send_message(platform, person_name, text) to the brain tool registry.
Platforms supported: WhatsApp, Facebook Messenger, Telegram.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.messaging import messaging_manager


def send_message(platform: str, person_name: str, text: str) -> str:
    """
    Send a message on WhatsApp, Facebook Messenger, or Telegram using the user's
    own already logged-in browser profile.

    Safety:
      The Permission Gate intercepts every call and requires the user's explicit
      spoken confirmation before anything is sent.

    Parameters
    ----------
    platform : str
        The messaging platform: 'whatsapp', 'messenger', or 'telegram'.
        If forgotten or unclear, Jarvis will ask the user which platform.
    person_name : str
        The recipient's contact name or group name to search for.
    text : str
        The message content to send.
    """
    return messaging_manager.send_message(platform=platform, person_name=person_name, text=text)
