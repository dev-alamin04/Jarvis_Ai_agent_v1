"""
jarvis/laravel/debug.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Laravel Debugging & Automated Fix Loop.

Features:
  • Reads `storage/logs/laravel.log` and parses stack traces to locate exact
    application files and line numbers.
  • Isolates fixes on a git branch (e.g. `fix/jarvis-...`).
  • Proposes and applies targeted patches using gpt-4o.
  • Re-runs failing tests/requests to verify fixes.
  • Enforces bounded iterations (default max 3 attempts) to prevent runaway loops.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from jarvis.laravel.context import get_active_laravel_project, run_artisan, run_project_cmd
from jarvis.logger import logger


def _get_log_files(project_path: Path) -> list[Path]:
    """Find available Laravel log files, most recent first."""
    log_dir = project_path / "storage" / "logs"
    if not log_dir.is_dir():
        return []

    logs = list(log_dir.glob("laravel*.log"))
    logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return logs


def read_laravel_log(lines: int = 60, project_path: Path | None = None) -> str:
    """
    Read the most recent error entries and stack traces from `storage/logs/laravel.log`.

    Parameters
    ----------
    lines : int
        Maximum number of recent log lines to inspect.
    project_path : Path | None
        Optional project root; defaults to active project.
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    log_files = _get_log_files(project_path)
    if not log_files:
        return f"No log files found in {project_path / 'storage' / 'logs'}."

    target_log = log_files[0]
    try:
        content = target_log.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Failed to read {target_log.name}: {exc}"

    if not content.strip():
        return f"Log file `{target_log.name}` is empty."

    raw_lines = content.splitlines()
    recent = raw_lines[-lines:] if len(raw_lines) > lines else raw_lines

    # Parse and structure the log summary
    recent_text = "\n".join(recent)
    parsed = parse_stack_trace(recent_text, project_path)

    header = f"=== Latest Laravel Log: {target_log.name} (last {len(recent)} lines) ===\n"
    if parsed.get("message") or parsed.get("exception"):
        raw_msg = parsed.get("raw_error") or parsed.get("message")
        summary = (
            f"Error: {parsed.get('exception', 'Laravel Error')}\n"
            f"Message: {raw_msg}\n"
            f"Location: {parsed.get('file', 'unknown')}:{parsed.get('line', '?')}\n\n"
        )
        return header + summary + "Recent frames:\n" + "\n".join(f"  • {f}" for f in parsed.get("app_frames", [])[:5])

    return header + recent_text[-1200:]


def parse_stack_trace(log_chunk: str, project_path: Path | None = None) -> dict[str, Any]:
    """
    Parse a Laravel log chunk or test error output to extract:
      - Exception name
      - Error message
      - Offending file & line (prioritizing app/ code over vendor/)
      - App-specific stack frames
    """
    result: dict[str, Any] = {
        "exception": None,
        "message": None,
        "raw_error": None,
        "file": None,
        "line": None,
        "app_frames": [],
    }

    # 1. Match [object] (BadMethodCallException(code: 0): Method does not exist at ...
    obj_match = re.search(r"\[object\]\s*\(([A-Za-z0-9_\\]+(?:Exception|Error))\([^)]*\):\s*(.*?)(?=\s+at\s+[\/\w\.-]+\.php|\Z)", log_chunk)
    if obj_match:
        result["exception"] = obj_match.group(1).split("\\")[-1]
        result["message"] = obj_match.group(2).strip()

    # 2. Match main local.ERROR line or formatted Message: header
    err_match = re.search(r"(?:Message:\s*|\w+\.ERROR:\s*)(.*?)(?=\s*\{|\s*\[stacktrace\]|\n#\d|\nLocation:|\Z)", log_chunk, re.DOTALL)
    if err_match:
        full_err_msg = err_match.group(1).strip()
        result["raw_error"] = full_err_msg
        if not result["message"]:
            result["message"] = full_err_msg

        if not result["exception"]:
            cls_match = re.match(r"^([A-Za-z0-9_\\]+(?:Exception|Error))(?::\s*(.*))?$", full_err_msg)
            if cls_match:
                result["exception"] = cls_match.group(1).split("\\")[-1]
                if cls_match.group(2):
                    result["message"] = cls_match.group(2).strip()
            else:
                result["exception"] = "Laravel Error"

    # Find file and line references
    # Pattern: in /path/to/project/app/Http/...php on line 123
    # or at /path/...php:123
    frame_pattern = re.compile(r"([/\w\.-]+\.php)(?::| on line\s+)(\d+)")
    matches = frame_pattern.findall(log_chunk)

    for f_path, l_num in reversed(matches):
        p = Path(f_path)
        frame_str = f"{f_path}:{l_num}"
        # Skip vendor boilerplate to find the actual application code
        if "vendor/" not in f_path:
            if not result["file"]:
                result["file"] = f_path
                result["line"] = int(l_num)
            if frame_str not in result["app_frames"]:
                result["app_frames"].append(frame_str)

    # Fallback to vendor frame if no app frame was found
    if not result["file"] and matches:
        last_f, last_l = matches[-1]
        result["file"] = last_f
        result["line"] = int(last_l)

    return result


def laravel_debug_and_fix(
    test_filter: str | None = None,
    api_endpoint: str | None = None,
    max_attempts: int = 3,
    project_path: Path | None = None,
) -> str:
    """
    Automated debug and fix loop:
      1. Inspects storage/logs/laravel.log or re-runs failing test/request.
      2. Finds offending file and line.
      3. Creates a dedicated git branch.
      4. Generates and applies patch using gpt-4o.
      5. Re-runs verification up to max_attempts.
    """
    if not project_path:
        project_name, project_path = get_active_laravel_project()
    else:
        project_name = project_path.name

    logger.info(f"[Laravel Debug] Starting debug & fix loop for '{project_name}' (max_attempts={max_attempts})")

    # 1. Create a dedicated fix branch
    timestamp = int(time.time())
    branch_name = f"fix/jarvis-{timestamp}"
    run_project_cmd(["git", "checkout", "-b", branch_name], project_path=project_path)

    attempts_log: list[str] = []

    for attempt in range(1, max_attempts + 1):
        logger.info(f"[Laravel Debug] Attempt {attempt}/{max_attempts}")

        # Gather failure information
        error_context = ""
        if test_filter:
            code, out, err = run_artisan(f"test --filter {test_filter}", project_path=project_path)
            if code == 0:
                return (
                    f"Success on branch `{branch_name}`! "
                    f"Test filter `{test_filter}` is now passing cleanly.\n\n"
                    + "\n".join(attempts_log)
                )
            error_context = out + "\n" + err
        else:
            log_out = read_laravel_log(lines=80, project_path=project_path)
            error_context = log_out

        parsed = parse_stack_trace(error_context, project_path)
        target_file = parsed.get("file")
        line_num = parsed.get("line")

        if not target_file or not line_num:
            return (
                f"Could not identify a specific local source file from the error stack trace.\n"
                f"Recent error context:\n{error_context[:800]}"
            )

        target_path = Path(target_file).expanduser().resolve()
        if not target_path.exists():
            # Try finding by relative path inside project
            rel_cand = project_path / target_file.lstrip("/")
            if rel_cand.exists():
                target_path = rel_cand
            else:
                return f"Offending file `{target_file}` could not be located on disk."

        # Safety invariant: Never edit .env files or secrets
        if ".env" in target_path.name or "secret" in target_path.name.lower():
            return "Access to .env files and secrets is blocked for security reasons."

        # Read surrounding code
        try:
            lines = target_path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            return f"Failed to read source file `{target_path}`: {exc}"

        total_lines = len(lines)
        start = max(0, line_num - 20)
        end = min(total_lines, line_num + 20)
        code_snippet = "\n".join(f"{i+1:4d} | {lines[i]}" for i in range(start, end))

        # Ask gpt-4o for a targeted patch
        from jarvis.brain import _get_client
        client = _get_client()
        prompt = (
            f"You are an expert Laravel developer fixing a bug.\n\n"
            f"Project: {project_name}\n"
            f"File: {target_path} (Lines {start+1} to {end})\n"
            f"Failing Line: {line_num}\n"
            f"Error details:\n{error_context[-1500:]}\n\n"
            f"Surrounding code:\n```php\n{code_snippet}\n```\n\n"
            "Provide the fix as a JSON object with this exact structure:\n"
            "{\n"
            '  "diagnosis": "Short explanation of the bug",\n'
            '  "original_snippet": "Exact contiguous lines of code from the file that must be replaced",\n'
            '  "replacement_snippet": "Corrected replacement lines of code",\n'
            '  "commit_message": "Conventional git commit message (e.g. fix(controller): handle null user)"\n'
            "}\n"
            "Ensure original_snippet matches the file text exactly. Return ONLY valid JSON."
        )

        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            raw_reply = resp.choices[0].message.content or ""
            clean_json = re.sub(r"^```(?:json)?\s*", "", raw_reply.strip(), flags=re.I)
            clean_json = re.sub(r"\s*```$", "", clean_json)
            patch_data = json.loads(clean_json)
        except Exception as exc:
            logger.error(f"[Laravel Debug] Patch generation error: {exc}")
            attempts_log.append(f"Attempt {attempt}: Failed to formulate patch via model: {exc}")
            continue

        orig = patch_data.get("original_snippet", "").strip()
        repl = patch_data.get("replacement_snippet", "").strip()
        commit_msg = patch_data.get("commit_message", f"fix: resolve error on line {line_num}")
        diagnosis = patch_data.get("diagnosis", "")

        file_text = target_path.read_text(encoding="utf-8")
        if orig not in file_text:
            # Fallback: line replacement
            logger.warning(f"[Laravel Debug] original_snippet not found verbatim. Attempting line replace.")
            lines[line_num - 1] = repl
            target_path.write_text("\n".join(lines), encoding="utf-8")
        else:
            new_file_text = file_text.replace(orig, repl, 1)
            target_path.write_text(new_file_text, encoding="utf-8")

        # Syntax check via php -l
        syn_code, _, syn_err = run_project_cmd(f"php -l {target_path}", project_path=project_path)
        if syn_code != 0:
            attempts_log.append(f"Attempt {attempt}: Applied patch had PHP syntax error: {syn_err}. Reverting.")
            target_path.write_text(file_text, encoding="utf-8")
            continue

        # Commit fix to branch
        run_project_cmd(f"git add {target_path}", project_path=project_path)
        run_project_cmd(["git", "commit", "-m", commit_msg], project_path=project_path)

        attempts_log.append(
            f"Attempt {attempt}: Patched `{target_path.name}:{line_num}` — {diagnosis}"
        )

        # Verification step
        if test_filter:
            v_code, v_out, v_err = run_artisan(f"test --filter {test_filter}", project_path=project_path)
            if v_code == 0:
                return (
                    f"Fixed on branch `{branch_name}`!\n"
                    f"Target: `{target_path.name}:{line_num}`\n"
                    f"Diagnosis: {diagnosis}\n"
                    f"Verification: Test filter `{test_filter}` passed successfully!\n\n"
                    + "\n".join(attempts_log)
                )
        else:
            # If no test filter, run test suite to see if tests pass
            v_code, v_out, _ = run_artisan("test", project_path=project_path, timeout=30)
            if v_code == 0:
                return (
                    f"Fixed on branch `{branch_name}`!\n"
                    f"Target: `{target_path.name}:{line_num}`\n"
                    f"Diagnosis: {diagnosis}\n"
                    f"Verification: All tests passing.\n\n"
                    + "\n".join(attempts_log)
                )

    return (
        f"Reached maximum attempts ({max_attempts}) on branch `{branch_name}`.\n"
        f"Summary of attempted fixes:\n" + "\n".join(attempts_log)
    )
