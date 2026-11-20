"""
jarvis/tools/registry.py
Central registry that maps tool names to their implementation functions and
OpenAI function-call schemas.

Adding a new tool:
  1. Implement it in a submodule of jarvis/tools/.
  2. Import the function here.
  3. Add a ToolDef entry to _TOOL_DEFS.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any

# ── Import tool implementations ───────────────────────────────────────────────
from jarvis.tools.system import run_shell_command, open_app, open_url, play_youtube
from jarvis.tools.memory_tools import (
    remember_fact,
    recall_facts,
    forget_fact,
    set_project_context,
    get_project_context,
)


@dataclass
class ToolDef:
    name: str
    fn: Callable[..., str]
    description: str
    parameters: dict = field(default_factory=dict)


# ── Tool definitions ─────────────────────────────────────────────────────────

_TOOL_DEFS: list[ToolDef] = [
    # ── run_shell_command ────────────────────────────────────────────────────
    ToolDef(
        name="run_shell_command",
        fn=run_shell_command,
        description=(
            "Run an arbitrary shell command on the user's Linux machine "
            "and return stdout + stderr. The permission gate will intercept "
            "dangerous commands and ask the user before running them."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The full shell command to execute.",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory (absolute path).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30).",
                },
            },
            "required": ["command"],
        },
    ),

    # ── open_app ─────────────────────────────────────────────────────────────
    ToolDef(
        name="open_app",
        fn=open_app,
        description=(
            "Launch a desktop application by its friendly name, e.g. 'vscode', "
            "'browser', 'terminal', 'nautilus'. Returns immediately after spawning."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": (
                        "Friendly application name as configured (e.g. 'vscode', "
                        "'chrome', 'terminal') or a raw executable name."
                    ),
                },
                "file_or_args": {
                    "type": "string",
                    "description": "Optional file path or extra argument to pass to the app.",
                },
            },
            "required": ["app_name"],
        },
    ),

    # ── open_url ─────────────────────────────────────────────────────────────
    ToolDef(
        name="open_url",
        fn=open_url,
        description=(
            "Open a specific URL in the default web browser. "
            "Use this for general websites, documentation, or direct URLs. "
            "Do NOT use this to play, listen to, or watch songs or videos; use play_youtube instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full URL to open (must start with http:// or https://).",
                },
            },
            "required": ["url"],
        },
    ),

    # ── play_youtube ─────────────────────────────────────────────────────────
    ToolDef(
        name="play_youtube",
        fn=play_youtube,
        description=(
            "Search for and play a video, song, or music on YouTube in the browser. "
            "Use this tool whenever the user says 'play', 'listen to', or 'watch' something, "
            "such as music, songs, artists, or videos. "
            "If the user says only 'play music' with no specifics, search for 'popular songs' instead of refusing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The search term or song/video title. If the user only asked to 'play music' "
                        "with no specifics, use 'popular songs'."
                    ),
                },
            },
            "required": ["query"],
        },
    ),

    # ── remember_fact ────────────────────────────────────────────────────────
    ToolDef(
        name="remember_fact",
        fn=remember_fact,
        description=(
            "Save an important fact, user preference, server address, project detail, "
            "or note to persistent long-term memory so you remember it in future sessions. "
            "Use this when the user says 'remember this', 'remember that...', or shares personal preferences."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The exact fact or note to remember (no credentials or passwords).",
                },
            },
            "required": ["text"],
        },
    ),

    # ── recall_facts ─────────────────────────────────────────────────────────
    ToolDef(
        name="recall_facts",
        fn=recall_facts,
        description=(
            "Search persistent long-term memory for stored facts, preferences, server details, "
            "or project notes matching a topic or keyword."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or search term to look up in memory.",
                },
            },
            "required": ["query"],
        },
    ),

    # ── forget_fact ──────────────────────────────────────────────────────────
    ToolDef(
        name="forget_fact",
        fn=forget_fact,
        description=(
            "Delete stored memories or facts matching a keyword. "
            "Requires user confirmation through the permission gate before taking effect."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords identifying the memory items to delete.",
                },
            },
            "required": ["query"],
        },
    ),

    # ── set_project_context ──────────────────────────────────────────────────
    ToolDef(
        name="set_project_context",
        fn=set_project_context,
        description=(
            "Set or switch the active project context in memory, including project name, path, "
            "and detected project framework (e.g. Laravel, Flutter, Python, Node.js)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The project identifier or name.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional absolute filesystem path to the project root.",
                },
            },
            "required": ["name"],
        },
    ),

    # ── get_project_context ──────────────────────────────────────────────────
    ToolDef(
        name="get_project_context",
        fn=get_project_context,
        description=(
            "Retrieve details about the current active project, its framework type, "
            "and recent commands run there."
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
]


# ── Public accessors ─────────────────────────────────────────────────────────

# name → implementation function
TOOL_REGISTRY: dict[str, Callable[..., str]] = {t.name: t.fn for t in _TOOL_DEFS}


def get_tool_schemas() -> list[dict]:
    """Return OpenAI-compatible function-call schema list."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _TOOL_DEFS
    ]
