"""
jarvis/routines/__init__.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Jarvis Routines Engine.

Allows triggering multi-step action sequences from a single voice command.
Enforces the Permission Gate on every single step.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.routines.config import (
    get_routine,
    load_routines,
    resolve_step_args,
    save_routine,
)
from jarvis.routines.creator import create_routine
from jarvis.routines.executor import execute_routine
from jarvis.routines.voice import (
    handle_create_routine_voice,
    handle_run_routine_voice,
    is_create_routine_command,
    match_routine_trigger,
)
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel

# Register tool risk classifications:
# Running and listing routines are SAFE (inner steps undergo individual gate checks)
# Creating a routine requires spoken confirmation
CENTRAL_TOOL_RISK_TABLE["run_routine"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["list_routines"] = RiskLevel.SAFE
CENTRAL_TOOL_RISK_TABLE["create_routine"] = RiskLevel.NEEDS_CONFIRMATION

__all__ = [
    "load_routines",
    "save_routine",
    "get_routine",
    "resolve_step_args",
    "execute_routine",
    "create_routine",
    "is_create_routine_command",
    "match_routine_trigger",
    "handle_create_routine_voice",
    "handle_run_routine_voice",
]
