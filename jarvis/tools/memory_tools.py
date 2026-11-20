"""
jarvis/tools/memory_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tools for memory management:
  - remember_fact(text)
  - recall_facts(query)
  - forget_fact(query) — requires permission gate confirmation
  - set_project_context(name, path)
  - get_project_context()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from jarvis.memory import memory_manager
from jarvis.logger import logger


def remember_fact(text: str) -> str:
    """
    Store an important piece of information, user preference, server details,
    or project note in persistent long-term memory.
    """
    logger.info(f"remember_fact tool called: {text!r}")
    return memory_manager.long_term.remember(text)


def recall_facts(query: str) -> str:
    """
    Search persistent long-term memory for stored facts, preferences,
    project paths, or notes matching the query.
    """
    logger.info(f"recall_facts tool called: {query!r}")
    results = memory_manager.long_term.recall(query, limit=5)
    if not results:
        return f"No memories found matching '{query}'."
    formatted = "\n".join(f"• {r}" for r in results)
    return f"Found {len(results)} memory items:\n{formatted}"


def forget_fact(query: str) -> str:
    """
    Delete memories or facts matching the query from persistent memory.
    The permission gate intercepts this and requires spoken/typed user confirmation.
    """
    logger.info(f"forget_fact tool called: {query!r}")
    deleted_count = memory_manager.long_term.forget(query)
    if deleted_count == 0:
        return f"No memories matching '{query}' were found to delete."
    return f"Successfully deleted {deleted_count} fact(s) matching '{query}' from memory."


def set_project_context(name: str, path: str | None = None) -> str:
    """
    Set or switch the active project context in memory (project name, path, and detected type).
    """
    logger.info(f"set_project_context tool called: name={name!r}, path={path!r}")
    info = memory_manager.long_term.set_active_project(name, path)
    return (
        f"Active project switched to '{info['name']}' at {info['path']} "
        f"(detected framework: {info['project_type']})."
    )


def get_project_context() -> str:
    """
    Retrieve details about the current active project, its framework type, and recent commands.
    """
    info = memory_manager.long_term.get_active_project()
    if not info:
        return "No active project is currently set."
    recent = ", ".join(f"`{c}`" for c in info["last_commands"]) if info["last_commands"] else "none"
    return (
        f"Active Project: '{info['name']}'\n"
        f"Path: {info['path']}\n"
        f"Type: {info['project_type']}\n"
        f"Recent Commands: {recent}"
    )
