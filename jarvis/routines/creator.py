"""
jarvis/routines/creator.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voice Routine Creator.

Allows creating routines by voice:
  "make a routine called study mode that opens chrome to google.com and plays youtube lofi"

STRICT INVARIANTS:
  1. The agent reads the steps back aloud.
  2. The routine is saved ONLY after user spoken confirmation ("yes").
  3. Every step uses valid tools in TOOL_REGISTRY that pass through the Permission Gate.
  4. A routine can never contain steps that skip or bypass the gate.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from typing import Any, Callable

from jarvis.logger import logger
from jarvis.permission_gate import PermissionDenied, _ask_user
from jarvis.routines.config import save_routine


def parse_steps_from_text(intent_text: str) -> list[dict[str, Any]]:
    """
    Parse natural language description into tool execution steps.
    Supports chaining via 'and', 'then', commas, and common action phrases.
    """
    clean = intent_text.strip()
    # Split by clause conjunctions: 'and then', 'then', 'and', or commas followed by action verbs
    chunks = re.split(r"\s+(?:and then|then|and)\s+|,\s*", clean, flags=re.IGNORECASE)
    chunks = [c.strip() for c in chunks if c.strip()]

    steps: list[dict[str, Any]] = []

    for chunk in chunks:
        c_lower = chunk.lower()

        # 1. Open URL in browser
        # e.g. "open chrome to https://google.com", "opens chrome to https://google.com", "open browser to localhost", "open https://..."
        m_url = re.search(r"(?:opens?\s+(?:chrome|browser|firefox)\s+(?:to|at)\s+|opens?\s+)(https?://[^\s]+|localhost[^\s]*|www\.[^\s]+|[a-z0-9\-]+\.[a-z]{2,}[^\s]*)", c_lower)
        if m_url:
            url = m_url.group(1)
            if not url.startswith("http"):
                url = "http://" + url
            steps.append({
                "tool": "browser_open",
                "args": {"url": url},
                "description": f"Open browser to {url}",
            })
            continue

        # 2. Open Application (VS Code, terminal, etc.)
        # e.g. "open vs code", "opens code", "open terminal"
        m_app = re.search(r"opens?\s+(?:app\s+)?(vs\s*code|vscode|code|terminal|browser|chrome|firefox|nautilus|files)", c_lower)
        if m_app:
            app_raw = m_app.group(1).replace(" ", "")
            app_name = "code" if "code" in app_raw else app_raw
            steps.append({
                "tool": "open_app",
                "args": {"app_name": app_name, "file_or_args": "{active_project_path}" if app_name == "code" else None},
                "description": f"Open {app_name.upper()}",
            })
            continue

        # 3. Play YouTube
        # e.g. "play youtube lofi beats", "plays yt synthwave"
        m_yt = re.search(r"plays?\s+(?:youtube|yt)\s+(.+)", c_lower)
        if m_yt:
            query = m_yt.group(1).strip()
            steps.append({
                "tool": "play_youtube",
                "args": {"query": query},
                "description": f"Play YouTube {query}",
            })
            continue

        # 4. Start Laravel dev server
        if any(w in c_lower for w in ["start", "starts", "starting"]) and ("server" in c_lower or "artisan serve" in c_lower):
            steps.append({
                "tool": "run_shell_command",
                "args": {"command": "cd {active_project_path} && php artisan serve > /dev/null 2>&1 &"},
                "description": "Start Laravel development server",
            })
            continue

        # 5. Stop dev servers
        if any(w in c_lower for w in ["stop", "stops", "kill", "kills"]) and ("server" in c_lower or "dev" in c_lower):
            steps.append({
                "tool": "run_shell_command",
                "args": {"command": "pkill -f 'artisan serve' || true"},
                "description": "Stop local development servers",
            })
            continue

        # 6. Run Laravel tests
        if "test" in c_lower and any(w in c_lower for w in ["run", "runs", "laravel", "pest", "phpunit"]):
            steps.append({
                "tool": "laravel_run_tests",
                "args": {},
                "description": "Run Laravel tests",
            })
            continue

        # 7. Show git status
        if "git status" in c_lower or (any(w in c_lower for w in ["show", "shows", "check"]) and "git" in c_lower):
            steps.append({
                "tool": "laravel_git_status",
                "args": {},
                "description": "Show git status of the active project",
            })
            continue

        # 8. Check server health
        if "server" in c_lower and ("check" in c_lower or "health" in c_lower):
            steps.append({
                "tool": "server_health_check",
                "args": {"server_name": "all"},
                "description": "Run health checks on all servers",
            })
            continue

        # 9. List reminders
        if "reminder" in c_lower:
            steps.append({
                "tool": "list_reminders",
                "args": {},
                "description": "Review pending reminders",
            })
            continue

        # 10. Cost summary
        if "cost" in c_lower or "spending" in c_lower or "summarize" in c_lower:
            steps.append({
                "tool": "get_cost_today",
                "args": {},
                "description": "Summarize today's activities and spending",
            })
            continue

        # 11. Generic fallback: shell command
        steps.append({
            "tool": "run_shell_command",
            "args": {"command": chunk},
            "description": f"Run command '{chunk}'",
        })

    return steps


def create_routine(
    name: str,
    steps_description: str,
    speak_fn: Callable[[str], None] | None = None,
    ask_user_fn: Callable[[str], bool] | None = None,
) -> str:
    """
    Create a new routine from voice or text with mandatory readback and confirmation.

    Invariant:
      The agent reads the steps back and saves it ONLY after the user confirms.
      Every step must map to a valid tool and go through the permission gate.
    """
    clean_name = name.strip()
    slug_name = clean_name.lower().replace(" ", "_")
    title_name = clean_name.title()

    # Reject any attempt to bypass or skip permission gates
    if any(bp in steps_description.lower() for bp in ["bypass", "skip permission", "skip gate", "no confirmation", "bypass gate"]):
        err = "Security Policy Violation: Routines can never contain steps that skip the permission gate."
        logger.error(f"[Routines Creator] {err}")
        raise PermissionDenied(err)

    # Parse steps
    steps = parse_steps_from_text(steps_description)
    if not steps:
        msg = f"I could not understand any actionable steps from: '{steps_description}'."
        if speak_fn:
            speak_fn(msg)
        return msg

    # Validate tool safety: all tools must exist in TOOL_REGISTRY and cannot bypass gates
    from jarvis.tools import TOOL_REGISTRY
    for step in steps:
        tool = step.get("tool")
        if tool not in TOOL_REGISTRY:
            err = f"Security Error: Tool `{tool}` is not in TOOL_REGISTRY and cannot be used in a routine."
            logger.error(f"[Routines Creator] {err}")
            raise PermissionDenied(err)
        # Check for any malicious bypass flags
        args = step.get("args", {})
        if any(k in args for k in ["skip_gate", "bypass_permission", "no_gate"]):
            err = f"Security Policy Violation: Routines can never contain steps that skip the permission gate."
            logger.error(f"[Routines Creator] {err}")
            raise PermissionDenied(err)

    # ── MANDATORY INVARIANT: Read steps back aloud & prompt confirmation ─────
    step_descriptions = [f"{i}. {s['description']}" for i, s in enumerate(steps, 1)]
    spoken_steps = ", ".join(f"Step {i}: {s['description']}" for i, s in enumerate(steps, 1))

    prompt_voice = (
        f"Create routine '{title_name}' with {len(steps)} steps: {spoken_steps}. "
        "Shall I save this routine?"
    )
    logger.warning(f"[Routines Gate] {prompt_voice}")

    if speak_fn:
        try:
            speak_fn(prompt_voice)
        except Exception:
            pass

    ask = ask_user_fn or _ask_user
    if not ask(prompt_voice):
        logger.warning(f"[Routines Gate] Routine creation for '{clean_name}' was cancelled by user.")
        cancel_msg = f"Routine creation for '{title_name}' was cancelled."
        if speak_fn:
            try:
                speak_fn(cancel_msg)
            except Exception:
                pass
        return f"❌ Routine creation for `{title_name}` was cancelled by user."

    # User approved -> save routine into config/routines.yaml
    routine_dict: dict[str, Any] = {
        "name": slug_name,
        "title": title_name,
        "triggers": [clean_name.lower(), slug_name, f"start {clean_name.lower()}", f"run {clean_name.lower()}"],
        "description": steps_description,
        "steps": steps,
    }
    save_routine(routine_dict)

    success_spoken = f"Routine '{title_name}' has been saved successfully."
    if speak_fn:
        try:
            speak_fn(success_spoken)
        except Exception:
            pass

    return (
        f"✅ **Routine Saved**: `{title_name}` (`{slug_name}`)\n"
        f"**Triggers**: `{', '.join(routine_dict['triggers'])}`\n"
        f"**Steps**:\n"
        + "\n".join(f"- {sd}" for sd in step_descriptions)
        + f"\n\n📢 *Voice Confirmation*: \"{success_spoken}\""
    )
