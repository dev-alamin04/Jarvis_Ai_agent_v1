"""
tests/test_messaging.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Test suite for Jarvis Unified Messaging Tool:
  1. Permission gate mandatory confirmation & custom prompt readback
  2. Privacy rules: Zero message text logged in actions or audit logs
  3. Daily rate limiting (20/day) & persistence
  4. Adapter architecture & multi-platform registration
  5. Contact search & disambiguation (never guess similar names)
  6. Tool schema validation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.messaging.base import BaseMessagingAdapter, ContactSearchResult
from jarvis.messaging.manager import MessagingManager, messaging_manager
from jarvis.messaging.rate_limiter import (
    can_send,
    get_daily_limit,
    get_today_count,
    log_audit,
    record_send,
)
from jarvis.permission_gate import (
    PermissionDenied,
    _scrub,
    check as gate_check,
)
from jarvis.tools.registry import TOOL_REGISTRY, get_tool_schemas


def test_permission_gate_mandatory_readback():
    print("[TEST] Permission Gate mandatory readback & confirmation...")

    args = {
        "platform": "whatsapp",
        "person_name": "Rahim Uddin",
        "text": "I will call you tonight",
    }

    spoken_prompts = []

    def mock_speak(prompt_text):
        spoken_prompts.append(prompt_text)

    # 1. Test when user denies
    with patch("jarvis.permission_gate._ask_user", return_value=False):
        try:
            gate_check("send_message", args, speak_fn=mock_speak)
            raise AssertionError("send_message must require confirmation and raise PermissionDenied when rejected!")
        except PermissionDenied:
            pass

    # Verify exact prompt format required by user:
    # "Send on WhatsApp to Rahim Uddin: I will call you tonight. Shall I send?"
    assert len(spoken_prompts) > 0, "Gate must speak the confirmation prompt aloud"
    expected_prompt = "Send on WhatsApp to Rahim Uddin: I will call you tonight. Shall I send?"
    assert spoken_prompts[0] == expected_prompt, f"Expected prompt '{expected_prompt}', got '{spoken_prompts[0]}'"

    # 2. Test when user approves
    with patch("jarvis.permission_gate._ask_user", return_value=True):
        # Should not raise
        gate_check("send_message", args, speak_fn=mock_speak)

    # 3. Privacy check: verify message text is scrubbed from logging args
    scrubbed = _scrub(args)
    assert scrubbed["text"] == "<23 chars>", f"Expected scrubbed length string, got: {scrubbed['text']}"
    assert "I will call you tonight" not in str(scrubbed), "Message text must NEVER be in logged args"

    print("  ✓ Permission gate enforces exact spoken readback and scrubs private message text.")


def test_rate_limiter_and_audit_logging():
    print("[TEST] Rate limiter and privacy-preserving audit logging...")

    with tempfile.TemporaryDirectory() as tmpdir:
        test_limits_file = Path(tmpdir) / "message_limits.json"
        test_audit_file = Path(tmpdir) / "messaging_audit.log"

        with patch("jarvis.messaging.rate_limiter._LIMITS_FILE", test_limits_file), \
             patch("jarvis.messaging.rate_limiter._AUDIT_LOG_FILE", test_audit_file), \
             patch("jarvis.messaging.rate_limiter.get_daily_limit", return_value=3):

            # Initial count is 0
            assert get_today_count("whatsapp") == 0
            ok, _ = can_send("whatsapp")
            assert ok is True

            # Send 3 messages
            record_send("whatsapp")
            record_send("whatsapp")
            record_send("whatsapp")
            assert get_today_count("whatsapp") == 3

            # 4th message must be blocked
            ok, reason = can_send("whatsapp")
            assert ok is False
            assert "Daily message limit of 3 for Whatsapp reached today" in reason

            # Audit log check
            private_message = "My super secret financial transfer code 998811"
            log_audit("whatsapp", "Rahim Uddin", private_message, status="SENT")

            audit_content = test_audit_file.read_text(encoding="utf-8")
            assert "PLATFORM: whatsapp" in audit_content
            assert "RECIPIENT: Rahim Uddin" in audit_content
            assert f"LENGTH: {len(private_message)} chars" in audit_content
            assert private_message not in audit_content, "Audit log must NEVER contain the message content"

    print("  ✓ Daily rate limiting and privacy-preserving audit log verified.")


def test_adapter_architecture_and_aliases():
    print("[TEST] Adapter architecture & multi-platform aliases...")

    mgr = MessagingManager()

    # Test standard platforms
    assert mgr.get_adapter("whatsapp") is not None
    assert mgr.get_adapter("telegram") is not None
    assert mgr.get_adapter("messenger") is not None

    # Test aliases
    assert mgr.get_adapter("wa").name == "whatsapp"
    assert mgr.get_adapter("tg").name == "telegram"
    assert mgr.get_adapter("fb").name == "messenger"
    assert mgr.get_adapter("facebook messenger").name == "messenger"

    # Test adding a custom adapter easily
    class SignalAdapter(BaseMessagingAdapter):
        name = "signal"
        display_name = "Signal"
        base_url = "https://signal.org"
        def check_login_state(self, page): return True, "Logged in"
        def search_contact(self, page, name): return ContactSearchResult(status="exact", contacts=[name])
        def select_contact(self, page, name): return True
        def send(self, page, text): return True
        def verify_sent(self, page, text): return True

    mgr.register_adapter(SignalAdapter)
    assert mgr.get_adapter("signal") is not None
    assert mgr.get_adapter("signal").display_name == "Signal"

    print("  ✓ Adapter registry, aliases, and extensibility verified.")


def test_disambiguation_and_flow():
    print("[TEST] Contact disambiguation & missing parameters...")

    mgr = MessagingManager()

    # 1. Missing platform asks user
    res1 = mgr.send_message(platform="", person_name="Rahim", text="Hello")
    assert "Which platform would you like" in res1

    # 2. Mock adapter with multiple matches (never guess between similar names)
    class MockWhatsApp(BaseMessagingAdapter):
        name = "mock_wa"
        display_name = "MockWhatsApp"
        def open(self, headless=None): return MagicMock()
        def check_login_state(self, page): return True, "Logged in"
        def search_contact(self, page, name):
            return ContactSearchResult(
                status="multiple",
                contacts=["Rahim Uddin", "Rahim Khan"],
                message="I found multiple contacts matching 'Rahim': Rahim Uddin, Rahim Khan. Which one should I message?"
            )
        def select_contact(self, page, name): return True
        def send(self, page, text): return True
        def verify_sent(self, page, text): return True

    mgr.register_adapter(MockWhatsApp)
    res_ambiguous = mgr.send_message(platform="mock_wa", person_name="Rahim", text="Call me")
    assert "I found multiple contacts matching 'Rahim'" in res_ambiguous
    assert "Rahim Uddin" in res_ambiguous and "Rahim Khan" in res_ambiguous

    # 3. Successful flow with verification
    class MockTelegram(BaseMessagingAdapter):
        name = "mock_tg"
        display_name = "MockTelegram"
        def open(self, headless=None): return MagicMock()
        def check_login_state(self, page): return True, "Logged in"
        def search_contact(self, page, name):
            return ContactSearchResult(status="exact", contacts=[name])
        def select_contact(self, page, name): return True
        def send(self, page, text): return True
        def verify_sent(self, page, text): return True

    mgr.register_adapter(MockTelegram)
    res_success = mgr.send_message(platform="mock_tg", person_name="John Doe", text="Hello John")
    assert "Message sent on MockTelegram to John Doe and verified." in res_success

    print("  ✓ Contact disambiguation and full flow verified.")


def test_tool_registry():
    print("[TEST] Tool registry schema for send_message...")

    assert "send_message" in TOOL_REGISTRY, "send_message must be in TOOL_REGISTRY"

    schemas = get_tool_schemas()
    msg_schema = next((s for s in schemas if s["function"]["name"] == "send_message"), None)
    assert msg_schema is not None, "send_message schema missing from get_tool_schemas()"

    props = msg_schema["function"]["parameters"]["properties"]
    assert "platform" in props
    assert "person_name" in props
    assert "text" in props
    assert set(msg_schema["function"]["parameters"]["required"]) == {"platform", "person_name", "text"}

    print("  ✓ Tool registry schema verified.")


if __name__ == "__main__":
    print("\n════════════════════════════════════════════════════════════════════")
    print(" Running Jarvis Unified Messaging Test Suite ")
    print("════════════════════════════════════════════════════════════════════\n")
    test_permission_gate_mandatory_readback()
    test_rate_limiter_and_audit_logging()
    test_adapter_architecture_and_aliases()
    test_disambiguation_and_flow()
    test_tool_registry()
    print("\n════════════════════════════════════════════════════════════════════")
    print(" ALL MESSAGING TESTS PASSED SUCCESSFULLY! ")
    print("════════════════════════════════════════════════════════════════════\n")
