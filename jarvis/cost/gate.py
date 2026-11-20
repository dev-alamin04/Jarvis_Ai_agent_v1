"""
jarvis/cost/gate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cost Confirmation Gate for Expensive Actions.

At 100% of the daily or monthly spending limit:
  • Automatically downgraded to a cheaper model (gpt-4o-mini).
  • Before continuing with expensive actions (vision, heavy debugging, full scans),
    prompts the user with spoken confirmation:
    "You have reached 100% of your daily spending limit ($1.05 of $1.00).
     Do you want to proceed with expensive action '...'?"
  • Requires spoken "yes" to proceed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from typing import Callable

from jarvis.cost.config import get_expensive_tools
from jarvis.cost.tracker import get_cost_today, is_hard_limit_reached
from jarvis.logger import logger
from jarvis.permission_gate import PermissionDenied, _ask_user


def check_expensive_action_confirmation(
    action_name: str,
    speak_fn: Callable[[str], None] | None = None,
    ask_user_fn: Callable[[str], bool] | None = None,
) -> bool:
    """
    Check if the budget is exhausted (100%) and the proposed action is expensive.
    If so, prompt the user for spoken confirmation before proceeding.

    Raises PermissionDenied if the user declines.
    """
    expensive_tools = get_expensive_tools()
    clean_action = action_name.strip()

    # Only gate if hard limit is reached AND tool is classified as expensive
    if not is_hard_limit_reached():
        return True

    if clean_action not in expensive_tools and not any(exp in clean_action for exp in ["vision", "screen", "deploy", "scan"]):
        return True

    today = get_cost_today()
    spent = today["total_cost"]
    limit = today["daily_limit"]

    prompt_text = (
        f"You have reached your daily spending limit (${spent:.2f} of ${limit:.2f}). "
        f"Do you want to proceed with expensive action '{clean_action}'?"
    )
    logger.warning(f"[Cost Gate] {prompt_text}")

    if speak_fn:
        try:
            speak_fn(prompt_text)
        except Exception:
            pass

    ask = ask_user_fn or _ask_user
    approved = ask(prompt_text)

    if not approved:
        logger.warning(f"[Cost Gate] User denied expensive action '{clean_action}' due to spending limit.")
        raise PermissionDenied(
            f"Action `{clean_action}` was cancelled: Daily spending limit of ${limit:.2f} reached "
            f"(current spend: ${spent:.2f}) and user declined confirmation."
        )

    logger.info(f"[Cost Gate] User approved expensive action '{clean_action}' despite spending limit.")
    return True
