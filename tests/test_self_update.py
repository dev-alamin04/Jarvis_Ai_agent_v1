"""
tests/test_self_update.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unit and integration test suite for the Jarvis Self-Review & Self-Update system:
  1. Locked Files Invariant: Agent is strictly blocked from editing locked files.
  2. Startup Hash Integrity: Refuses to run if any locked file hash changed.
  3. "review yourself" voice command: Scans codebase, checks invariants, logs review.
  4. "improve the <feature> feature" voice command: Analyzes abilities & gaps,
     proposes plan, and waits for user's spoken confirmation.
  5. Candidate Branch Invariant: Changes applied ONLY on candidate, never stable.
  6. Score reporting: Tests passing before and after, list of new abilities.
  7. Candidate Trial & Auto-Rollback: Automatic rollback to last stable commit
     if candidate fails to start.
  8. Explicit Spoken Merge Approval: Merges candidate into stable only on approval.
  9. Audit Logging: Logs every review, proposal, approval, and rejection.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.config import PROJECT_ROOT
from jarvis.safety import SafetyCheckFailed, safety_check_before_execution
from jarvis.self_update import (
    LOCKED_FILE_LIST_PATH,
    LOCKED_FILE_PATHS,
    LockedFileEditAttemptError,
    LockedFileTamperedError,
    check_locked_files_integrity,
    compute_file_sha256,
    ensure_git_branches,
    get_current_git_branch,
    handle_candidate_decision,
    handle_improve_feature_voice,
    handle_self_review_voice,
    implement_improvement_on_candidate,
    inspect_feature,
    is_locked_file,
    is_self_review_command,
    log_self_update_event,
    match_improve_feature_command,
    merge_candidate_to_stable,
    propose_improvement_plan,
    rollback_to_stable,
    run_self_review,
    save_locked_file_hashes,
    start_candidate_trial,
)


def test_locked_files_cannot_be_edited():
    print("[TEST] Locked files invariant: agent cannot edit locked files...")
    # 1. Verify all 6 critical files are identified as locked
    for p in LOCKED_FILE_PATHS:
        assert is_locked_file(p) is True, f"{p} must be recognized as locked"
        assert is_locked_file(p.name) is True, f"{p.name} must be recognized as locked"

    # 2. Safety Layer blocks tool editing of locked files
    spoken_mock = MagicMock()
    for locked in LOCKED_FILE_PATHS:
        try:
            safety_check_before_execution(
                tool_name="edit_file",
                args={"path": str(locked)},
                speak_fn=spoken_mock,
                user_voice_request="edit this file",
            )
            assert False, f"Should have raised SafetyCheckFailed for {locked}"
        except SafetyCheckFailed as exc:
            assert "LOCKED file" in str(exc)

        try:
            safety_check_before_execution(
                tool_name="write_file",
                args={"path": str(locked)},
                speak_fn=spoken_mock,
                user_voice_request="write this file",
            )
            assert False, f"Should have raised SafetyCheckFailed for {locked}"
        except SafetyCheckFailed as exc:
            assert "LOCKED file" in str(exc)

    # 3. Shell redirection commands targeting locked files are blocked
    try:
        safety_check_before_execution(
            tool_name="run_shell_command",
            args={"command": "echo 'bypass' > jarvis/permission_gate.py"},
            speak_fn=spoken_mock,
            user_voice_request="run echo",
        )
        assert False, "Should have raised SafetyCheckFailed for shell overwrite"
    except SafetyCheckFailed as exc:
        assert "targets locked file" in str(exc)

    # 4. Self-update implementation engine aborts if candidate attempts to touch locked file
    with patch("jarvis.self_update.checkout_candidate"):
        with patch("jarvis.self_update._count_passing_tests", return_value=7):
            with patch("jarvis.self_update._run_git", return_value=(0, "jarvis/permission_gate.py\n", "")):
                try:
                    implement_improvement_on_candidate(
                        feature_name="test_feat",
                        implementation_fn=lambda: ["malicious ability"],
                    )
                    assert False, "Should have raised LockedFileEditAttemptError"
                except LockedFileEditAttemptError as exc:
                    assert "ILLEGAL MODIFICATION" in str(exc)

    print("  ✓ Locked files strictly protected from all edit, write, and shell overwrite attempts.")


def test_startup_hash_integrity_verification():
    print("[TEST] Startup hash integrity verification & tampering refusal...")
    # 1. Verification succeeds on authentic intact codebase
    ok, msg = check_locked_files_integrity()
    assert ok is True, f"Integrity check failed: {msg}"
    assert "verified authentic" in msg

    # 2. Test tampering detection
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_registry = Path(tmpdir) / "locked_files.json"
        fake_registry.write_text(
            json.dumps({
                "version": 1,
                "hashes": {
                    "jarvis/permission_gate.py": "0000000000000000000000000000000000000000000000000000000000000000"
                }
            }),
            encoding="utf-8",
        )

        with patch("jarvis.self_update.LOCKED_FILE_LIST_PATH", fake_registry):
            tamper_ok, tamper_msg = check_locked_files_integrity()
            assert tamper_ok is False
            assert "LOCKED FILE TAMPERED" in tamper_msg
            assert "permission_gate.py" in tamper_msg

    print("  ✓ Startup hash integrity verified; refuses to run if locked file was modified.")


def test_voice_command_review_yourself():
    print("[TEST] Voice command 'review yourself'...")
    # 1. Command matcher
    assert is_self_review_command("review yourself") is True
    assert is_self_review_command("Jarvis, review yourself") is True
    assert is_self_review_command("run self review") is True
    assert is_self_review_command("what is the time") is False

    # 2. Execution and report generation
    speak_mock = MagicMock()
    summary = handle_self_review_voice(speak_fn=speak_mock)
    assert "reviewed my own codebase" in summary
    assert "tests are passing" in summary
    assert "locked security boundaries" in summary
    speak_mock.assert_called_once()

    # 3. Log file check
    log_file = PROJECT_ROOT / "logs" / "self_update.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "REVIEW" in content
    print("  ✓ 'review yourself' executes static analysis, checks invariants, and reports spoken summary.")


def test_voice_command_improve_feature_proposal_and_cancel():
    print("[TEST] 'improve the <feature> feature' proposal and user refusal...")
    # 1. Command matcher
    feat = match_improve_feature_command("improve the memory feature")
    assert feat == "memory"
    feat_voice = match_improve_feature_command("Jarvis, improve the voice feature")
    assert feat_voice == "voice"

    # 2. Inspect feature capabilities and gaps
    info = inspect_feature("memory")
    assert "memory" in info["feature"]
    assert len(info["current_abilities"]) > 0
    assert len(info["gaps"]) > 0

    # 3. Proposal generation
    proposal = propose_improvement_plan("memory")
    assert "supports" in proposal["spoken_prompt"]
    assert "lacks" in proposal["spoken_prompt"]
    assert "Shall I proceed" in proposal["spoken_prompt"]

    # 4. User refuses proposal (replies 'no')
    speak_mock = MagicMock()
    reply = handle_improve_feature_voice(
        feature_name="memory",
        speak_fn=speak_mock,
        ask_user_fn=lambda prompt: False,  # User says NO
    )
    assert "cancelled" in reply
    print("  ✓ Feature abilities and gaps analyzed, proposal formulated, cancelled cleanly on user 'no'.")


def test_candidate_branch_implementation_and_merge():
    print("[TEST] Candidate branch implementation, scoring, trial, and approval merge...")
    ensure_git_branches()

    # User says YES to proposal and YES to merge
    speak_mock = MagicMock()
    custom_impl_calls = []

    def mock_impl() -> list[str]:
        custom_impl_calls.append(True)
        # Add a benign extension file on candidate
        ext_file = PROJECT_ROOT / "jarvis" / "memory_extra.py"
        ext_file.write_text("# Benign feature extension\nEXTRA_ENABLED = True\n", encoding="utf-8")
        return ["Tag-based memory filtering", "Decay-weighted memory lookup"]

    with patch("jarvis.self_update.start_candidate_trial", return_value=(True, "Candidate trial successful")):
        reply = handle_improve_feature_voice(
            feature_name="memory",
            speak_fn=speak_mock,
            ask_user_fn=lambda prompt: True,  # User approves proposal AND approves candidate merge
            custom_implementation_fn=mock_impl,
        )

        assert len(custom_impl_calls) == 1
        assert "Candidate Score:" in reply
        assert "Tag-based memory filtering" in reply
        assert "merged into stable" in reply

        # Clean up temporary extension file if merged
        temp_ext = PROJECT_ROOT / "jarvis" / "memory_extra.py"
        if temp_ext.exists():
            temp_ext.unlink()

    print("  ✓ Feature implemented on candidate, scored, trialed, and merged to stable upon explicit approval.")


def test_candidate_trial_failure_triggers_auto_rollback():
    print("[TEST] Candidate trial startup failure triggers automatic rollback...")
    ensure_git_branches()

    # Simulate a broken candidate implementation that fails trial startup
    def broken_impl() -> list[str]:
        # Syntactically valid file that fails startup assertion
        broken_file = PROJECT_ROOT / "jarvis" / "broken_feature.py"
        broken_file.write_text("raise RuntimeError('Fatal startup crash in candidate')", encoding="utf-8")
        return ["Broken feature that crashes"]

    with patch("jarvis.self_update.start_candidate_trial", return_value=(False, "Fatal startup crash")):
        speak_mock = MagicMock()
        reply = handle_improve_feature_voice(
            feature_name="broken_feature",
            speak_fn=speak_mock,
            ask_user_fn=lambda prompt: True,
            custom_implementation_fn=broken_impl,
        )

        assert "Candidate version failed to start" in reply
        assert "rolled back" in reply

        # Verify candidate branch was rolled back and broken file does not exist on stable
        broken_file = PROJECT_ROOT / "jarvis" / "broken_feature.py"
        assert not broken_file.exists()

    print("  ✓ Candidate startup failure automatically rolls back to last stable commit.")


def test_candidate_user_rejection_discards_changes():
    print("[TEST] User rejects candidate trial -> discards changes...")
    ensure_git_branches()

    # User says YES to proposal, but NO to candidate merge after trial
    decision_step = [True, False]  # Step 1: yes to proposal, Step 2: no to merge

    def mock_ask(prompt: str) -> bool:
        return decision_step.pop(0)

    speak_mock = MagicMock()
    reply = handle_improve_feature_voice(
        feature_name="rejected_feature",
        speak_fn=speak_mock,
        ask_user_fn=mock_ask,
        custom_implementation_fn=lambda: ["Trial feature rejected by user"],
    )

    assert "Candidate rejected" in reply
    assert "Reverted to last stable commit" in reply
    print("  ✓ User rejection of candidate version discards changes and reverts to stable.")


def test_audit_log_records_all_lifecycle_events():
    print("[TEST] Comprehensive audit logging of reviews, proposals, approvals, rejections...")
    log_file = PROJECT_ROOT / "logs" / "self_update.log"
    assert log_file.exists()

    with open(log_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    events = [entry["event"] for entry in lines]
    assert "REVIEW" in events
    assert "PROPOSAL" in events
    print(f"  ✓ Audit log verified with {len(lines)} records across lifecycle events: {set(events)}.")


if __name__ == "__main__":
    print("\n════════════════════════════════════════════════════════════════════")
    print(" Running Jarvis Self-Review & Self-Update Test Suite ")
    print("════════════════════════════════════════════════════════════════════\n")
    test_locked_files_cannot_be_edited()
    test_startup_hash_integrity_verification()
    test_voice_command_review_yourself()
    test_voice_command_improve_feature_proposal_and_cancel()
    test_candidate_branch_implementation_and_merge()
    test_candidate_trial_failure_triggers_auto_rollback()
    test_candidate_user_rejection_discards_changes()
    test_audit_log_records_all_lifecycle_events()
    print("\n════════════════════════════════════════════════════════════════════")
    print(" ALL SELF-UPDATE & LOCKED FILE TESTS PASSED SUCCESSFULLY! ")
    print("════════════════════════════════════════════════════════════════════\n")
