"""
jarvis/messaging/__init__.py
"""

from jarvis.messaging.base import BaseMessagingAdapter, ContactSearchResult
from jarvis.messaging.manager import MessagingManager, messaging_manager

__all__ = [
    "BaseMessagingAdapter",
    "ContactSearchResult",
    "MessagingManager",
    "messaging_manager",
]
