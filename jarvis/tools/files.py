"""
jarvis/tools/files.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
File & Clipboard Tools.

Provides:
  • search_files: search for files by name/glob, or search inside file contents (grep).
  • move_files: move and organize files into folders.
  • read_clipboard: get the current text on the system clipboard.
  • write_clipboard: copy text onto the system clipboard.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any

import pyperclip

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

_IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "venv",
    ".venv",
    "node_modules",
    ".cache",
    ".npm",
    "dist",
    "build",
}

_BINARY_EXTS = {
    ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
    ".tar", ".gz", ".xz", ".bz2", ".7z", ".mp3", ".wav", ".mp4",
    ".mkv", ".webm", ".bin", ".iso", ".exe", ".so", ".o", ".dll"
}


def search_files(
    query: str,
    directory: str | None = None,
    search_content: bool = False,
    max_results: int = 20,
) -> str:
    """
    Search for files by filename pattern or search inside file contents.

    Parameters
    ----------
    query : str
        The filename pattern (e.g. '*.py', 'config*') or text string to search for.
    directory : str | None
        Directory to start searching from (defaults to active project path or workspace).
    search_content : bool
        If True, search inside text files for query; if False, search filenames.
    max_results : int
        Maximum number of matching lines/files to return.
    """
    # Determine base directory
    if directory:
        base_path = Path(directory).expanduser().resolve()
    else:
        # Check active project from memory
        try:
            from jarvis.memory import memory_manager
            proj = memory_manager.get_active_project()
            if proj and proj.get("path") and Path(proj["path"]).is_dir():
                base_path = Path(proj["path"]).resolve()
            else:
                base_path = PROJECT_ROOT
        except Exception:
            base_path = PROJECT_ROOT

    if not base_path.exists():
        return f"Directory does not exist: {base_path}"

    logger.info(f"search_files: query={query!r} dir={base_path} content={search_content}")

    matches: list[str] = []
    q_lower = query.lower()

    if not search_content:
        # Search by file / folder name
        for root, dirs, files in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS and not d.startswith(".")]
            for name in files + dirs:
                if fnmatch.fnmatch(name.lower(), q_lower) or q_lower in name.lower():
                    full_p = Path(root) / name
                    try:
                        rel = full_p.relative_to(base_path)
                    except ValueError:
                        rel = full_p
                    size_str = ""
                    if full_p.is_file():
                        try:
                            size_str = f" ({full_p.stat().st_size:,} bytes)"
                        except Exception:
                            pass
                    matches.append(f"{rel}{size_str}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        if not matches:
            return f"No files matching '{query}' found in {base_path}."
        return f"Found {len(matches)} match(es) in {base_path}:\n" + "\n".join(f"  • {m}" for m in matches)

    else:
        # Search file contents (grep)
        for root, dirs, files in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS and not d.startswith(".")]
            for name in files:
                p = Path(root) / name
                if p.suffix.lower() in _BINARY_EXTS:
                    continue
                try:
                    if p.stat().st_size > 2 * 1024 * 1024:  # skip files > 2MB
                        continue
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    lines = text.splitlines()
                    for idx, line in enumerate(lines, 1):
                        if q_lower in line.lower():
                            try:
                                rel = p.relative_to(base_path)
                            except ValueError:
                                rel = p
                            snippet = line.strip()
                            if len(snippet) > 120:
                                snippet = snippet[:117] + "..."
                            matches.append(f"{rel}:{idx}: {snippet}")
                            if len(matches) >= max_results:
                                break
                except Exception:
                    continue
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        if not matches:
            return f"No occurrences of '{query}' found in {base_path}."
        return f"Found {len(matches)} occurrence(s) in {base_path}:\n" + "\n".join(f"  {m}" for m in matches)


def move_files(
    sources: list[str],
    destination: str,
    create_dest: bool = True,
) -> str:
    """
    Move and organize one or more files to a destination directory.

    Parameters
    ----------
    sources : list[str]
        List of file or directory paths to move.
    destination : str
        Target destination directory.
    create_dest : bool
        If True, create destination directory if it doesn't already exist.
    """
    logger.info(f"move_files: {len(sources)} source(s) -> {destination}")

    dest_path = Path(destination).expanduser().resolve()
    if not dest_path.exists():
        if create_dest:
            try:
                dest_path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                return f"Failed to create destination directory `{destination}`: {exc}"
        else:
            return f"Destination directory `{destination}` does not exist."

    moved: list[str] = []
    errors: list[str] = []

    for src in sources:
        src_path = Path(src).expanduser().resolve()
        if not src_path.exists():
            errors.append(f"Source not found: {src}")
            continue

        try:
            target = dest_path / src_path.name
            shutil.move(str(src_path), str(target))
            moved.append(f"{src_path.name} -> {target}")
        except Exception as exc:
            errors.append(f"Failed to move {src_path.name}: {exc}")

    result = []
    if moved:
        result.append(f"Successfully moved {len(moved)} item(s) to `{dest_path}`:\n" + "\n".join(f"  • {m}" for m in moved))
    if errors:
        result.append("Errors encountered:\n" + "\n".join(f"  ⚠️ {e}" for e in errors))

    return "\n\n".join(result) if result else "No files were moved."


# ── Clipboard Tools ──────────────────────────────────────────────────────────

def read_clipboard() -> str:
    """Read the current text from the system clipboard."""
    try:
        content = pyperclip.paste()
        if not content:
            return "(clipboard is empty)"
        logger.info(f"read_clipboard: read {len(content)} chars")
        return content
    except Exception as exc:
        return f"Failed to read clipboard: {exc}"


def write_clipboard(text: str) -> str:
    """Copy text to the system clipboard."""
    try:
        pyperclip.copy(text)
        logger.info(f"write_clipboard: copied {len(text)} chars")
        return f"Copied {len(text)} characters to the clipboard."
    except Exception as exc:
        return f"Failed to write to clipboard: {exc}"
