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
from jarvis.tools.vision import take_screenshot, fix_screen_error
from jarvis.tools.computer import (
    click_at,
    click_element,
    type_text,
    press_hotkey,
    scroll_screen,
)
from jarvis.tools.files import (
    search_files,
    move_files,
    read_clipboard,
    write_clipboard,
)
from jarvis.tools.browser import (
    browser_open,
    browser_search,
    browser_fill_form,
)
from jarvis.tools.messaging_tools import send_message
from jarvis.tools.laravel_tools import (
    read_laravel_log,
    laravel_debug_and_fix,
    laravel_run_tests,
    laravel_write_test,
    laravel_git_status,
    laravel_git_diff,
    laravel_git_create_branch,
    laravel_git_commit,
    laravel_git_push,
    laravel_git_pr_description,
    laravel_git_reset_hard,
    laravel_git_delete_branch,
    laravel_run_migrations,
    laravel_backup_database,
    laravel_table_schema,
    laravel_scaffold,
    laravel_code_review,
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

    # ── take_screenshot ──────────────────────────────────────────────────────
    ToolDef(
        name="take_screenshot",
        fn=take_screenshot,
        description=(
            "Capture the screen (or active window) and send it to the vision model (gpt-4o) "
            "to describe what is on screen, read an error or text, or find a button or UI element. "
            "The screenshot is held in memory and never saved to disk unless explicitly asked."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What to look for, read, or describe from the screenshot.",
                },
                "target": {
                    "type": "string",
                    "enum": ["screen", "window"],
                    "description": "'screen' for the full desktop, or 'window' for the active window.",
                },
                "save_to_disk": {
                    "type": "boolean",
                    "description": "Set to true ONLY if the user explicitly requested saving the image to disk.",
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional file path where to save if save_to_disk is true.",
                },
            },
        },
    ),

    # ── fix_screen_error ─────────────────────────────────────────────────────
    ToolDef(
        name="fix_screen_error",
        fn=fix_screen_error,
        description=(
            "Analyze an error, exception, or traceback currently visible on the screen. "
            "Automatically captures the screen, extracts error messages and file paths/lines, "
            "inspects the local code files, and proposes a concrete fix. "
            "Use this whenever the user says 'fix this error' or refers to an error on screen."
        ),
        parameters={
            "type": "object",
            "properties": {
                "extra_context": {
                    "type": "string",
                    "description": "Optional user context or description of what they were trying to do.",
                },
            },
        },
    ),

    # ── click_at ─────────────────────────────────────────────────────────────
    ToolDef(
        name="click_at",
        fn=click_at,
        description=(
            "Click the mouse at specific (x, y) pixel coordinates on the screen. "
            "Clicking inside sensitive apps (password managers, banking, terminals running sudo) "
            "requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate in pixels (0 is left).",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate in pixels (0 is top).",
                },
                "clicks": {
                    "type": "integer",
                    "description": "Number of clicks (1 for single, 2 for double). Default 1.",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "Mouse button to click. Default 'left'.",
                },
            },
            "required": ["x", "y"],
        },
    ),

    # ── click_element ────────────────────────────────────────────────────────
    ToolDef(
        name="click_element",
        fn=click_element,
        description=(
            "Find a UI element by visual description using screen vision and click it. "
            "Example descriptions: 'the blue Submit button', 'the search bar', 'the terminal window'. "
            "Clicking inside sensitive apps requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Natural language description of the button, input, or element to click.",
                },
            },
            "required": ["description"],
        },
    ),

    # ── type_text ────────────────────────────────────────────────────────────
    ToolDef(
        name="type_text",
        fn=type_text,
        description=(
            "Type text into the currently active or focused desktop window or input element. "
            "Supports full Unicode, multi-line text, and pressing Enter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text string to type into the active window.",
                },
                "press_enter": {
                    "type": "boolean",
                    "description": "Whether to press Enter after typing the text (default false).",
                },
            },
            "required": ["text"],
        },
    ),

    # ── press_hotkey ─────────────────────────────────────────────────────────
    ToolDef(
        name="press_hotkey",
        fn=press_hotkey,
        description=(
            "Press a keyboard key or hotkey combination (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'super')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "keys": {
                    "type": "string",
                    "description": "Hotkey string such as 'ctrl+c', 'ctrl+shift+t', 'alt+tab', or 'escape'.",
                },
            },
            "required": ["keys"],
        },
    ),

    # ── scroll_screen ────────────────────────────────────────────────────────
    ToolDef(
        name="scroll_screen",
        fn=scroll_screen,
        description=(
            "Scroll the active screen, page, or window up or down."
        ),
        parameters={
            "type": "object",
            "properties": {
                "clicks": {
                    "type": "integer",
                    "description": "Number of scroll clicks/units (default 3).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["down", "up"],
                    "description": "Scroll direction: 'down' or 'up'. Default 'down'.",
                },
            },
        },
    ),

    # ── search_files ─────────────────────────────────────────────────────────
    ToolDef(
        name="search_files",
        fn=search_files,
        description=(
            "Search for files by name/glob pattern, or search inside file contents (like grep). "
            "Useful for finding source code, configuration files, notes, or error references."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Filename pattern (e.g. '*.py', 'docker*') or text string to grep for.",
                },
                "directory": {
                    "type": "string",
                    "description": "Optional directory to search in (defaults to active project or workspace).",
                },
                "search_content": {
                    "type": "boolean",
                    "description": "If true, search inside file contents (grep). If false, search filenames.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 20).",
                },
            },
            "required": ["query"],
        },
    ),

    # ── move_files ───────────────────────────────────────────────────────────
    ToolDef(
        name="move_files",
        fn=move_files,
        description=(
            "Move or organize files into a destination folder. "
            "Moving more than 3 files at once requires user confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of source file or directory paths to move.",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination directory path.",
                },
                "create_dest": {
                    "type": "boolean",
                    "description": "Whether to create destination folder if it does not exist (default true).",
                },
            },
            "required": ["sources", "destination"],
        },
    ),

    # ── read_clipboard ───────────────────────────────────────────────────────
    ToolDef(
        name="read_clipboard",
        fn=read_clipboard,
        description="Read the current text content from the system clipboard.",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),

    # ── write_clipboard ──────────────────────────────────────────────────────
    ToolDef(
        name="write_clipboard",
        fn=write_clipboard,
        description="Copy text to the system clipboard.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to copy to clipboard.",
                },
            },
            "required": ["text"],
        },
    ),

    # ── browser_open ─────────────────────────────────────────────────────────
    ToolDef(
        name="browser_open",
        fn=browser_open,
        description="Open a web URL in the system default web browser.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full website URL to open (must start with http:// or https://).",
                },
            },
            "required": ["url"],
        },
    ),

    # ── browser_search ───────────────────────────────────────────────────────
    ToolDef(
        name="browser_search",
        fn=browser_search,
        description="Search Google, DuckDuckGo, or Bing and open the results in the browser.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query or topic.",
                },
                "engine": {
                    "type": "string",
                    "enum": ["google", "duckduckgo", "bing"],
                    "description": "Search engine to use (default 'google').",
                },
            },
            "required": ["query"],
        },
    ),

    # ── browser_fill_form ────────────────────────────────────────────────────
    ToolDef(
        name="browser_fill_form",
        fn=browser_fill_form,
        description=(
            "Fill out simple form inputs in the active browser window. "
            "Submitting forms (submit=true) requires user spoken confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "description": "Key-value dictionary mapping field names or labels to their values.",
                },
                "submit": {
                    "type": "boolean",
                    "description": "Whether to submit the form after filling. Requires confirmation.",
                },
            },
            "required": ["fields"],
        },
    ),

    # ── send_message ─────────────────────────────────────────────────────────
    ToolDef(
        name="send_message",
        fn=send_message,
        description=(
            "Send a message to a person or group on Facebook Messenger, WhatsApp, or Telegram "
            "using the user's dedicated, already logged-in browser profile. "
            "The permission gate will always ask for user spoken confirmation before sending. "
            "If the user did not specify the platform, ask which one before calling."
        ),
        parameters={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["whatsapp", "messenger", "telegram"],
                    "description": "The messaging platform to use: 'whatsapp', 'messenger', or 'telegram'.",
                },
                "person_name": {
                    "type": "string",
                    "description": "The name of the contact or group to find and message.",
                },
                "text": {
                    "type": "string",
                    "description": "The exact message content to send.",
                },
            },
            "required": ["platform", "person_name", "text"],
        },
    ),

    # ── read_laravel_log ─────────────────────────────────────────────────────
    ToolDef(
        name="read_laravel_log",
        fn=read_laravel_log,
        description="Read the most recent error entries and stack traces from storage/logs/laravel.log in the active Laravel project.",
        parameters={
            "type": "object",
            "properties": {
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to inspect (default 60).",
                },
            },
        },
    ),

    # ── laravel_debug_and_fix ────────────────────────────────────────────────
    ToolDef(
        name="laravel_debug_and_fix",
        fn=laravel_debug_and_fix,
        description=(
            "Diagnose an error or failing test in the active Laravel project, locate the file and line, "
            "propose a patch using gpt-4o, apply it on a dedicated git branch, and re-run verification. "
            "Keeps the fix loop bounded to a small number of tries."
        ),
        parameters={
            "type": "object",
            "properties": {
                "test_filter": {
                    "type": "string",
                    "description": "Optional failing test filter (e.g. 'UserTest' or 'test_payment').",
                },
                "api_endpoint": {
                    "type": "string",
                    "description": "Optional failing API endpoint or route to verify.",
                },
                "max_attempts": {
                    "type": "integer",
                    "description": "Maximum number of fix attempts (default 3).",
                },
            },
        },
    ),

    # ── laravel_run_tests ────────────────────────────────────────────────────
    ToolDef(
        name="laravel_run_tests",
        fn=laravel_run_tests,
        description="Run PHPUnit or Pest tests in the active Laravel project and report summary results by voice.",
        parameters={
            "type": "object",
            "properties": {
                "test_filter": {
                    "type": "string",
                    "description": "Optional method or class filter (e.g. 'OrderTest' or 'can_create_order').",
                },
                "suite": {
                    "type": "string",
                    "description": "Optional test suite ('Unit' or 'Feature').",
                },
            },
        },
    ),

    # ── laravel_write_test ───────────────────────────────────────────────────
    ToolDef(
        name="laravel_write_test",
        fn=laravel_write_test,
        description="Write and immediately run a new Pest or PHPUnit test for code, a model, or controller in the active Laravel project.",
        parameters={
            "type": "object",
            "properties": {
                "target_name": {
                    "type": "string",
                    "description": "Name of the class or feature to test (e.g. 'UserController' or 'OrderService').",
                },
                "test_description": {
                    "type": "string",
                    "description": "Description of the test scenarios to implement.",
                },
                "test_framework": {
                    "type": "string",
                    "enum": ["pest", "phpunit"],
                    "description": "Testing framework to use: 'pest' (default) or 'phpunit'.",
                },
            },
            "required": ["target_name", "test_description"],
        },
    ),

    # ── laravel_git_status ───────────────────────────────────────────────────
    ToolDef(
        name="laravel_git_status",
        fn=laravel_git_status,
        description="Get current git branch and working tree status for the active Laravel project.",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),

    # ── laravel_git_diff ─────────────────────────────────────────────────────
    ToolDef(
        name="laravel_git_diff",
        fn=laravel_git_diff,
        description="Show git diff summary for changes in the active Laravel project.",
        parameters={
            "type": "object",
            "properties": {
                "cached": {
                    "type": "boolean",
                    "description": "Whether to view staged changes (--cached).",
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional specific file path to diff.",
                },
            },
        },
    ),

    # ── laravel_git_create_branch ────────────────────────────────────────────
    ToolDef(
        name="laravel_git_create_branch",
        fn=laravel_git_create_branch,
        description="Create and switch to a new git branch in the active Laravel project.",
        parameters={
            "type": "object",
            "properties": {
                "branch_name": {
                    "type": "string",
                    "description": "Name of the branch to create (e.g. 'feature/checkout-flow').",
                },
                "checkout": {
                    "type": "boolean",
                    "description": "Whether to switch to the new branch immediately (default true).",
                },
            },
            "required": ["branch_name"],
        },
    ),

    # ── laravel_git_commit ───────────────────────────────────────────────────
    ToolDef(
        name="laravel_git_commit",
        fn=laravel_git_commit,
        description=(
            "Commit changes in the active Laravel project. "
            "If message is omitted, automatically generates a clean conventional commit message from the diff."
        ),
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Commit message. If omitted, will be auto-generated from git diff.",
                },
                "auto_generate": {
                    "type": "boolean",
                    "description": "Whether to auto-generate message if empty (default true).",
                },
            },
        },
    ),

    # ── laravel_git_push ─────────────────────────────────────────────────────
    ToolDef(
        name="laravel_git_push",
        fn=laravel_git_push,
        description="Push commits to git remote. Force push requires user spoken confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "remote": {
                    "type": "string",
                    "description": "Remote name (default 'origin').",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to push (defaults to current branch).",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force push flag. REQUIRES USER CONFIRMATION.",
                },
            },
        },
    ),

    # ── laravel_git_pr_description ───────────────────────────────────────────
    ToolDef(
        name="laravel_git_pr_description",
        fn=laravel_git_pr_description,
        description="Generate a complete Pull Request title, description, and testing checklist in markdown from git log and diff.",
        parameters={
            "type": "object",
            "properties": {
                "base_branch": {
                    "type": "string",
                    "description": "Target base branch to compare against (default 'main').",
                },
            },
        },
    ),

    # ── laravel_git_reset_hard ───────────────────────────────────────────────
    ToolDef(
        name="laravel_git_reset_hard",
        fn=laravel_git_reset_hard,
        description="Hard reset the git working tree to target commit/HEAD. Discards uncommitted work. Requires user spoken confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Commit or ref to reset to (default 'HEAD').",
                },
            },
        },
    ),

    # ── laravel_git_delete_branch ────────────────────────────────────────────
    ToolDef(
        name="laravel_git_delete_branch",
        fn=laravel_git_delete_branch,
        description="Delete a git branch in the active Laravel project. Requires user spoken confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "branch_name": {
                    "type": "string",
                    "description": "Name of the branch to delete.",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force delete unmerged branch (-D).",
                },
            },
            "required": ["branch_name"],
        },
    ),

    # ── laravel_run_migrations ───────────────────────────────────────────────
    ToolDef(
        name="laravel_run_migrations",
        fn=laravel_run_migrations,
        description=(
            "Run database migrations in the active Laravel project. "
            "Destructive actions ('fresh', 'reset', 'rollback') automatically create a database backup first "
            "and require user spoken confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["migrate", "rollback", "fresh", "reset", "status"],
                    "description": "Migration action to execute (default 'migrate').",
                },
                "step": {
                    "type": "integer",
                    "description": "Number of migration batches to rollback (for rollback action).",
                },
            },
        },
    ),

    # ── laravel_backup_database ──────────────────────────────────────────────
    ToolDef(
        name="laravel_backup_database",
        fn=laravel_backup_database,
        description="Create an immediate backup of the Laravel project database in storage/backups/.",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),

    # ── laravel_table_schema ─────────────────────────────────────────────────
    ToolDef(
        name="laravel_table_schema",
        fn=laravel_table_schema,
        description="Inspect and display the column names, data types, nullability, and indexes of a database table.",
        parameters={
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Name of the table to inspect (e.g. 'users', 'orders').",
                },
            },
            "required": ["table_name"],
        },
    ),

    # ── laravel_scaffold ─────────────────────────────────────────────────────
    ToolDef(
        name="laravel_scaffold",
        fn=laravel_scaffold,
        description="Scaffold controllers, models, migrations, factories, requests, resources, or routes using artisan when you describe what you want.",
        parameters={
            "type": "object",
            "properties": {
                "component_type": {
                    "type": "string",
                    "enum": ["controller", "model", "migration", "route", "factory", "seeder", "request", "resource"],
                    "description": "Type of component to scaffold.",
                },
                "name": {
                    "type": "string",
                    "description": "Name of the component or description for route.",
                },
                "options": {
                    "type": "string",
                    "description": "Extra artisan flags (e.g. '--resource', '-mfc', '--api').",
                },
                "route_definition": {
                    "type": "string",
                    "description": "Optional explicit PHP route definition line for route scaffolding.",
                },
            },
            "required": ["component_type", "name"],
        },
    ),

    # ── laravel_code_review ──────────────────────────────────────────────────
    ToolDef(
        name="laravel_code_review",
        fn=laravel_code_review,
        description="Perform a comprehensive code review of the current git diff in the active Laravel project, checking for bugs, security vulnerabilities (SQLi, IDOR, Mass Assignment, CSRF), performance (N+1 queries), and style.",
        parameters={
            "type": "object",
            "properties": {
                "base_branch": {
                    "type": "string",
                    "description": "Optional base branch to compare diff against (default compares working tree / staged changes).",
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional specific file to limit review to.",
                },
            },
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
