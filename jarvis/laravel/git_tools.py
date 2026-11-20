"""
jarvis/laravel/git_tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Git Operations for Laravel Projects.

Provides:
  • Status & diff summary.
  • Branch creation & automatic commit message generation from diffs.
  • Push & Pull Request description generator.
  • Guarded actions (force push, hard reset, branch deletion) requiring spoken confirmation.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from pathlib import Path

from jarvis.laravel.context import get_active_laravel_project, run_project_cmd
from jarvis.logger import logger


def laravel_git_status(project_path: Path | None = None) -> str:
    """Get the current working tree git status for the active Laravel project."""
    if not project_path:
        _, project_path = get_active_laravel_project()

    code, out, err = run_project_cmd(["git", "status", "--short", "--branch"], project_path=project_path)
    if code != 0:
        return f"Git error: {err or out}"

    branch_match = re.search(r"^##\s+(\S+)", out)
    branch = branch_match.group(1) if branch_match else "unknown"
    lines = [l for l in out.splitlines() if not l.startswith("##")]

    if not lines:
        return f"Branch: `{branch}` — Working tree clean, no uncommitted changes."

    return (
        f"Branch: `{branch}` ({len(lines)} modified/untracked files)\n"
        f"```\n{out}\n```"
    )


def laravel_git_diff(
    cached: bool = False,
    file_path: str | None = None,
    project_path: Path | None = None,
) -> str:
    """Show git diff summary for uncommitted changes."""
    if not project_path:
        _, project_path = get_active_laravel_project()

    cmd = ["git", "diff"]
    if cached:
        cmd.append("--cached")
    if file_path:
        cmd.append(file_path)

    code, out, err = run_project_cmd(cmd, project_path=project_path)
    if code != 0:
        return f"Git error: {err or out}"

    if not out.strip():
        return "No git diff changes detected."

    # Return diff stat + diff snippet
    _, stat_out, _ = run_project_cmd(cmd + ["--stat"], project_path=project_path)
    snippet = out[:2500]
    return f"**Summary**:\n```\n{stat_out}\n```\n\n**Diff**:\n```diff\n{snippet}\n```"


def laravel_git_create_branch(
    branch_name: str,
    checkout: bool = True,
    project_path: Path | None = None,
) -> str:
    """Create a new git branch in the Laravel project."""
    if not project_path:
        _, project_path = get_active_laravel_project()

    clean_name = branch_name.strip().replace(" ", "-")
    cmd = ["git", "checkout", "-b", clean_name] if checkout else ["git", "branch", clean_name]
    code, out, err = run_project_cmd(cmd, project_path=project_path)

    if code == 0:
        return f"Successfully created and switched to branch `{clean_name}`."
    return f"Failed to create branch `{clean_name}`: {err or out}"


def laravel_git_commit(
    message: str | None = None,
    auto_generate: bool = True,
    project_path: Path | None = None,
) -> str:
    """
    Commit changes to git. If message is not provided, writes an intelligent
    conventional commit message based on the actual diff.
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    # Stage all changes
    run_project_cmd(["git", "add", "-A"], project_path=project_path)

    if not message or not message.strip():
        # Auto-generate commit message from diff
        _, diff_out, _ = run_project_cmd(["git", "diff", "--cached"], project_path=project_path)
        if not diff_out.strip():
            return "Nothing to commit, working tree clean."

        from jarvis.brain import _get_client
        client = _get_client()
        prompt = (
            "Analyze this git diff and write a concise, professional conventional commit message "
            "(e.g. 'feat(orders): add invoice pdf generation' or 'fix(auth): prevent session expiration loop').\n"
            "Return ONLY the single line commit message (under 72 chars):\n\n"
            f"```diff\n{diff_out[:2000]}\n```"
        )
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
            )
            message = (resp.choices[0].message.content or "").strip().strip('"\'')
        except Exception:
            message = "chore: update application code"

    code, out, err = run_project_cmd(["git", "commit", "-m", message], project_path=project_path)
    if code == 0:
        return f"Committed: `{message}`\n```\n{out}\n```"
    return f"Commit failed: {err or out}"


def laravel_git_push(
    remote: str = "origin",
    branch: str | None = None,
    force: bool = False,
    project_path: Path | None = None,
) -> str:
    """
    Push commits to remote.
    NOTE: Force pushing requires explicit user confirmation via the Permission Gate.
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    # Get current branch if not specified
    if not branch:
        _, out, _ = run_project_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], project_path=project_path)
        branch = out.strip() or "main"

    cmd = ["git", "push", remote, branch]
    if force:
        cmd.append("--force")

    code, out, err = run_project_cmd(cmd, project_path=project_path, timeout=60)
    if code == 0:
        return f"Successfully pushed branch `{branch}` to `{remote}`."
    return f"Failed to push: {err or out}"


def laravel_git_pr_description(
    base_branch: str = "main",
    project_path: Path | None = None,
) -> str:
    """Generate a clean Pull Request title and description in markdown from branch diff and log."""
    if not project_path:
        _, project_path = get_active_laravel_project()

    _, log_out, _ = run_project_cmd(["git", "log", f"{base_branch}..HEAD", "--oneline"], project_path=project_path)
    _, stat_out, _ = run_project_cmd(["git", "diff", f"{base_branch}...HEAD", "--stat"], project_path=project_path)

    client = _get_client()
    prompt = (
        f"You are a tech lead writing a GitHub Pull Request description against `{base_branch}`.\n\n"
        f"Commits on this branch:\n{log_out}\n\n"
        f"Diff stats:\n{stat_out}\n\n"
        "Generate a structured PR description with:\n"
        "1. PR Title (concise, clear)\n"
        "2. Summary of changes\n"
        "3. Motivation / Context\n"
        "4. How to test (verification steps)"
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
        )
        return resp.choices[0].message.content or "Failed to generate PR description."
    except Exception as exc:
        return f"Error generating PR description: {exc}"


def laravel_git_reset_hard(target: str = "HEAD", project_path: Path | None = None) -> str:
    """
    Hard reset git working tree to target commit/HEAD.
    Requires spoken confirmation via Permission Gate!
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    code, out, err = run_project_cmd(["git", "reset", "--hard", target], project_path=project_path)
    if code == 0:
        return f"Hard reset to `{target}` complete: {out}"
    return f"Hard reset failed: {err or out}"


def laravel_git_delete_branch(branch_name: str, force: bool = False, project_path: Path | None = None) -> str:
    """
    Delete a git branch.
    Requires spoken confirmation via Permission Gate!
    """
    if not project_path:
        _, project_path = get_active_laravel_project()

    flag = "-D" if force else "-d"
    code, out, err = run_project_cmd(["git", "branch", flag, branch_name], project_path=project_path)
    if code == 0:
        return f"Deleted branch `{branch_name}`."
    return f"Failed to delete branch `{branch_name}`: {err or out}"
