"""
jarvis/recon/logger.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Security Reconnaissance Audit Logger.

Logs every security scan and reconnaissance operation with:
  • Target host / URL
  • Timestamp (UTC ISO 8601)
  • Recon tool / operation name
  • Findings summary and severity counts
  • Tamper-evident cryptographic hash chain integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

RECON_LOG_PATH = PROJECT_ROOT / "logs" / "security_recon.log"


def log_recon_scan(
    target: str,
    tool_name: str,
    command: str,
    findings_count: int,
    highest_severity: str = "INFO",
    status: str = "COMPLETED",
    summary: str = "",
) -> None:
    """
    Append an entry to logs/security_recon.log and mirror to the
    cryptographic tamper-evident hash chain.
    """
    RECON_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()

    entry = (
        f"[{timestamp}] [TARGET: {target}] [TOOL: {tool_name}] [STATUS: {status}] "
        f"[SEVERITY: {highest_severity}] [FINDINGS: {findings_count}] "
        f"[CMD: {command}] [SUMMARY: {summary[:150]!r}]\n"
    )

    try:
        with open(RECON_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as exc:
        logger.error(f"[Recon Logger] Failed to write to {RECON_LOG_PATH}: {exc}")

    # Mirror to tamper-evident audit log
    try:
        from jarvis.safety import log_tamper_evident_action
        log_tamper_evident_action(
            tool=f"recon:{tool_name}",
            args={"target": target, "command": command},
            result=f"{status} (Findings: {findings_count}, Max: {highest_severity}): {summary[:100]}",
            status=status,
        )
    except Exception as exc:
        logger.debug(f"[Recon Logger] Tamper-evident log mirror error: {exc}")
