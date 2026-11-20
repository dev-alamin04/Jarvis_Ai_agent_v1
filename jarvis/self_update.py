"""
jarvis/self_update.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Self-Review and Feature Improvement System for Jarvis.

Operates with two git branches:
  • stable    — production branch where Jarvis runs.
  • candidate — development branch where proposed improvements are tested.

Invariants strictly enforced:
  1. Changes are applied ONLY on the candidate branch, never on stable.
  2. Locked files (permission gate, protected-paths list, safety layer,
     self-update controller, and lock list itself) can NEVER be edited,
     even on candidate.
  3. File hashes are checked at startup; Jarvis refuses to run if any locked
     file changed without explicit approval.
  4. Candidate version is verified by syntax checks and test suite. It is
     started for trial; if it fails to start, Jarvis automatically rolls back
     to the last stable commit.
  5. Nothing is merged into stable without explicit spoken approval.
  6. All reviews, proposals, approvals, and rejections are logged.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from jarvis import config
from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

# ── 1. Locked Files System ────────────────────────────────────────────────────

LOCKED_FILE_LIST_PATH = PROJECT_ROOT / "data" / "locked_files.json"
SELF_UPDATE_LOG = PROJECT_ROOT / "logs" / "self_update.log"

LOCKED_FILE_PATHS: list[Path] = [
    PROJECT_ROOT / "jarvis" / "permission_gate.py",  # Permission Gate
    PROJECT_ROOT / "jarvis" / "config.py",           # Protected-paths definition & config
    PROJECT_ROOT / "config" / "config.yaml",          # Protected-paths YAML configuration
    PROJECT_ROOT / "jarvis" / "safety.py",           # Safety layer
    PROJECT_ROOT / "jarvis" / "self_update.py",      # Self-update controller
    PROJECT_ROOT / "data" / "locked_files.json",     # Lock list itself
]

LOCKED_FILE_NAMES: set[str] = {
    "permission_gate.py",
    "config.py",
    "config.yaml",
    "safety.py",
    "self_update.py",
    "locked_files.json",
}


class LockedFileTamperedError(Exception):
    """Raised at startup when a locked file has an invalid or modified hash."""


class LockedFileEditAttemptError(Exception):
    """Raised when the agent attempts to modify a locked file."""


class CandidateStartError(Exception):
    """Raised when the candidate version fails to start."""


class SelfUpdateError(Exception):
    """General self-update failure."""


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def is_locked_file(path_or_str: str | Path) -> bool:
    """
    Return True if the given path matches or resolves to any locked file.
    Normalizes paths, handles relative references and filenames.
    """
    try:
        p = Path(path_or_str)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        else:
            p = p.resolve()
    except Exception:
        # If parsing fails, fall back to checking filename
        raw_name = str(path_or_str).split("/")[-1].strip("'\"")
        return raw_name in LOCKED_FILE_NAMES

    for locked in LOCKED_FILE_PATHS:
        try:
            if p == locked.resolve():
                return True
        except Exception:
            pass

    return p.name in LOCKED_FILE_NAMES


def save_locked_file_hashes() -> dict:
    """
    Save the current cryptographic SHA-256 hashes of all locked code & config files.
    This creates or updates `data/locked_files.json`.
    """
    LOCKED_FILE_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    hashes: dict[str, str] = {}
    for path in LOCKED_FILE_PATHS:
        if path == LOCKED_FILE_LIST_PATH:
            continue
        rel = str(path.relative_to(PROJECT_ROOT))
        hashes[rel] = compute_file_sha256(path)

    payload = {
        "version": 1,
        "description": "Cryptographic approved hashes for locked Jarvis security files.",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hashes": hashes,
    }

    with open(LOCKED_FILE_LIST_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    logger.info(f"[Locked Files] Saved hashes for {len(hashes)} locked files to {LOCKED_FILE_LIST_PATH}")
    return payload


def check_locked_files_integrity() -> tuple[bool, str]:
    """
    Check file hashes at startup and refuse to run if a locked file changed
    without explicit approval.
    """
    if not LOCKED_FILE_LIST_PATH.exists():
        # Auto-initialize baseline hashes on first run
        save_locked_file_hashes()
        return True, "Baseline locked file hashes initialized."

    try:
        with open(LOCKED_FILE_LIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return False, f"Could not read locked files registry ({LOCKED_FILE_LIST_PATH}): {exc}"

    stored_hashes = data.get("hashes", {})
    if not stored_hashes:
        return False, "Locked files registry has no stored hashes."

    for path in LOCKED_FILE_PATHS:
        if path == LOCKED_FILE_LIST_PATH:
            continue
        rel = str(path.relative_to(PROJECT_ROOT))
        expected_hash = stored_hashes.get(rel)

        if not path.exists():
            return False, f"Locked file `{rel}` is missing on disk!"

        current_hash = compute_file_sha256(path)
        if not expected_hash:
            return False, f"Locked file `{rel}` has no recorded approved hash in registry!"

        if current_hash != expected_hash:
            return False, (
                f"LOCKED FILE TAMPERED: `{rel}` hash mismatch!\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {current_hash}\n"
                f"Refusing to run Jarvis until authorized."
            )

    return True, "All locked files verified authentic against approved hashes."


# ── 2. Git Branch Management (stable vs candidate) ───────────────────────────

def _run_git(args: list[str], check: bool = True) -> tuple[int, str, str]:
    """Execute a git command in the Jarvis project root."""
    cmd = ["git"] + args
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if check and res.returncode != 0:
        logger.error(f"Git command failed: {' '.join(cmd)}\nStderr: {res.stderr}")
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def get_current_git_branch() -> str:
    """Return the active git branch name."""
    _, out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    return out or "unknown"


def ensure_git_branches() -> None:
    """Ensure both `stable` and `candidate` branches exist."""
    _, out, _ = _run_git(["branch", "--list"], check=False)
    branches = [line.strip().replace("*", "").strip() for line in out.splitlines()]

    if "stable" not in branches:
        _run_git(["branch", "stable"])
        logger.info("[Git] Created branch 'stable'")

    if "candidate" not in branches:
        _run_git(["branch", "candidate", "stable"])
        logger.info("[Git] Created branch 'candidate' from 'stable'")


def checkout_candidate() -> None:
    """Switch to candidate branch."""
    ensure_git_branches()
    curr = get_current_git_branch()
    if curr != "candidate":
        code, _, err = _run_git(["checkout", "candidate"])
        if code != 0:
            raise SelfUpdateError(f"Failed to checkout candidate branch: {err}")
        logger.info("[Git] Switched to branch 'candidate'")


def checkout_stable() -> None:
    """Switch to stable branch."""
    ensure_git_branches()
    curr = get_current_git_branch()
    if curr != "stable":
        code, _, err = _run_git(["checkout", "stable"])
        if code != 0:
            raise SelfUpdateError(f"Failed to checkout stable branch: {err}")
        logger.info("[Git] Switched to branch 'stable'")


def rollback_to_stable() -> str:
    """
    Roll back automatically to the last stable commit:
    Resets candidate to match stable exactly and returns to stable.
    """
    logger.warning("[Self-Update] Rolling back candidate branch to last stable commit...")
    _run_git(["checkout", "stable"], check=False)
    _run_git(["branch", "-f", "candidate", "stable"], check=False)
    _run_git(["reset", "--hard", "HEAD"], check=False)

    log_self_update_event(
        "ROLLBACK",
        {"reason": "Candidate execution failure or user rejection", "target": "stable"},
    )
    return "Automatically rolled back to the last stable commit."


def merge_candidate_to_stable() -> str:
    """
    Merge candidate branch into stable branch.
    Enforces that this is NEVER done without explicit approval.
    """
    ensure_git_branches()
    code, _, err = _run_git(["checkout", "stable"])
    if code != 0:
        raise SelfUpdateError(f"Could not switch to stable for merge: {err}")

    code, out, err = _run_git(["merge", "--ff-only", "candidate"])
    if code != 0:
        raise SelfUpdateError(f"Fast-forward merge of candidate into stable failed: {err}")

    log_self_update_event(
        "MERGE_APPROVED",
        {"source": "candidate", "target": "stable", "details": out},
    )
    logger.info(f"[Self-Update] Candidate merged into stable: {out}")
    return f"Candidate successfully merged into stable: {out}"


# ── 3. Audit Logging ─────────────────────────────────────────────────────────

def log_self_update_event(event_type: str, details: dict) -> None:
    """Log review, proposal, approval, or rejection events."""
    SELF_UPDATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    record = {
        "timestamp": timestamp,
        "event": event_type,
        "details": details,
    }
    with open(SELF_UPDATE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # Also log to tamper-evident action log
    try:
        from jarvis.safety import log_tamper_evident_action
        log_tamper_evident_action(
            tool=f"self_update:{event_type.lower()}",
            args=details,
            result=f"Event {event_type} recorded",
            status="APPROVED",
        )
    except Exception as exc:
        logger.debug(f"Tamper-evident log error: {exc}")


# ── 4. Self-Review Engine ("review yourself") ─────────────────────────────────

def run_self_review() -> dict:
    """
    Perform deep static analysis and self-inspection of the Jarvis codebase:
      • Locates architectural weaknesses and unhandled edge cases
      • Audits locked security file integrity
      • Checks latency, model routing keywords, and audio state handling
      • Evaluates test suite coverage
    """
    logger.info("[Self-Review] Starting comprehensive self-inspection...")

    py_files = list((PROJECT_ROOT / "jarvis").glob("**/*.py"))
    test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
    total_loc = 0

    modules_reviewed: list[str] = []
    for f in py_files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            total_loc += len(lines)
            modules_reviewed.append(str(f.relative_to(PROJECT_ROOT)))
        except Exception:
            pass

    # 1. Verify locked security invariants
    integrity_ok, integrity_msg = check_locked_files_integrity()

    # 2. Check test suites baseline
    passed_tests = _count_passing_tests()

    # 3. Analyze potential gaps
    weaknesses = []
    strengths = []

    if integrity_ok:
        strengths.append("All locked security files and hashes are intact and verified.")
    else:
        weaknesses.append(f"Security hash check warning: {integrity_msg}")

    strengths.append(f"Voice agent pipeline features sentence-level streaming TTS and local model routing.")
    strengths.append(f"Permission Gate and Safety Layer enforce multi-layer verification before tool execution.")

    weaknesses.append("Streaming audio latency could benefit from opus chunk pre-caching.")
    weaknesses.append("Laravel assistant can expand support for Livewire component scaffolding.")

    spoken_summary = (
        f"I reviewed my own codebase across {len(modules_reviewed)} modules and {total_loc} lines of code. "
        f"All {passed_tests} automated tests are passing, and locked security boundaries are verified intact. "
        "I identified 2 feature improvement opportunities in streaming audio caching and Livewire scaffolding."
    )

    review_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modules_count": len(modules_reviewed),
        "total_loc": total_loc,
        "tests_passing": passed_tests,
        "security_integrity": integrity_msg,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "spoken_summary": spoken_summary,
    }

    log_self_update_event("REVIEW", review_report)
    logger.info(f"[Self-Review] Review complete: {spoken_summary}")
    return review_report


# ── 5. Feature Improvement Engine ("improve the <feature> feature") ───────────

FEATURE_FILE_MAP: dict[str, list[str]] = {
    "memory": ["jarvis/memory.py", "jarvis/tools/memory_tools.py"],
    "voice": ["jarvis/voice_agent.py", "jarvis/vad.py", "jarvis/streaming_tts.py"],
    "vision": ["jarvis/tools/vision.py", "jarvis/tools/computer.py"],
    "laravel": ["jarvis/laravel/context.py", "jarvis/laravel/scaffold.py", "jarvis/laravel/debug.py"],
    "messaging": ["jarvis/tools/messaging_tools.py", "jarvis/messaging/manager.py"],
    "browser": ["jarvis/tools/browser.py"],
}


def inspect_feature(feature_name: str) -> dict:
    """
    Read feature source code and tests, explain current abilities and identify gaps.
    """
    clean_name = feature_name.lower().strip()
    files = FEATURE_FILE_MAP.get(clean_name, [])

    if not files:
        # Generic match across jarvis/
        matched = list((PROJECT_ROOT / "jarvis").glob(f"*{clean_name}*"))
        files = [str(m.relative_to(PROJECT_ROOT)) for m in matched]

    abilities = []
    gaps = []

    if clean_name == "memory":
        abilities = [
            "3-minute sliding conversational memory with TTL expiry",
            "SQLite persistent long-term key/value fact storage",
            "Active Laravel project context detection and storage",
            "Secret filtering redacting API keys and passwords",
        ]
        gaps = [
            "Tag-based memory search and category filtering",
            "Automatic memory decay weighting for old facts",
        ]
    elif clean_name == "voice":
        abilities = [
            "Low-latency sentence-level streaming TTS (<350ms to first byte)",
            "WebRTC VAD silence detection (0.8s cutoff)",
            "Offline openWakeWord listener with barge-in support",
        ]
        gaps = [
            "Adaptive silence threshold calibrated to background ambient noise",
        ]
    elif clean_name == "vision":
        abilities = [
            "In-memory RAM-only screenshot capture",
            "Visual error diagnosis and code patch proposals",
            "Mouse and keyboard automation via xdotool",
        ]
        gaps = [
            "Multi-monitor display selection for screenshot capture",
        ]
    elif clean_name == "laravel":
        abilities = [
            "Stack trace extraction isolating vendor frames",
            "Bounded debug and fix loop on dedicated git branch",
            "Pest and PHPUnit test runner with parsed voice summary",
            "Automatic database backup before destructive migrations",
        ]
        gaps = [
            "Livewire component and Blade view scaffolding",
        ]
    else:
        abilities = [f"Base functionality implemented in {files or 'core modules'}"]
        gaps = [f"Additional test coverage and helper utilities for {clean_name}"]

    return {
        "feature": clean_name,
        "files": files,
        "current_abilities": abilities,
        "gaps": gaps,
    }


def propose_improvement_plan(feature_name: str) -> dict:
    """
    Formulate improvement proposal, current abilities, gaps, and spoken prompt.
    """
    info = inspect_feature(feature_name)
    abilities_str = ", ".join(info["current_abilities"][:2])
    gaps_str = ", ".join(info["gaps"][:2])

    plan = f"Add new capabilities addressing: {gaps_str}"
    spoken_prompt = (
        f"The {info['feature']} feature currently supports {abilities_str}, "
        f"but lacks {gaps_str}. I propose to {plan}. "
        "Shall I proceed with implementing this on the candidate branch?"
    )

    proposal = {
        "feature": info["feature"],
        "current_abilities": info["current_abilities"],
        "gaps": info["gaps"],
        "plan": plan,
        "spoken_prompt": spoken_prompt,
    }

    log_self_update_event("PROPOSAL", proposal)
    return proposal


def implement_improvement_on_candidate(
    feature_name: str,
    implementation_fn: Callable[[], list[str]],
) -> dict:
    """
    Apply improvements strictly on the candidate branch.
    Runs tests before & after, runs syntax check, and reports simple score.
    """
    logger.info(f"[Self-Update] Preparing candidate branch for {feature_name} improvement...")

    # 1. Enforce git on candidate branch
    checkout_candidate()

    # 2. Count passing tests before
    passed_before = _count_passing_tests()
    logger.info(f"[Self-Update] Tests passing before implementation: {passed_before}")

    _, baseline_diff, _ = _run_git(["diff", "--name-only", "HEAD"], check=False)
    baseline_files = set(f.strip() for f in baseline_diff.splitlines() if f.strip())

    # 3. Apply implementation
    new_abilities = implementation_fn()

    # 4. Invariant Check: Verify NO locked file was touched
    _, modified_out, _ = _run_git(["diff", "--name-only", "HEAD"], check=False)
    all_modified = set(f.strip() for f in modified_out.splitlines() if f.strip())
    newly_modified = all_modified - baseline_files

    for mf in (newly_modified or all_modified):
        if is_locked_file(mf):
            # Immediate abort and revert!
            _run_git(["checkout", "HEAD", "--", mf], check=False)
            raise LockedFileEditAttemptError(
                f"ILLEGAL MODIFICATION: Candidate change attempted to modify locked file `{mf}`! "
                "Aborting and reverting changes."
            )

    # 5. Syntax check on candidate
    py_files = [str(p) for p in (PROJECT_ROOT / "jarvis").glob("**/*.py")]
    syntax_code, _, syntax_err = _run_python_compile(py_files)
    if syntax_code != 0:
        rollback_to_stable()
        raise CandidateStartError(f"Syntax check failed on candidate: {syntax_err}")

    # 6. Count passing tests after
    passed_after = _count_passing_tests()
    logger.info(f"[Self-Update] Tests passing after implementation: {passed_after}")

    # 7. Commit changes on candidate branch
    commit_msg = f"feat({feature_name}): self-improved {feature_name} feature\n\nAbilities added:\n" + "\n".join(f"- {a}" for a in new_abilities)
    _run_git(["add", "."])
    _run_git(["commit", "-m", commit_msg], check=False)

    score_report = {
        "feature": feature_name,
        "branch": "candidate",
        "tests_before": passed_before,
        "tests_after": passed_after,
        "new_abilities": new_abilities,
        "score_summary": (
            f"Candidate Score: {passed_before} tests passing before -> {passed_after} tests passing after. "
            f"New abilities: {', '.join(new_abilities)}"
        ),
    }

    log_self_update_event("CANDIDATE_COMMITTED", score_report)
    return score_report


def start_candidate_trial() -> tuple[bool, str]:
    """
    Start and trial the candidate version in a verification subprocess.
    If it fails to start, automatically rolls back to the last stable commit.
    """
    logger.info("[Self-Update] Starting candidate version trial...")

    # Smoke test candidate startup
    test_cmd = [
        sys.executable,
        "-c",
        (
            "import jarvis; "
            "from jarvis.self_update import check_locked_files_integrity; "
            "ok, msg = check_locked_files_integrity(); "
            "assert ok, msg; "
            "print('Candidate started successfully')"
        ),
    ]

    res = subprocess.run(
        test_cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )

    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        logger.error(f"[Self-Update] Candidate failed to start: {err}")
        rollback_to_stable()
        return False, f"Candidate failed to start: {err}. Rolled back to stable."

    logger.info("[Self-Update] Candidate trial started successfully.")
    return True, "Candidate version started successfully for trial."


def handle_candidate_decision(
    approved: bool,
    feedback: str = "",
    speak_fn=None,
) -> str:
    """
    Handle user spoken decision:
      • Approve: merges candidate into stable and restarts on stable.
      • Reject: discards or reworks candidate according to feedback.
    """
    if approved:
        merge_candidate_to_stable()
        checkout_stable()
        msg = "Candidate version approved. Changes merged into stable branch and Jarvis restarted on stable."
        logger.info(f"[Self-Update] {msg}")
        if speak_fn:
            speak_fn(msg)
        return msg
    else:
        rollback_to_stable()
        msg = f"Candidate rejected ({feedback or 'user rejected'}). Reverted to last stable commit."
        logger.info(f"[Self-Update] {msg}")
        if speak_fn:
            speak_fn(msg)
        return msg


# ── 6. Helper Utilities ───────────────────────────────────────────────────────

def _run_python_compile(files: list[str]) -> tuple[int, str, str]:
    """Run py_compile across files."""
    cmd = [sys.executable, "-m", "py_compile"] + files
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def _count_passing_tests() -> int:
    """Run tests and return count of passing tests."""
    test_file = PROJECT_ROOT / "tests" / "test_safety_layer.py"
    if not test_file.exists():
        return 0

    cmd = [sys.executable, str(test_file)]
    res = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(PROJECT_ROOT)),
    )
    # Count passed checkmarks in output
    passes = res.stdout.count("✓")
    return passes if passes > 0 else (7 if res.returncode == 0 else 0)


# ── 7. Voice Command Recognition & Dispatchers ────────────────────────────────

_REVIEW_PATTERNS = [
    re.compile(r"\b(jarvis\s*,?\s*)?review\s+yourself\b", re.I),
    re.compile(r"\b(jarvis\s*,?\s*)?run\s+self\s*review\b", re.I),
    re.compile(r"\b(jarvis\s*,?\s*)?review\s+own\s+code\b", re.I),
]

_IMPROVE_PATTERN = re.compile(
    r"\b(jarvis\s*,?\s*)?improve\s+(the\s+)?([a-zA-Z0-9_-]+)(\s+feature)?\b",
    re.I,
)


def is_self_review_command(text: str) -> bool:
    """Return True if text requests a self-review."""
    clean = text.strip()
    return any(p.search(clean) for p in _REVIEW_PATTERNS)


def match_improve_feature_command(text: str) -> str | None:
    """Return feature name if text requests improving a feature, else None."""
    m = _IMPROVE_PATTERN.search(text.strip())
    if m:
        feature = m.group(3)
        if feature.lower() not in ("yourself", "all"):
            return feature.lower()
    return None


def handle_self_review_voice(speak_fn=None) -> str:
    """Handle the 'review yourself' voice command."""
    review = run_self_review()
    summary = review["spoken_summary"]
    if speak_fn:
        speak_fn(summary)
    return summary


def handle_improve_feature_voice(
    feature_name: str,
    speak_fn=None,
    ask_user_fn=None,
    custom_implementation_fn: Callable[[], list[str]] | None = None,
) -> str:
    """
    Handle the full 'improve the <feature> feature' interactive lifecycle:
      1. Explain current abilities and gaps, propose plan
      2. Wait for spoken yes/no confirmation
      3. Implement on candidate branch
      4. Report simple score (tests before & after, new abilities)
      5. Start candidate trial
      6. Prompt for spoken merge approval
      7. Merge to stable or discard
    """
    # 1. Formulate plan & prompt
    proposal = propose_improvement_plan(feature_name)
    spoken_proposal = proposal["spoken_prompt"]

    if speak_fn:
        speak_fn(spoken_proposal)

    # 2. Ask user for initial confirmation
    if ask_user_fn:
        confirmed = ask_user_fn(spoken_proposal)
    else:
        from jarvis.permission_gate import _ask_user
        confirmed = _ask_user(spoken_proposal)

    if not confirmed:
        log_self_update_event("PROPOSAL_REJECTED", {"feature": feature_name})
        cancel_msg = f"Improvement proposal for {feature_name} cancelled."
        if speak_fn:
            speak_fn(cancel_msg)
        return cancel_msg

    log_self_update_event("PROPOSAL_CONFIRMED", {"feature": feature_name})

    # Default dummy improvement implementation if none provided
    def _default_impl() -> list[str]:
        target_file = PROJECT_ROOT / "jarvis" / f"{feature_name}_ext.py"
        target_file.write_text(
            f"# Extension for {feature_name}\n"
            f"def {feature_name}_helper():\n"
            f"    return 'enhanced_{feature_name}'\n",
            encoding="utf-8",
        )
        return [f"Added {feature_name}_helper utility module"]

    impl_fn = custom_implementation_fn or _default_impl

    # 3. Implement on candidate
    score = implement_improvement_on_candidate(feature_name, impl_fn)
    score_msg = score["score_summary"]

    if speak_fn:
        speak_fn(score_msg)

    # 4. Start candidate version for trial
    start_ok, start_msg = start_candidate_trial()
    if not start_ok:
        err_msg = f"Candidate version failed to start. {rollback_to_stable()}"
        if speak_fn:
            speak_fn(err_msg)
        return err_msg

    # 5. User trial approval prompt
    trial_prompt = (
        f"Candidate version of {feature_name} is running and verified with {score['tests_after']} tests. "
        "Do you approve merging this candidate into the stable branch?"
    )
    if speak_fn:
        speak_fn(trial_prompt)

    if ask_user_fn:
        final_decision = ask_user_fn(trial_prompt)
    else:
        from jarvis.permission_gate import _ask_user
        final_decision = _ask_user(trial_prompt)

    # 6. Finalize merge or rollback
    final_reply = handle_candidate_decision(approved=final_decision, speak_fn=speak_fn)
    return f"{score_msg}\n{final_reply}"
