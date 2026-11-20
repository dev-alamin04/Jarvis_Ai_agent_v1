"""
jarvis/model_router.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Intelligent Model Routing.

Routes simple, fast commands to a lightweight model (e.g. gpt-4o-mini)
for sub-300ms latency, and reserves the heavyweight model (e.g. gpt-4o)
for complex coding, debugging, or deep reasoning tasks.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from jarvis.config import get
from jarvis.logger import logger

_DEFAULT_COMPLEX_KEYWORDS = [
    "fix",
    "debug",
    "error",
    "refactor",
    "code",
    "script",
    "explain",
    "patch",
    "analyze",
    "review",
    "laravel",
    "docker",
    "database",
    "bug",
    "stack trace",
    "screen",
    "screenshot",
    "vision",
    "look",
    "see",
    "click",
    "type",
    "mouse",
    "hotkey",
    "press",
    "form",
]


def select_model(user_text: str) -> tuple[str, str]:
    """
    Select the optimal model for the given query.

    Returns
    -------
    tuple[str, str]
        (model_name, decision_reason)
    """
    strategy = get("models.routing_strategy", "auto").lower().strip()
    fast_model = get("models.fast_model", "gpt-4o-mini")
    strong_model = get("models.strong_model", "gpt-4o")

    if strategy == "fast":
        return fast_model, "forced_fast"
    if strategy == "strong":
        return strong_model, "forced_strong"

    # Strategy: "auto"
    text_lower = user_text.lower()
    keywords = get("models.complex_keywords") or _DEFAULT_COMPLEX_KEYWORDS

    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
            logger.info(f"Model router: query matched complex keyword '{kw}' -> routing to {strong_model}")
            return strong_model, f"complex_keyword:{kw}"

    # If query is relatively long (> 30 words), it may require deeper understanding
    if len(user_text.split()) > 30:
        logger.info(f"Model router: query length > 30 words -> routing to {strong_model}")
        return strong_model, "long_prompt"

    # Default to fast model for low-latency voice experience
    logger.info(f"Model router: simple command -> routing to {fast_model}")
    return fast_model, "simple_command"
