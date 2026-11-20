"""
jarvis/laravel/review.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Laravel Code Reviewer.

Analyzes current git diffs for:
  1. Bugs & logic flaws
  2. Security vulnerabilities (SQLi, IDOR, Mass Assignment, CSRF, auth leaks)
  3. Performance (N+1 queries, Eloquent efficiency)
  4. Laravel style & conventions (PSR-12, FormRequests, best practices)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from pathlib import Path

from jarvis.laravel.context import get_active_laravel_project, run_project_cmd
from jarvis.logger import logger


def laravel_code_review(
    base_branch: str | None = None,
    file_path: str | None = None,
    project_path: Path | None = None,
) -> str:
    """
    Perform a comprehensive code review of the current git diff in the active Laravel project.

    Parameters
    ----------
    base_branch : str | None
        Optional branch to compare against (e.g. 'main' or 'develop').
    file_path : str | None
        Optional file path to limit review to.
    """
    if not project_path:
        project_name, project_path = get_active_laravel_project()
    else:
        project_name = project_path.name

    logger.info(f"[Laravel Review] Reviewing code in '{project_name}' (base={base_branch}, file={file_path})")

    # Get diff
    if base_branch:
        cmd = ["git", "diff", f"{base_branch}...HEAD"]
    else:
        # Check unstaged diff first, then staged
        _, unstaged, _ = run_project_cmd(["git", "diff"], project_path=project_path)
        _, staged, _ = run_project_cmd(["git", "diff", "--cached"], project_path=project_path)
        diff_text = unstaged + "\n" + staged
        if not diff_text.strip():
            # Check last commit diff
            _, last_commit_diff, _ = run_project_cmd(["git", "diff", "HEAD~1..HEAD"], project_path=project_path)
            diff_text = last_commit_diff

    if base_branch:
        code, out, _ = run_project_cmd(cmd, project_path=project_path)
        diff_text = out

    if not diff_text.strip():
        return f"Working tree in `{project_name}` is clean. No diff available to review."

    # Truncate if massive
    diff_snippet = diff_text[:12000]

    from jarvis.brain import _get_client
    client = _get_client()
    prompt = (
        f"You are a Principal Laravel Architect conducting a rigorous code review.\n"
        f"Project: {project_name}\n\n"
        "Analyze the following git diff carefully across four specific pillars:\n"
        "1. 🐛 **Bugs & Logic Flaws**: Unhandled nulls, type errors, race conditions, missing DB transactions.\n"
        "2. 🛡️ **Security Vulnerabilities**: SQL injection, Mass Assignment ($request->all()), IDOR, missing policy checks, CSRF, sensitive data exposure.\n"
        "3. ⚡ **Performance & Eloquent**: N+1 queries, missing eager loading with(), heavy computations in loops.\n"
        "4. 🎨 **Laravel Conventions & Style**: PSR-12, FormRequest usage, Route Model Binding, naming standards.\n\n"
        "Format your output in clean Markdown with:\n"
        "• A short 2-sentence **Executive Voice Summary** (suitable to be spoken aloud).\n"
        "• Specific findings grouped by the four pillars above, referencing exact files and line numbers with proposed fixes.\n\n"
        f"```diff\n{diff_snippet}\n```"
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        return resp.choices[0].message.content or "No review generated."
    except Exception as exc:
        return f"Failed to perform code review: {exc}"
