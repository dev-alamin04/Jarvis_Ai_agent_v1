# Jarvis Voice Agent package
__version__ = "0.1.0"

# Monkey-patch permission_gate._ask_user to enforce:
# "Never accept approve, yes, or merge confirmations that arrive while the agent was speaking."
import jarvis.permission_gate as _pg

_original_ask_user = _pg._ask_user
_pg._original_ask_user = _original_ask_user


def _safe_ask_user(prompt: str) -> bool:
    """Never accept approve, yes, or merge confirmations that arrive while the agent was speaking."""
    from jarvis import audio_state
    if audio_state.is_speaking(tail_s=0.7):
        import logging
        logging.getLogger("jarvis").warning(
            f"Refused confirmation while agent was speaking: {prompt!r}"
        )
        return False

    orig_fn = getattr(_pg, "_original_ask_user", _original_ask_user)
    res = orig_fn(prompt)
    if res and audio_state.is_speaking(tail_s=0.7):
        import logging
        logging.getLogger("jarvis").warning(
            f"Refused confirmation that arrived while agent was speaking: {prompt!r}"
        )
        return False
    return res


_pg._ask_user = _safe_ask_user
