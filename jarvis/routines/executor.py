"""
jarvis/routines/executor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Routine Execution Engine.

Executes a sequence of routine steps.
STRICT SECURITY INVARIANT:
  Every step MUST pass through the Permission Gate and Safety Layer.
  A routine can NEVER contain steps that skip or bypass the gate.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from typing import Any, Callable

from jarvis.logger import logger
from jarvis.routines.config import get_routine, resolve_step_args


def execute_routine(
    name_or_routine: str | dict[str, Any],
    speak_fn: Callable[[str], None] | None = None,
    ask_user_fn: Callable[[str], bool] | None = None,
) -> str:
    """
    Execute a routine step by step through the Permission Gate.

    Parameters
    ----------
    name_or_routine : str | dict
        The routine name, trigger phrase, or routine definition dictionary.
    speak_fn : callable | None
        Function to speak output aloud.
    ask_user_fn : callable | None
        Function for confirmation prompts.
    """
    if isinstance(name_or_routine, str):
        routine = get_routine(name_or_routine)
        if not routine:
            err = f"Routine `{name_or_routine}` was not found. Use `list_routines` to see available routines."
            if speak_fn:
                speak_fn(f"I could not find a routine named {name_or_routine}.")
            return err
    else:
        routine = name_or_routine

    title = routine.get("title", routine.get("name", "Routine"))
    steps = routine.get("steps", [])
    logger.info(f"[Routines] Starting execution of routine '{title}' ({len(steps)} steps)...")

    # Announce start
    start_msg = f"Starting {title} routine with {len(steps)} actions."
    if speak_fn:
        try:
            speak_fn(start_msg)
        except Exception:
            pass

    # Import the central tool executor that runs through Permission Gate & Safety Layer
    from jarvis.brain import _execute_tool

    step_results = []
    failed = False
    failure_reason = ""

    for idx, step in enumerate(steps, 1):
        tool_name = step.get("tool", "").strip()
        raw_args = step.get("args", {})
        description = step.get("description", f"Step {idx}")

        if not tool_name:
            continue

        resolved_args = resolve_step_args(raw_args)
        logger.info(f"[Routines] Executing Step {idx}/{len(steps)}: '{description}' ({tool_name})")

        try:
            # ── MANDATORY INVARIANT: Every step goes through _execute_tool ──
            # This guarantees safety pre-check, cost gate, and Permission Gate enforcement!
            result = _execute_tool(
                tool_name=tool_name,
                args=resolved_args,
                speak_fn=speak_fn,
                user_voice_text=title,
            )

            # Check if step was denied by Permission Gate or Safety Layer
            if "DENIED" in str(result) or "PermissionDenied" in str(result) or "BLOCKED" in str(result):
                step_results.append({
                    "step": idx,
                    "description": description,
                    "tool": tool_name,
                    "status": "DENIED",
                    "output": str(result),
                })
                failed = True
                failure_reason = f"Step {idx} ({description}) was denied by the permission gate."
                logger.warning(f"[Routines] {failure_reason}")
                break

            step_results.append({
                "step": idx,
                "description": description,
                "tool": tool_name,
                "status": "COMPLETED",
                "output": str(result),
            })

        except Exception as exc:
            step_results.append({
                "step": idx,
                "description": description,
                "tool": tool_name,
                "status": "ERROR",
                "output": str(exc),
            })
            failed = True
            failure_reason = f"Step {idx} ({description}) failed: {exc}"
            logger.error(f"[Routines] {failure_reason}")
            break

    # Build Spoken Summary
    if failed:
        spoken_summary = f"{title} routine stopped at step {idx}. {failure_reason}"
    else:
        executed_descs = [s["description"] for s in step_results if s["status"] == "COMPLETED"]
        if len(executed_descs) <= 3:
            acts = ", ".join(executed_descs)
            spoken_summary = f"{title} completed: {acts}."
        else:
            spoken_summary = f"{title} completed successfully with all {len(step_results)} actions finished."

    if speak_fn:
        try:
            speak_fn(spoken_summary)
        except Exception:
            pass

    # Markdown Report
    lines = [f"# ⚡ Routine Execution: {title}\n"]
    lines.append(f"> 📢 **Spoken Overview**: *\"{spoken_summary}\"*\n")
    lines.append("### Step Execution Details:")

    for r in step_results:
        status_icon = "✅" if r["status"] == "COMPLETED" else ("🚫" if r["status"] == "DENIED" else "❌")
        lines.append(f"{r['step']}. {status_icon} **{r['description']}** (`{r['tool']}`)")
        if r["output"]:
            first_line = r["output"].strip().splitlines()[0][:100]
            lines.append(f"   - *Output*: `{first_line}`")

    if failed:
        lines.append(f"\n⚠️ **Routine Halted**: {failure_reason}")

    return "\n".join(lines)
