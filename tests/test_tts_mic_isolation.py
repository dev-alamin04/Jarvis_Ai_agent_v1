"""
tests/test_tts_mic_isolation.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unit tests for TTS microphone isolation bug fix:
  1. audio_state.speaking set for whole TTS playback including queued sentences
  2. Mic audio dropped until playback ends plus a 0.7 second tail
  3. PCM queue flushed after speaking
  4. Transcriptions shorter than 2 words or empty are ignored
  5. Confirmations (approve, yes, merge) arriving while speaking are never accepted
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import queue
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

os.environ["JARVIS_TEST_MODE"] = "1"
os.environ["OPENAI_API_KEY"] = "sk-test-key-for-tts-mic-isolation"

from jarvis import audio_state
from jarvis.streaming_tts import StreamingTTSPlayer
from jarvis.voice_agent import _on_command_received
from jarvis.voice_input import transcribe
from jarvis.voice_output import speak
from jarvis.wake_word import WakeWordListener
import jarvis.permission_gate as pg


class TestTTSMicIsolation:

    def setup_method(self):
        audio_state.speaking.clear()
        audio_state.interrupted.clear()
        audio_state.muted.clear()
        audio_state.last_spoke_time = 0.0

    def teardown_method(self):
        audio_state.speaking.clear()
        audio_state.interrupted.clear()
        audio_state.muted.clear()
        audio_state.last_spoke_time = 0.0

    # ── 1. audio_state.speaking set for whole TTS playback including queued sentences ──
    @patch("openai.OpenAI")
    @patch("sounddevice.OutputStream")
    def test_speak_sets_speaking_flag_for_entire_duration(self, mock_sd_stream, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.audio.speech.create.return_value = MagicMock(content=b"\x00\x00" * 4800)

        speaking_states = []

        class DummyStream:
            def __enter__(self):
                speaking_states.append(audio_state.speaking.is_set())
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                speaking_states.append(audio_state.speaking.is_set())
            def write(self, chunk):
                speaking_states.append(audio_state.speaking.is_set())

        mock_sd_stream.return_value = DummyStream()

        speak("Hello, this is a test speech output.")

        # speaking should have been True while stream was active and writing
        assert all(speaking_states), f"speaking was not set during playback: {speaking_states}"
        # after speak finishes, speaking is cleared and last_spoke_time is recorded
        assert not audio_state.speaking.is_set()
        assert audio_state.last_spoke_time > 0.0

    @patch("openai.OpenAI")
    @patch("sounddevice.OutputStream")
    def test_streaming_tts_speaking_set_throughout_queued_sentences(self, mock_sd_stream, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.audio.speech.create.return_value = MagicMock(content=b"\x00\x00" * 2400)

        chunks_played = []

        class DummyStream:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                pass
            def write(self, chunk):
                chunks_played.append(audio_state.speaking.is_set())
                time.sleep(0.01)

        mock_sd_stream.return_value = DummyStream()

        player = StreamingTTSPlayer(client=mock_client)
        player.start()
        assert audio_state.speaking.is_set()

        player.feed_sentence("First queued sentence.")
        player.feed_sentence("Second queued sentence.")
        assert audio_state.speaking.is_set()

        player.finish()
        assert len(chunks_played) >= 2
        assert all(chunks_played), "speaking flag dropped while queued sentences were playing"
        assert not audio_state.speaking.is_set()
        assert audio_state.last_spoke_time > 0.0

    # ── 2. Drop all mic audio until playback ends plus a 0.7 second tail ──
    def test_mic_audio_dropped_while_speaking_and_during_tail(self):
        listener = WakeWordListener(on_wake=lambda pcm: None)
        dummy_audio = np.zeros(1280, dtype=np.int16)

        # Case A: Normal (idle) → audio queued
        listener.flush_pcm_queue()
        audio_state.speaking.clear()
        audio_state.last_spoke_time = 0.0
        listener._audio_callback(dummy_audio, 1280, None, None)
        assert not listener._pcm_queue.empty()

        # Case B: While speaking → audio MUST be dropped
        listener.flush_pcm_queue()
        audio_state.speaking.set()
        listener._audio_callback(dummy_audio, 1280, None, None)
        assert listener._pcm_queue.empty(), "Mic audio was not dropped while speaking"

        # Case C: Immediately after speaking ends (within 0.7s tail) → audio MUST be dropped
        listener.flush_pcm_queue()
        audio_state.speaking.clear()
        audio_state.last_spoke_time = time.time()  # 0s elapsed (< 0.7s)
        assert audio_state.is_speaking(tail_s=0.7) is True

        listener._audio_callback(dummy_audio, 1280, None, None)
        assert listener._pcm_queue.empty(), "Mic audio was not dropped during 0.7s tail"

        # Case D: After 0.7s tail has elapsed → audio accepted again
        audio_state.last_spoke_time = time.time() - 0.75  # 0.75s elapsed (> 0.7s)
        assert audio_state.is_speaking(tail_s=0.7) is False

        listener._audio_callback(dummy_audio, 1280, None, None)
        assert not listener._pcm_queue.empty(), "Mic audio was not accepted after 0.7s tail"

    # ── 3. Flush the PCM queue after speaking ──
    def test_pcm_queue_flushed_after_speaking(self):
        listener = WakeWordListener(on_wake=lambda pcm: None)
        audio_state.register_flush_callback(listener.flush_pcm_queue)

        # Fill queue with some dummy audio
        listener._pcm_queue.put(b"\x00\x00" * 100)
        listener._pcm_queue.put(b"\x00\x00" * 100)
        assert not listener._pcm_queue.empty()

        # Call flush_all_pcm
        audio_state.flush_all_pcm()
        assert listener._pcm_queue.empty(), "PCM queue was not flushed"

    # ── 4. Ignore any transcription shorter than 2 words or empty ──
    @patch("openai.OpenAI")
    def test_ignore_transcriptions_shorter_than_two_words(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # 1 word: 'module.'
        mock_client.audio.transcriptions.create.return_value = MagicMock(text="module.")
        res1 = transcribe(b"\x00\x00" * 8000, min_words=2)
        assert res1 == "", f"Expected empty string for 1 word transcription, got: {res1!r}"

        # Empty: ''
        mock_client.audio.transcriptions.create.return_value = MagicMock(text="")
        res2 = transcribe(b"\x00\x00" * 8000, min_words=2)
        assert res2 == "", f"Expected empty string for empty transcription, got: {res2!r}"

        # 2 words: 'Streaming audio.'
        mock_client.audio.transcriptions.create.return_value = MagicMock(text="Streaming audio.")
        res3 = transcribe(b"\x00\x00" * 8000, min_words=2)
        assert res3 == "Streaming audio."

    @patch("jarvis.voice_agent.transcribe")
    @patch("jarvis.voice_agent.process_turn")
    @patch("jarvis.voice_agent.speak")
    def test_voice_agent_ignores_short_or_empty_transcription(self, mock_speak, mock_brain, mock_stt):
        mock_stt.return_value = "hello"  # 1 word

        _on_command_received(b"\x00\x00" * 8000)

        # Brain should NOT be called
        mock_brain.assert_not_called()
        # Should not even speak "Sorry, I didn't catch that"
        mock_speak.assert_not_called()

        mock_stt.return_value = ""  # empty
        _on_command_received(b"\x00\x00" * 8000)
        mock_brain.assert_not_called()
        mock_speak.assert_not_called()

    # ── 5. Never accept approve, yes, or merge confirmations while speaking ──
    def test_never_accept_confirmations_while_speaking(self):
        # When agent is speaking, _safe_ask_user must refuse immediately
        audio_state.speaking.set()
        assert pg._ask_user("Do you approve merging this candidate?") is False

        # Even within 0.7s tail after speaking ends
        audio_state.speaking.clear()
        audio_state.last_spoke_time = time.time()
        assert pg._ask_user("Do you approve merging this candidate?") is False

        # When speaking has ended (> 0.7s ago), original ask_user is permitted
        audio_state.last_spoke_time = time.time() - 1.0
        with patch.object(pg, "_original_ask_user", return_value=True) as mock_orig:
            assert pg._ask_user("Do you approve merging this candidate?") is True
            mock_orig.assert_called_once()

    @patch("jarvis.voice_agent.transcribe")
    @patch("jarvis.voice_agent.process_turn")
    def test_voice_agent_rejects_confirmation_commands_while_speaking(self, mock_brain, mock_stt):
        # If user command arrived with confirmation words while speaking
        audio_state.speaking.set()
        for confirm_phrase in ["yes", "approve", "merge", "yes approve", "merge candidate"]:
            mock_stt.return_value = confirm_phrase
            _on_command_received(b"\x00\x00" * 8000)
            mock_brain.assert_not_called()

        # Also during tail
        audio_state.speaking.clear()
        audio_state.last_spoke_time = time.time()
        mock_stt.return_value = "yes I approve"
        _on_command_received(b"\x00\x00" * 8000)
        mock_brain.assert_not_called()
