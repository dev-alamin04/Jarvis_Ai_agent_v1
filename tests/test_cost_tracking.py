"""
tests/test_cost_tracking.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unit and integration test suite for Jarvis Cost Tracking & Spending Limits:
  1. Token counting and estimated cost calculations (model, whisper, tts)
  2. Local SQLite database persistence (daily and monthly totals)
  3. Voice commands: "how much have I spent today" and "how much this month"
  4. 80% voice warning and alert deduplication
  5. 100% hard limit: automatic downgrade to cheaper model (gpt-4o-mini)
  6. 100% hard limit: expensive action spoken confirmation gate
  7. Real-time UI event emission with running costs
  8. Security Invariant: API keys (sk-...) are NEVER logged or stored
  9. Tool registry & Central Tool Risk Table integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
os.environ["JARVIS_TEST_MODE"] = "1"

import json
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jarvis.cost.config import (
    get_cheaper_model,
    get_daily_limit,
    get_expensive_tools,
    get_monthly_limit,
    get_rates,
    load_cost_config,
)
from jarvis.cost.gate import check_expensive_action_confirmation
from jarvis.cost.tracker import (
    _get_db,
    _sanitize_secrets,
    calculate_model_cost,
    calculate_speech_cost,
    calculate_transcription_cost,
    check_and_notify_thresholds,
    get_cost_month,
    get_cost_today,
    is_hard_limit_reached,
    reset_threshold_warnings,
    track_model_call,
    track_speech,
    track_transcription,
)
from jarvis.cost.voice_commands import (
    handle_cost_inquiry,
    is_cost_inquiry,
    is_today_cost_query,
)
from jarvis.model_router import select_model
from jarvis.permission_gate import PermissionDenied
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel
from jarvis.tools import TOOL_REGISTRY, get_tool_schemas


# ── 1. Token Counting & Cost Calculations ─────────────────────────────────────

def test_cost_calculations():
    print("[TEST] Token counting and estimated cost calculations...")
    # 1. gpt-4o: $2.50 / 1M prompt, $10.00 / 1M completion
    # 10,000 prompt tokens = 10,000 * 0.0000025 = $0.025
    # 2,000 completion tokens = 2,000 * 0.00001 = $0.020
    # Total = $0.045
    cost_4o = calculate_model_cost("gpt-4o", prompt_tokens=10_000, completion_tokens=2_000)
    assert abs(cost_4o - 0.045) < 0.0001, f"Expected 0.045, got {cost_4o}"

    # 2. gpt-4o-mini: $0.15 / 1M prompt, $0.60 / 1M completion
    # 10,000 prompt tokens = 10,000 * 0.00000015 = $0.0015
    # 2,000 completion tokens = 2,000 * 0.0000006 = $0.0012
    # Total = $0.0027
    cost_mini = calculate_model_cost("gpt-4o-mini", prompt_tokens=10_000, completion_tokens=2_000)
    assert abs(cost_mini - 0.0027) < 0.0001, f"Expected 0.0027, got {cost_mini}"

    # 3. Whisper-1 transcription: $0.006 per minute
    # 30 seconds = 0.5 minutes = $0.003
    cost_whisper = calculate_transcription_cost(audio_seconds=30.0, model="whisper-1")
    assert abs(cost_whisper - 0.003) < 0.0001, f"Expected 0.003, got {cost_whisper}"

    # 4. TTS-1 speech synthesis: $15.00 per 1M characters
    # 1,000 characters = 1,000 * 0.000015 = $0.015
    cost_tts = calculate_speech_cost(chars=1_000, model="tts-1")
    assert abs(cost_tts - 0.015) < 0.0001, f"Expected 0.015, got {cost_tts}"

    print("  ✓ Pricing mathematics verified across all modalities.")


# ── 2. SQLite Database Persistence & Accumulation ─────────────────────────────

def test_database_persistence_and_accumulation():
    print("[TEST] SQLite database persistence per day and per month...")
    reset_threshold_warnings()

    # Track model call
    c1 = track_model_call(
        model="gpt-4o-mini",
        prompt_tokens=5000,
        completion_tokens=1000,
        details={"query": "test query"},
    )
    assert c1 > 0

    # Track transcription
    c2 = track_transcription(audio_seconds=15.0, model="whisper-1")
    assert c2 > 0

    # Track speech
    c3 = track_speech(text_or_chars="Hello Alamin, how can I help you?", model="tts-1")
    assert c3 > 0

    today = get_cost_today()
    month = get_cost_month()

    assert today["total_cost"] >= (c1 + c2 + c3) - 1e-6
    assert today["call_count"] >= 3
    assert today["total_tokens"] >= 6000
    assert today["model_cost"] >= c1
    assert today["transcription_cost"] >= c2
    assert today["speech_cost"] >= c3

    assert month["total_cost"] >= today["total_cost"]
    assert month["call_count"] >= today["call_count"]

    # Verify rows in raw SQLite database
    conn = _get_db()
    cursor = conn.execute("SELECT COUNT(*) as cnt FROM cost_events")
    count = cursor.fetchone()["cnt"]
    assert count >= 3

    print("  ✓ SQLite persistence and day/month accumulation verified.")


# ── 3. Voice Commands: "how much have I spent today" & "how much this month" ─

def test_voice_commands():
    print("[TEST] Voice commands: 'how much have I spent today' and 'how much this month'...")
    # Pattern matching
    assert is_cost_inquiry("how much have I spent today")
    assert is_cost_inquiry("how much have i spent today")
    assert is_cost_inquiry("how much did I spend today")
    assert is_cost_inquiry("how much today")
    assert is_cost_inquiry("what is my spending today")
    assert is_cost_inquiry("cost today")

    assert is_cost_inquiry("how much this month")
    assert is_cost_inquiry("how much have I spent this month")
    assert is_cost_inquiry("how much did I spend this month")
    assert is_cost_inquiry("what is my spending this month")
    assert is_cost_inquiry("cost this month")

    assert is_today_cost_query("how much have I spent today")
    assert not is_today_cost_query("how much this month")

    # Command execution
    spoken_today = []
    res_today = handle_cost_inquiry("how much have I spent today", speak_fn=lambda m: spoken_today.append(m))
    assert "Daily Spending Summary" in res_today
    assert "Voice Reply" in res_today
    assert len(spoken_today) == 1
    assert "today" in spoken_today[0].lower()
    assert "$" in spoken_today[0]

    spoken_month = []
    res_month = handle_cost_inquiry("how much this month", speak_fn=lambda m: spoken_month.append(m))
    assert "Monthly Spending Summary" in res_month
    assert len(spoken_month) == 1
    assert "month" in spoken_month[0].lower()
    assert "$" in spoken_month[0]

    print("  ✓ Voice commands parsing and spoken responses verified.")


# ── 4. 80% Voice Warning & Alert Deduplication ────────────────────────────────

def test_eighty_percent_voice_warning():
    print("[TEST] 80% voice warning threshold and alert deduplication...")
    reset_threshold_warnings()

    spoken_warnings = []

    def mock_speak(msg):
        spoken_warnings.append(msg)

    # Set artificial daily limit to $0.10 via environment
    with patch.dict(os.environ, {"JARVIS_DAILY_LIMIT_USD": "0.10"}):
        # Insert event to cross $0.08 (80%)
        track_model_call(
            model="gpt-4o",
            prompt_tokens=25_000,     # $0.0625
            completion_tokens=2_500,  # $0.0250 -> Total = $0.0875 (> 80% of $0.10)
            speak_fn=mock_speak,
        )

        assert len(spoken_warnings) > 0
        warn_msg = spoken_warnings[0]
        assert "spending limit" in warn_msg
        assert "8" in warn_msg or "9" in warn_msg or "reached" in warn_msg

        # Deduplication invariant: Second call on same day should NOT re-trigger speech alert
        initial_count = len(spoken_warnings)
        track_model_call(
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
            speak_fn=mock_speak,
        )
        assert len(spoken_warnings) == initial_count

    print("  ✓ 80% voice warning and alert deduplication verified.")


# ── 5. 100% Hard Limit: Model Downgrade in Router ─────────────────────────────

def test_hard_limit_model_downgrade():
    print("[TEST] 100% hard limit: automatic downgrade to cheaper model...")
    # Set limit low so current spend exceeds 100%
    with patch.dict(os.environ, {"JARVIS_DAILY_LIMIT_USD": "0.01"}):
        # Current spend in DB is > $0.01 from previous tests
        assert is_hard_limit_reached()

        # Query that would normally trigger gpt-4o (complex keyword 'debug')
        model, reason = select_model("Jarvis, debug this complex Laravel error")
        assert model == "gpt-4o-mini", f"Expected cheaper model 'gpt-4o-mini', got {model}"
        assert reason == "cost_limit_cheaper_model"

        # Vision query that would normally trigger gpt-4o
        model_vis, _ = select_model("look at the screen and fix this")
        assert model_vis == "gpt-4o-mini"

    # Reset limit to normal ($10.00), verify router returns gpt-4o for complex queries
    with patch.dict(os.environ, {"JARVIS_DAILY_LIMIT_USD": "100.00", "JARVIS_MONTHLY_LIMIT_USD": "500.00"}):
        model_normal, reason_normal = select_model("Jarvis, debug this complex Laravel error")
        assert model_normal == "gpt-4o"
        assert "complex_keyword" in reason_normal

    print("  ✓ Automatic model downgrade at 100% limit verified.")


# ── 6. 100% Hard Limit: Expensive Action Confirmation Gate ────────────────────

def test_expensive_action_confirmation_gate():
    print("[TEST] 100% hard limit: expensive action confirmation gate...")
    spoken_prompts = []

    def mock_speak(msg):
        spoken_prompts.append(msg)

    # 1. Budget exhausted -> user denies expensive action
    with patch.dict(os.environ, {"JARVIS_DAILY_LIMIT_USD": "0.01"}):
        assert is_hard_limit_reached()

        # Expensive action 'take_screenshot'
        with pytest.raises(PermissionDenied):
            check_expensive_action_confirmation(
                action_name="take_screenshot",
                speak_fn=mock_speak,
                ask_user_fn=lambda _: False,  # User says NO
            )

        assert len(spoken_prompts) > 0
        assert "spending limit" in spoken_prompts[0]
        assert "take_screenshot" in spoken_prompts[0]

        # 2. Budget exhausted -> user approves expensive action
        spoken_prompts.clear()
        res = check_expensive_action_confirmation(
            action_name="server_deploy",
            speak_fn=mock_speak,
            ask_user_fn=lambda _: True,  # User says YES
        )
        assert res is True
        assert len(spoken_prompts) > 0
        assert "server_deploy" in spoken_prompts[0]

        # 3. Inexpensive action does not trigger the gate
        spoken_prompts.clear()
        res_cheap = check_expensive_action_confirmation(
            action_name="read_file",
            speak_fn=mock_speak,
            ask_user_fn=lambda _: False,
        )
        assert res_cheap is True
        assert len(spoken_prompts) == 0

    print("  ✓ Expensive action confirmation gate verified.")


# ── 7. UI Event Emission with Running Costs ───────────────────────────────────

def test_ui_cost_events():
    print("[TEST] Real-time UI event emission...")
    emitted = []

    with patch("jarvis.ui_events.emit") as mock_emit:
        check_and_notify_thresholds()
        assert mock_emit.called
        call_args = mock_emit.call_args
        event_name = call_args[0][0]
        kwargs = call_args[1]
        assert event_name == "cost"
        assert "today" in kwargs
        assert "month" in kwargs
        assert "daily_limit" in kwargs
        assert "monthly_limit" in kwargs
        assert kwargs["today"].startswith("$")

    print("  ✓ Real-time UI cost events verified.")


# ── 8. Security Invariant: API Keys NEVER Logged ──────────────────────────────

def test_api_key_redaction_security():
    print("[TEST] Security Invariant: API keys are NEVER logged or stored in DB...")
    dummy_key = "sk-proj-FAKE9876543210abcdefghijklmnopQRSTUVWXYZ"

    # Test secret sanitizer
    sanitized = _sanitize_secrets(f"Error calling OpenAI with key {dummy_key} on prompt")
    assert dummy_key not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized

    # Track call with secret in details
    track_model_call(
        model="gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=5,
        details={"auth": dummy_key, "header": f"Bearer {dummy_key}"},
    )

    # Check raw SQLite cost_events
    conn = _get_db()
    cursor = conn.execute("SELECT details FROM cost_events ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    assert dummy_key not in row["details"]
    assert "[REDACTED_API_KEY]" in row["details"]

    print("  ✓ API key redaction invariant verified.")


# ── 9. Tool Registry and Risk Table Integration ───────────────────────────────

def test_tool_registry_and_risk_table():
    print("[TEST] Tool registry and Risk Table integration...")
    # Verify in TOOL_REGISTRY
    assert "get_cost_today" in TOOL_REGISTRY
    assert "get_cost_month" in TOOL_REGISTRY

    # Verify in schemas
    schemas = get_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "get_cost_today" in names
    assert "get_cost_month" in names

    # Verify in CENTRAL_TOOL_RISK_TABLE
    assert CENTRAL_TOOL_RISK_TABLE["get_cost_today"] == RiskLevel.SAFE
    assert CENTRAL_TOOL_RISK_TABLE["get_cost_month"] == RiskLevel.SAFE

    print("  ✓ Tool registry and Central Risk Table integration verified.")


if __name__ == "__main__":
    test_cost_calculations()
    test_database_persistence_and_accumulation()
    test_voice_commands()
    test_eighty_percent_voice_warning()
    test_hard_limit_model_downgrade()
    test_expensive_action_confirmation_gate()
    test_ui_cost_events()
    test_api_key_redaction_security()
    test_tool_registry_and_risk_table()
    print("\n🎉 ALL COST TRACKING TESTS PASSED SUCCESSFULLY! 🎉")
