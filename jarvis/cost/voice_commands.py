"""
jarvis/cost/voice_commands.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Natural language voice commands for cost and spending inquiries:
  • "how much have I spent today"
  • "how much this month"
  • "how much did I spend today / this month"
  • "what is my spending today / this month"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from typing import Callable

from jarvis.cost.tracker import get_cost_month, get_cost_today
from jarvis.logger import logger


_TODAY_PATTERNS = [
    r"\bhow much (?:have i|did i|have we)?\s*(?:spent|spend) today\b",
    r"\bhow much today\b",
    r"\bwhat (?:is|was) my (?:spending|cost) today\b",
    r"\b(?:cost|spending) today\b",
    r"\btoday'?s? (?:cost|spending)\b",
]

_MONTH_PATTERNS = [
    r"\bhow much (?:have i|did i|have we)?\s*(?:spent|spend) this month\b",
    r"\bhow much this month\b",
    r"\bwhat (?:is|was) my (?:spending|cost) this month\b",
    r"\b(?:cost|spending) this month\b",
    r"\bthis month'?s? (?:cost|spending)\b",
    r"\bmonthly (?:cost|spending)\b",
]


def is_cost_inquiry(text: str) -> bool:
    """Return True if text matches a cost or spending query."""
    clean = text.lower().strip()
    for pat in _TODAY_PATTERNS + _MONTH_PATTERNS:
        if re.search(pat, clean):
            return True
    return False


def is_today_cost_query(text: str) -> bool:
    """Return True if the query is specifically asking about today's spending."""
    clean = text.lower().strip()
    for pat in _TODAY_PATTERNS:
        if re.search(pat, clean):
            return True
    return "today" in clean or ("month" not in clean and "spent" in clean)


def handle_cost_inquiry(text: str, speak_fn: Callable[[str], None] | None = None) -> str:
    """
    Process a natural language cost inquiry, formulate a concise spoken summary,
    and return a structured markdown response.
    """
    logger.info(f"[Cost Voice Command] Handling inquiry: {text!r}")
    is_today = is_today_cost_query(text)

    if is_today:
        data = get_cost_today()
        spent = data["total_cost"]
        limit = data["daily_limit"]
        pct = data["percent_used"]
        calls = data["call_count"]
        tokens = data["total_tokens"]

        if spent <= 0.0001:
            spoken = f"You have not spent anything today. Your ${limit:.2f} daily budget is fully available."
        else:
            spoken = (
                f"You have spent ${spent:.2f} today across {calls} calls, "
                f"which is {pct:.1f}% of your ${limit:.2f} daily limit."
            )

        report = f"""### 💰 Daily Spending Summary ({data['day_key']})

- **Total Spent**: **${spent:.4f}** / ${limit:.2f} ({pct:.1f}%)
- **Model Queries**: ${data['model_cost']:.4f}
- **Transcription**: ${data['transcription_cost']:.4f}
- **Speech (TTS)**: ${data['speech_cost']:.4f}
- **Tokens Counted**: {tokens:,} tokens
- **Total API Calls**: {calls}

📢 *Voice Reply*: "{spoken}"
"""
    else:
        data = get_cost_month()
        spent = data["total_cost"]
        limit = data["monthly_limit"]
        pct = data["percent_used"]
        calls = data["call_count"]
        tokens = data["total_tokens"]

        if spent <= 0.0001:
            spoken = f"You have not spent anything this month. Your ${limit:.2f} monthly budget is fully available."
        else:
            spoken = (
                f"You have spent ${spent:.2f} this month across {calls} calls, "
                f"which is {pct:.1f}% of your ${limit:.2f} monthly limit."
            )

        report = f"""### 💰 Monthly Spending Summary ({data['month_key']})

- **Total Spent**: **${spent:.4f}** / ${limit:.2f} ({pct:.1f}%)
- **Model Queries**: ${data['model_cost']:.4f}
- **Transcription**: ${data['transcription_cost']:.4f}
- **Speech (TTS)**: ${data['speech_cost']:.4f}
- **Tokens Counted**: {tokens:,} tokens
- **Total API Calls**: {calls}

📢 *Voice Reply*: "{spoken}"
"""

    if speak_fn:
        try:
            speak_fn(spoken)
        except Exception as exc:
            logger.debug(f"[Cost Voice Command] TTS error: {exc}")

    return report.strip()
