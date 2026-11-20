"""
jarvis/assistant/client_messages.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Client & Freelance Message Reply Drafter.

Capabilities:
  • Drafts polished client responses for Fiverr, Upwork, and direct clients.
  • Adjusts tone (professional, technical, concise, reassuring, persuasive).
  • STRICT INVARIANT: Jarvis NEVER sends client messages automatically.
    Messages are only sent if the user explicitly triggers the unified messaging
    tool with spoken confirmation.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from typing import Any
from jarvis.logger import logger

_TONE_TEMPLATES = {
    "professional and friendly": (
        "Hi {name},\n\n"
        "Thank you for reaching out! Regarding your inquiry: {context}\n\n"
        "I have reviewed the requirements and everything is on track. I will keep you updated as we progress. "
        "Please let me know if you have any questions in the meantime!\n\n"
        "Best regards,\nAlamin"
    ),
    "technical and concise": (
        "Hi {name},\n\n"
        "Update regarding {context}:\n"
        "• Implementation completed and tested on staging.\n"
        "• All unit tests passing with zero regressions.\n"
        "• Ready for deployment or your review.\n\n"
        "Regards,\nAlamin"
    ),
    "reassuring": (
        "Hi {name},\n\n"
        "Don't worry at all regarding {context} — I have already investigated the issue and identified the root cause. "
        "A fix is being applied and will be fully resolved shortly. I'll notify you the moment it's live.\n\n"
        "Best,\nAlamin"
    ),
    "persuasive": (
        "Hi {name},\n\n"
        "Thanks for getting in touch! I'd love to help you with {context}. "
        "I have extensive experience building scalable Laravel and modern web architectures, and I can deliver a clean, robust solution within your timeline. "
        "Let me know if you'd like to discuss the next steps!\n\n"
        "Best regards,\nAlamin"
    ),
}


def client_draft_reply(
    client_name: str,
    platform: str,
    inquiry_or_context: str,
    tone: str = "professional and friendly",
) -> str:
    """
    Draft a client reply for Fiverr, Upwork, or direct clients in the desired tone.
    The agent never sends this automatically.
    """
    clean_name = client_name.strip()
    clean_platform = platform.strip()
    clean_tone = tone.strip().lower()

    logger.info(f"[Client Drafter] Drafting reply to `{clean_name}` on `{clean_platform}` (Tone: {clean_tone})...")

    # Select template or default
    template = _TONE_TEMPLATES.get(clean_tone, _TONE_TEMPLATES["professional and friendly"])
    draft_body = template.format(name=clean_name, context=inquiry_or_context.strip())

    spoken_summary = (
        f"I drafted a {clean_tone} reply for {clean_name} on {clean_platform}. "
        "I will never send it automatically. You can copy it or ask me to send it via messaging."
    )

    return (
        f"### 💬 Client Reply Draft: `{clean_name}` ({clean_platform})\n"
        f"**Tone**: `{clean_tone}`\n\n"
        f"**Drafted Message**:\n```text\n{draft_body}\n```\n\n"
        f"🛡️ **Safety Notice**: Jarvis never sends client messages automatically. "
        f"To send via WhatsApp, Telegram, or Messenger, say:  \n"
        f"> *\"Send on {clean_platform} to {clean_name}: [message]\"*  \n"
        f"Jarvis will read the final text aloud and wait for your spoken **yes** before sending.\n\n"
        f"📢 *Voice Summary*: \"{spoken_summary}\""
    )
