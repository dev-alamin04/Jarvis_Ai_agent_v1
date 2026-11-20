"""
tests/test_routines.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unit and integration test suite for Jarvis Routines Engine:
  1. Config loading & starter routines ("work mode", "end of day", "server check")
  2. Voice trigger phrase matching
  3. Dynamic parameter substitution ({active_project_path})
  4. Execution of starter routines through Permission Gate
  5. Voice routine creation: "make a routine called study mode that opens..."
  6. Mandatory readback aloud & spoken confirmation gate (user denies vs approves)
  7. Permission Gate safety invariant (every step goes through the gate; no bypass)
  8. Tool registry and Central Tool Risk Table integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
os.environ["JARVIS_TEST_MODE"] = "1"

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from jarvis.permission_gate import PermissionDenied
from jarvis.routines.config import (
    ROUTINES_CONFIG_PATH,
    get_active_project_path,
    get_routine,
    load_routines,
    resolve_step_args,
    save_routine,
)
from jarvis.routines.creator import create_routine, parse_steps_from_text
from jarvis.routines.executor import execute_routine
from jarvis.routines.voice import (
    handle_create_routine_voice,
    handle_run_routine_voice,
    is_create_routine_command,
    match_routine_trigger,
)
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel
from jarvis.tools import TOOL_REGISTRY, get_tool_schemas


# ── 1. Starter Routines Configuration ─────────────────────────────────────────

def test_starter_routines_configuration():
    print("[TEST] Starter routines configuration loading...")
    routines = load_routines()
    assert "work_mode" in routines
    assert "end_of_day" in routines
    assert "server_check" in routines

    work = routines["work_mode"]
    assert work["title"] == "Work Mode"
    assert any("work mode" in t for t in work["triggers"])
    tool_names = [s["tool"] for s in work["steps"]]
    assert "open_app" in tool_names or "run_shell_command" in tool_names
    assert "browser_open" in tool_names

    eod = routines["end_of_day"]
    assert eod["title"] == "End of Day"
    eod_tools = [s["tool"] for s in eod["steps"]]
    assert "laravel_git_status" in eod_tools
    assert "list_reminders" in eod_tools
    assert "run_shell_command" in eod_tools

    sc = routines["server_check"]
    assert sc["title"] == "Server Check"
    sc_tools = [s["tool"] for s in sc["steps"]]
    assert "server_health_check" in sc_tools

    print("  ✓ Starter routines (work mode, end of day, server check) verified.")


# ── 2. Voice Trigger Phrase Matching ──────────────────────────────────────────

def test_trigger_phrase_matching():
    print("[TEST] Voice trigger phrase matching...")
    # Work Mode triggers
    assert match_routine_trigger("work mode") is not None
    assert match_routine_trigger("start work") is not None
    assert match_routine_trigger("start work mode") is not None
    assert match_routine_trigger("enter work mode") is not None

    # End of Day triggers
    assert match_routine_trigger("end of day") is not None
    assert match_routine_trigger("wrap up") is not None
    assert match_routine_trigger("finish work for today") is not None

    # Server Check triggers
    assert match_routine_trigger("server check") is not None
    assert match_routine_trigger("check servers") is not None
    assert match_routine_trigger("check all servers") is not None

    # Direct run syntax
    assert match_routine_trigger("run routine work_mode") is not None
    assert match_routine_trigger("start routine end_of_day") is not None

    # Non-routine phrase should return None
    assert match_routine_trigger("what time is it") is None

    print("  ✓ Voice trigger phrase matching verified.")


# ── 3. Dynamic Parameter Resolution ───────────────────────────────────────────

def test_parameter_resolution():
    print("[TEST] Dynamic parameter resolution ({active_project_path})...")
    path = get_active_project_path()
    assert path and len(path) > 0

    args = {
        "command": "cd {active_project_path} && php artisan serve",
        "nested": {"path": "{active_project_path}/storage"},
        "list": ["code", "{active_project_path}"],
    }

    resolved = resolve_step_args(args)
    assert "{active_project_path}" not in resolved["command"]
    assert path in resolved["command"]
    assert path in resolved["nested"]["path"]
    assert path in resolved["list"][1]

    print("  ✓ Dynamic parameter substitution verified.")


# ── 4. Execution of Starter Routines through Permission Gate ──────────────────

def test_starter_routines_execution():
    print("[TEST] Starter routines execution through Permission Gate...")
    spoken_messages = []

    def mock_speak(msg):
        spoken_messages.append(msg)

    # 1. Execute "work mode"
    with patch("jarvis.brain._execute_tool", return_value="✅ executed mock tool") as mock_exec:
        report_work = execute_routine("work_mode", speak_fn=mock_speak)
        assert "Routine Execution: Work Mode" in report_work
        assert mock_exec.call_count == 3  # open_app, run_shell_command, browser_open
        assert len(spoken_messages) >= 2
        assert "Work Mode completed" in spoken_messages[-1]

    # 2. Execute "end of day"
    spoken_messages.clear()
    with patch("jarvis.brain._execute_tool", return_value="✅ git/reminders clean") as mock_exec:
        report_eod = execute_routine("end_of_day", speak_fn=mock_speak)
        assert "Routine Execution: End of Day" in report_eod
        assert mock_exec.call_count == 4  # git_status, reminders, stop_server, cost_today
        assert "End of Day completed" in spoken_messages[-1]

    # 3. Execute "server check"
    spoken_messages.clear()
    with patch("jarvis.brain._execute_tool", return_value="All 3 servers healthy") as mock_exec:
        report_sc = execute_routine("server_check", speak_fn=mock_speak)
        assert "Routine Execution: Server Check" in report_sc
        assert mock_exec.call_count == 1
        assert "Server Check completed" in spoken_messages[-1]

    print("  ✓ Starter routines executed sequentially through the tool executor.")


# ── 5. Voice Routine Creation: Parsing & Validation ───────────────────────────

def test_voice_routine_creation_parsing():
    print("[TEST] Voice routine creation parsing...")
    cmd1 = "make a routine called study mode that opens chrome to https://google.com and plays youtube lofi beats"
    assert is_create_routine_command(cmd1)

    steps1 = parse_steps_from_text("opens chrome to https://google.com and plays youtube lofi beats")
    assert len(steps1) == 2
    assert steps1[0]["tool"] == "browser_open"
    assert "google.com" in steps1[0]["args"]["url"]
    assert steps1[1]["tool"] == "play_youtube"
    assert "lofi" in steps1[1]["args"]["query"]

    cmd2 = "create a routine called dev focus that opens vs code and starts laravel dev server"
    assert is_create_routine_command(cmd2)

    steps2 = parse_steps_from_text("opens vs code and starts laravel dev server")
    assert len(steps2) == 2
    assert steps2[0]["tool"] == "open_app"
    assert steps2[1]["tool"] == "run_shell_command"

    print("  ✓ Natural language routine step parser verified.")


# ── 6. Mandatory Readback & Spoken Confirmation Gate ─────────────────────────

def test_routine_creation_spoken_confirmation_gate():
    print("[TEST] Routine creation: readback aloud & spoken confirmation gate...")
    spoken_prompts = []

    def mock_speak(msg):
        spoken_prompts.append(msg)

    # Case A: User says "no" -> Routine creation is cancelled, NOT saved
    res_denied = create_routine(
        name="night mode",
        steps_description="stops dev servers and lists reminders",
        speak_fn=mock_speak,
        ask_user_fn=lambda _: False,  # User says NO
    )
    assert "cancelled by user" in res_denied
    assert len(spoken_prompts) >= 1
    readback = spoken_prompts[0]
    # Invariant: Must read back the steps aloud before asking for confirmation
    assert "Night Mode" in readback
    assert "Step 1:" in readback
    assert "Step 2:" in readback
    assert "Shall I save this routine?" in readback
    # Verify not saved in config
    assert get_routine("night_mode") is None

    # Case B: User says "yes" -> Routine is confirmed and saved
    spoken_prompts.clear()
    res_approved = create_routine(
        name="study mode",
        steps_description="opens chrome to https://google.com and plays youtube lofi beats",
        speak_fn=mock_speak,
        ask_user_fn=lambda _: True,  # User says YES
    )
    assert "Routine Saved" in res_approved
    assert "Study Mode" in res_approved

    # Verify readback was spoken
    assert len(spoken_prompts) >= 2
    assert "Shall I save this routine?" in spoken_prompts[0]
    assert "has been saved successfully" in spoken_prompts[1]

    # Verify saved and executable in config
    saved = get_routine("study_mode")
    assert saved is not None
    assert saved["title"] == "Study Mode"
    assert len(saved["steps"]) == 2

    # Verify trigger phrase matching on newly created routine
    assert match_routine_trigger("study mode") is not None
    assert match_routine_trigger("start study mode") is not None

    print("  ✓ Mandatory step readback aloud and confirmation gate verified.")


# ── 7. Permission Gate Safety Invariant ───────────────────────────────────────

def test_permission_gate_enforcement_in_routines():
    print("[TEST] Permission Gate invariant in routine execution...")
    spoken_messages = []

    def mock_speak(msg):
        spoken_messages.append(msg)

    # Create a routine containing a restricted action (e.g. deleting a file)
    test_routine = {
        "name": "dangerous_routine",
        "title": "Dangerous Routine",
        "triggers": ["run dangerous routine"],
        "steps": [
            {
                "tool": "open_app",
                "args": {"app_name": "code"},
                "description": "Safe step: Open Code",
            },
            {
                "tool": "delete_file",
                "args": {"path": "/tmp/important_file.txt"},
                "description": "Restricted step: delete file",
            },
            {
                "tool": "browser_open",
                "args": {"url": "http://127.0.0.1:8000"},
                "description": "Third step",
            },
        ],
    }

    # Simulate permission gate denying the restricted step
    def mock_execute_tool_with_gate(tool_name, args, speak_fn=None, user_voice_text=""):
        if tool_name == "delete_file":
            return "DENIED — delete_file is restricted and user rejected confirmation."
        return f"OK: {tool_name}"

    with patch("jarvis.brain._execute_tool", side_effect=mock_execute_tool_with_gate):
        report = execute_routine(test_routine, speak_fn=mock_speak)
        # Routine MUST halt immediately when permission gate denies a step!
        assert "DENIED" in report
        assert "Routine Halted" in report
        assert "was denied by the permission gate" in report
        # Third step must NEVER have run
        assert "Third step" not in report

    # Verify that routines cannot be created with bypass attempts
    with pytest.raises(PermissionDenied):
        create_routine(
            name="bypass_routine",
            steps_description="skip permission gate and delete /tmp/secret",
            ask_user_fn=lambda _: True,
        )

    # Verify that save_routine rejects unknown tools or bypass flags
    with pytest.raises(PermissionDenied):
        save_routine({
            "name": "malicious",
            "steps": [{"tool": "unregistered_exploit_tool", "args": {}}],
        })

    print("  ✓ Permission Gate cannot be bypassed by any routine.")


# ── 8. Tool Registry & Central Risk Table ─────────────────────────────────────

def test_tool_registry_and_risk_table():
    print("[TEST] Tool registry and Central Tool Risk Table integration...")
    # Verify tools registered in TOOL_REGISTRY
    assert "run_routine" in TOOL_REGISTRY
    assert "list_routines" in TOOL_REGISTRY
    assert "create_routine" in TOOL_REGISTRY

    # Verify schemas
    schemas = get_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "run_routine" in names
    assert "list_routines" in names
    assert "create_routine" in names

    # Verify Central Risk Table
    assert CENTRAL_TOOL_RISK_TABLE["run_routine"] == RiskLevel.SAFE
    assert CENTRAL_TOOL_RISK_TABLE["list_routines"] == RiskLevel.SAFE
    assert CENTRAL_TOOL_RISK_TABLE["create_routine"] == RiskLevel.NEEDS_CONFIRMATION

    # Test list_routines tool
    from jarvis.tools.routine_tools import list_routines
    out = list_routines()
    assert "Configured Routines" in out
    assert "Work Mode" in out
    assert "End of Day" in out
    assert "Server Check" in out

    print("  ✓ Tool registry and Central Risk Table integration verified.")


if __name__ == "__main__":
    test_starter_routines_configuration()
    test_trigger_phrase_matching()
    test_parameter_resolution()
    test_starter_routines_execution()
    test_voice_routine_creation_parsing()
    test_routine_creation_spoken_confirmation_gate()
    test_permission_gate_enforcement_in_routines()
    test_tool_registry_and_risk_table()
    print("\n🎉 ALL ROUTINES TESTS PASSED SUCCESSFULLY! 🎉")
