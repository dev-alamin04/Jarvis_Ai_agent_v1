"""
tests/test_focus_and_german.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Comprehensive Test Suite for:
  1. Focus Mode (timer, muting desktop notifications, quiet mode, break reminders, daily summary)
  2. German Study Companion (B1 level, gentle corrections, vocab bank, quizzes, STT/TTS language switching)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

# Set test environment
os.environ["JARVIS_TEST_MODE"] = "1"
os.environ["OPENAI_API_KEY"] = "sk-test-key-for-unit-tests"

from jarvis.focus.manager import (
    _get_db as get_focus_db,
    _on_focus_completed,
    _set_desktop_notifications,
    format_focus_summary,
    get_active_focus_session,
    get_focus_summary,
    is_focus_active,
    start_focus_mode,
    stop_focus_mode,
)
from jarvis.focus.voice import (
    handle_focus_voice,
    match_focus_command,
)
from jarvis.german.companion import (
    _active_session_data,
    generate_quick_quiz,
    get_active_session_info,
    process_german_turn,
    start_german_session,
    stop_german_session,
)
from jarvis.german.state import (
    get_stt_language,
    get_stt_prompt,
    is_german_mode_active,
    set_german_mode,
)
from jarvis.german.store import (
    _STARTER_B1_VOCABULARY,
    add_custom_vocabulary,
    get_common_mistakes,
    get_next_vocabulary_to_introduce,
    get_recent_vocabulary,
    get_study_statistics,
    mark_vocabulary_introduced,
    record_mistake,
)
from jarvis.german.voice import (
    format_german_study_summary,
    handle_german_voice,
    match_german_practice_start,
    match_german_quiz,
    match_german_stop,
    match_german_summary,
)
from jarvis.safety import CENTRAL_TOOL_RISK_TABLE, RiskLevel
from jarvis.tools import TOOL_REGISTRY, get_tool_schemas


# ═════════════════════════════════════════════════════════════════════════════
# 1. FOCUS MODE TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestFocusMode:

    def setup_method(self):
        # Ensure clean state before each test
        stop_focus_mode()

    def teardown_method(self):
        stop_focus_mode()

    @patch("subprocess.run")
    def test_start_focus_mode_and_mute_notifications(self, mock_subproc):
        spoken_messages = []

        res = start_focus_mode(duration_minutes=45, speak_fn=spoken_messages.append)
        assert is_focus_active() is True
        assert "Focus Mode Activated" in res
        assert "45 minutes" in res
        assert any("Starting 45-minute focus mode" in m for m in spoken_messages)

        # Verify gsettings mute was called
        mock_subproc.assert_any_call(
            ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "false"],
            check=False,
            stdout=-3,
            stderr=-3,
            timeout=2,
        )

    def test_duplicate_start_attempt_informs_remaining_time(self):
        start_focus_mode(duration_minutes=30)
        res = start_focus_mode(duration_minutes=15)
        assert "already active" in res

    @patch("subprocess.run")
    def test_stop_focus_mode_early_and_restore_notifications(self, mock_subproc):
        start_focus_mode(duration_minutes=25)
        assert is_focus_active() is True

        res = stop_focus_mode()
        assert is_focus_active() is False
        assert "Focus Mode Stopped" in res

        # Verify gsettings unmute was called
        mock_subproc.assert_any_call(
            ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "true"],
            check=False,
            stdout=-3,
            stderr=-3,
            timeout=2,
        )

    @patch("subprocess.run")
    def test_on_focus_completed_alerts_break_and_saves_to_db(self, mock_subproc):
        spoken_messages = []
        start_focus_mode(duration_minutes=20)

        # Trigger completion callback
        _on_focus_completed(duration_minutes=20, speak_fn=spoken_messages.append)

        assert is_focus_active() is False
        assert any("focus session is complete" in m for m in spoken_messages)
        assert any("take a 5-minute break" in m for m in spoken_messages)

        # Verify summary reflects completed session
        summary = get_focus_summary()
        assert summary["completed_sessions"] >= 1
        assert summary["total_minutes"] >= 20

    def test_focus_voice_command_matching_and_duration_parsing(self):
        assert match_focus_command("focus mode for 45 minutes") is True
        assert match_focus_command("start focus mode for 25 mins") is True
        assert match_focus_command("how many focus sessions today") is True
        assert match_focus_command("stop focus mode") is True
        assert match_focus_command("what is the weather today") is False

        # Test voice dispatch
        res1 = handle_focus_voice("focus mode for 35 minutes")
        assert "35 minutes" in res1
        assert is_focus_active() is True

        res2 = handle_focus_voice("how many focus sessions today")
        assert "Focus Mode Summary" in res2

        res3 = handle_focus_voice("stop focus mode")
        assert "Focus Mode Stopped" in res3
        assert is_focus_active() is False

    def test_focus_stays_quiet_for_reminders_except_urgent_alerts(self):
        from jarvis.assistant.reminders import check_due_reminders, add_reminder
        from jarvis.devops.watcher import BackgroundServerWatcher

        # Start focus mode
        start_focus_mode(duration_minutes=45)
        assert is_focus_active() is True

        # Add a reminder that is due
        add_reminder("Review pull request", "in 0 minutes")

        # Reminders should stay quiet
        spoken_reminders = []
        check_due_reminders(speak_fn=spoken_reminders.append)
        assert spoken_reminders == []  # Completely quiet during focus

        # DevOps urgent server alert should still speak
        watcher = BackgroundServerWatcher()
        spoken_devops = []
        watcher._speak_cb = spoken_devops.append
        watcher._speak_alert("site_down", "Alamin, urgent alert: Production server is down!")
        assert any("urgent alert: Production server is down" in m for m in spoken_devops)


# ═════════════════════════════════════════════════════════════════════════════
# 2. GERMAN STUDY COMPANION TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestGermanCompanion:

    def setup_method(self):
        set_german_mode(False)

    def teardown_method(self):
        set_german_mode(False)

    def test_stt_language_and_prompt_switch_with_german_mode(self):
        # Default state: English
        assert is_german_mode_active() is False
        assert get_stt_language() == "en"
        assert "Jarvis desktop assistant" in get_stt_prompt()

        # Activate German mode
        set_german_mode(True)
        assert is_german_mode_active() is True
        assert get_stt_language() == "de"
        assert "Deutsch auf B1-Niveau" in get_stt_prompt()

        # Deactivate
        set_german_mode(False)
        assert get_stt_language() == "en"

    def test_start_and_stop_german_session(self):
        spoken_messages = []

        start_res = start_german_session(speak_fn=spoken_messages.append)
        assert is_german_mode_active() is True
        assert get_stt_language() == "de"
        assert "German Practice Session Activated" in start_res
        assert any("Deutsch auf B1-Niveau" in m for m in spoken_messages)

        spoken_closing = []
        stop_res = stop_german_session(speak_fn=spoken_closing.append)
        assert is_german_mode_active() is False
        assert get_stt_language() == "en"
        assert "German Practice Session Ended" in stop_res
        assert any("back in English mode" in m for m in spoken_closing)

    def test_database_vocabulary_and_mistakes_storage(self):
        stats_before = get_study_statistics()
        assert stats_before["total_vocabulary"] >= len(_STARTER_B1_VOCABULARY)

        # Retrieve next vocab to introduce
        next_vocab = get_next_vocabulary_to_introduce()
        assert next_vocab is not None
        assert "word" in next_vocab
        assert next_vocab["level"] == "B1"

        # Mark introduced
        mark_vocabulary_introduced(next_vocab["id"])
        recent = get_recent_vocabulary(limit=5)
        assert any(v["id"] == next_vocab["id"] for v in recent)

        # Record mistake with gentle explanation
        mistake_id = record_mistake(
            user_phrase="Ich fahre mit den Zug",
            correction="Ich fahre mit dem Zug",
            explanation="Dativ nach 'mit': der Zug -> dem Zug",
            category="Dativ / Präpositionen",
        )
        assert mistake_id > 0

        common_mistakes = get_common_mistakes(limit=5)
        assert any(m["id"] == mistake_id for m in common_mistakes)
        matched = next(m for m in common_mistakes if m["id"] == mistake_id)
        assert matched["user_phrase"] == "Ich fahre mit den Zug"
        assert "Dativ nach 'mit'" in matched["explanation"]

    @patch("openai.OpenAI")
    def test_process_german_turn_with_gentle_correction(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content=(
                        "Tipp: Man sagt 'Ich bin nach Hause gegangen' (Perfekt mit sein), "
                        "nicht 'Ich habe gegangen'. "
                        "Sehr interessant! Was hast du zu Hause noch gemacht?"
                    )
                )
            )
        ]
        mock_completion.usage = MagicMock(prompt_tokens=40, completion_tokens=30)
        mock_client.chat.completions.create.return_value = mock_completion

        start_german_session()
        spoken_responses = []

        turn_res = process_german_turn(
            user_text="Gestern ich habe nach Hause gegangen.",
            speak_fn=spoken_responses.append,
        )

        assert "Jarvis (B1 Deutsch)" in turn_res
        assert any("Tipp: Man sagt 'Ich bin nach Hause gegangen'" in m for m in spoken_responses)

        # Verify gentle correction was recorded to DB
        mistakes = get_common_mistakes(limit=5)
        assert any("Gestern ich habe" in m["user_phrase"] for m in mistakes)

    def test_generate_quick_quiz_from_mistakes_or_vocab(self):
        # Record a test mistake to quiz on
        record_mistake(
            user_phrase="Er wartet auf seine Freund",
            correction="Er wartet auf seinen Freund",
            explanation="Akkusativ maskulin nach 'warten auf': der Freund -> seinen Freund",
            category="Akkusativ",
        )

        spoken_quiz = []
        quiz_output = generate_quick_quiz(speak_fn=spoken_quiz.append)

        assert "Schnelles Deutsch-Quiz" in quiz_output
        assert len(spoken_quiz) == 1
        assert "Quiz" in spoken_quiz[0]

    def test_german_voice_triggers(self):
        assert match_german_practice_start("German practice") is True
        assert match_german_practice_start("start german practice") is True
        assert match_german_practice_start("let's practice german") is True
        assert match_german_practice_start("sprechen wir deutsch") is True

        assert match_german_quiz("German quiz") is True
        assert match_german_quiz("quiz me in german") is True

        assert match_german_stop("stop german practice") is True
        assert match_german_stop("back to english") is True
        assert match_german_stop("aufhören") is True

        assert match_german_summary("german study summary") is True

        # Test dispatch
        res1 = handle_german_voice("German practice")
        assert "German Practice Session Activated" in res1
        assert is_german_mode_active() is True

        res2 = handle_german_voice("German quiz")
        assert "Schnelles Deutsch-Quiz" in res2

        res3 = handle_german_voice("stop German practice")
        assert "German Practice Session Ended" in res3
        assert is_german_mode_active() is False

    @patch("openai.OpenAI")
    def test_voice_input_transcribe_switches_whisper_language_param(self, mock_openai_class):
        from jarvis.voice_input import transcribe

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.audio.transcriptions.create.return_value = MagicMock(text="Guten Tag")

        # 1. When in English mode
        set_german_mode(False)
        transcribe(b"\x00\x00" * 8000)
        _, kwargs_en = mock_client.audio.transcriptions.create.call_args
        assert kwargs_en["language"] == "en"

        # 2. When in German practice mode
        set_german_mode(True)
        transcribe(b"\x00\x00" * 8000)
        _, kwargs_de = mock_client.audio.transcriptions.create.call_args
        assert kwargs_de["language"] == "de"
        assert "Deutsch auf B1-Niveau" in kwargs_de["prompt"]

        set_german_mode(False)


# ═════════════════════════════════════════════════════════════════════════════
# 3. TOOL REGISTRY & RISK TABLE TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestToolRegistryIntegration:

    def test_focus_and_german_tools_registered(self):
        expected_tools = [
            "start_focus_mode",
            "stop_focus_mode",
            "get_focus_summary",
            "start_german_practice",
            "stop_german_practice",
            "get_german_quiz",
            "get_german_study_summary",
        ]
        for t in expected_tools:
            assert t in TOOL_REGISTRY, f"Tool {t} must be in TOOL_REGISTRY"
            assert t in CENTRAL_TOOL_RISK_TABLE, f"Tool {t} must be in CENTRAL_TOOL_RISK_TABLE"
            assert CENTRAL_TOOL_RISK_TABLE[t] == RiskLevel.SAFE

        schemas = get_tool_schemas()
        schema_names = [s["function"]["name"] for s in schemas]
        for t in expected_tools:
            assert t in schema_names, f"Tool {t} must be in get_tool_schemas()"


# ═════════════════════════════════════════════════════════════════════════════
# 4. BRAIN INTEGRATION TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestBrainProcessTurnIntegration:

    def setup_method(self):
        stop_focus_mode()
        set_german_mode(False)

    def teardown_method(self):
        stop_focus_mode()
        set_german_mode(False)

    def test_brain_intercepts_focus_commands(self):
        from jarvis.brain import process_turn

        spoken = []
        res = process_turn(
            "focus mode for 45 minutes",
            conversation_history=[],
            speak_fn=spoken.append,
            stream_to_voice=False,
        )
        assert is_focus_active() is True
        assert "Focus Mode Activated" in res

        # Summary inquiry
        res_sum = process_turn(
            "how many focus sessions today",
            conversation_history=[],
            speak_fn=spoken.append,
            stream_to_voice=False,
        )
        assert "Focus Mode Summary" in res_sum

        # Stop command
        res_stop = process_turn(
            "stop focus mode",
            conversation_history=[],
            speak_fn=spoken.append,
            stream_to_voice=False,
        )
        assert is_focus_active() is False
        assert "Focus Mode Stopped" in res_stop

    @patch("openai.OpenAI")
    def test_brain_intercepts_german_session_lifecycle(self, mock_openai_class):
        from jarvis.brain import process_turn

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content="Sehr schön! Welche Programmiersprache magst du am liebsten?"
                )
            )
        ]
        mock_completion.usage = MagicMock(prompt_tokens=30, completion_tokens=20)
        mock_client.chat.completions.create.return_value = mock_completion

        history = []
        spoken = []

        # 1. Start German practice
        start_res = process_turn(
            "German practice",
            conversation_history=history,
            speak_fn=spoken.append,
            stream_to_voice=False,
        )
        assert is_german_mode_active() is True
        assert get_stt_language() == "de"
        assert "German Practice Session Activated" in start_res

        # 2. Conversational turn in German
        turn_res = process_turn(
            "Ich programmiere gern in Python.",
            conversation_history=history,
            speak_fn=spoken.append,
            stream_to_voice=False,
        )
        assert "Jarvis (B1 Deutsch)" in turn_res

        # 3. Request quiz
        quiz_res = process_turn(
            "German quiz",
            conversation_history=history,
            speak_fn=spoken.append,
            stream_to_voice=False,
        )
        assert "Schnelles Deutsch-Quiz" in quiz_res

        # 4. Stop German practice
        stop_res = process_turn(
            "stop German practice",
            conversation_history=history,
            speak_fn=spoken.append,
            stream_to_voice=False,
        )
        assert is_german_mode_active() is False
        assert get_stt_language() == "en"
        assert "German Practice Session Ended" in stop_res

