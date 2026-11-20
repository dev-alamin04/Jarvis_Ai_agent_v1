"""
jarvis/tools/routine_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool Registry bridge for Routines:
  run_routine, list_routines, create_routine.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.routines.config import load_routines
from jarvis.routines.creator import create_routine as _create_routine
from jarvis.routines.executor import execute_routine as _execute_routine


def run_routine(routine_name: str) -> str:
    """
    Execute a configured routine by name or trigger phrase (e.g. 'work_mode', 'end_of_day', 'server_check').
    Every step inside the routine is executed through the Permission Gate and Safety Layer.
    """
    return _execute_routine(routine_name)


def list_routines() -> str:
    """
    List all configured routines, their voice trigger phrases, and descriptions.
    """
    routines = load_routines()
    if not routines:
        return "No routines currently configured."

    lines = ["### ⚡ Configured Routines\n"]
    for idx, (name, r) in enumerate(routines.items(), 1):
        title = r.get("title", name.title())
        desc = r.get("description", "No description")
        triggers = ", ".join(f"`{t}`" for t in r.get("triggers", []))
        step_count = len(r.get("steps", []))
        lines.append(
            f"{idx}. **{title}** (`{name}`)\n"
            f"   - **Description**: {desc}\n"
            f"   - **Voice Triggers**: {triggers}\n"
            f"   - **Steps**: {step_count} actions\n"
        )

    return "\n".join(lines).strip()


def create_routine(name: str, steps_description: str) -> str:
    """
    Create a new routine with steps parsed from natural language.
    Reads back the parsed steps and saves the routine only after user spoken confirmation.
    """
    return _create_routine(name=name, steps_description=steps_description)


__all__ = [
    "run_routine",
    "list_routines",
    "create_routine",
]
