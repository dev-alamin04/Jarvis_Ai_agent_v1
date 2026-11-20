"""
jarvis/logger.py
Centralised logging setup. Every module imports `action_log` and `logger` from here.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from jarvis.config import ACTION_LOG, LOG_LEVEL, PROJECT_ROOT

# ── ensure log directory exists ──────────────────────────────────────────────
ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)

# ── root logger (console + action log file) ──────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ACTION_LOG, encoding="utf-8"),
    ],
)

logger = logging.getLogger("jarvis")


def action_log(tool: str, args: dict, result: str, approved: bool = True) -> None:
    """
    Write a structured entry to the action log.
    API keys and secrets are never passed through here—
    args dicts must have them scrubbed before calling this.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    status = "APPROVED" if approved else "DENIED"
    entry = (
        f"[{timestamp}] [{status}] TOOL={tool} "
        f"ARGS={args!r} "
        f"RESULT={result[:300]!r}"
    )
    logger.info(entry)
    try:
        from jarvis import ui_events
        ts_short = datetime.now().strftime("%H:%M:%S")
        ui_events.emit("log", text=f"[{status}] {tool}", ts=ts_short)
    except Exception:
        pass
