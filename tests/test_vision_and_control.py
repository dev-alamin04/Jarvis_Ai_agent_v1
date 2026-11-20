"""
tests/test_vision_and_control.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Test suite for Screen Vision & Computer Control in Jarvis:
  1. In-memory screen capture & disk privacy invariant
  2. Permission gate enforcement (safe vs dangerous)
  3. Mouse & keyboard automation tools
  4. File search & clipboard tools
  5. Browser tools
  6. Model router complexity keywords
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.permission_gate import check as gate_check, PermissionDenied
from jarvis.tools.vision import capture_screen_image, take_screenshot
from jarvis.tools.computer import (
    ensure_display_auth,
    click_at,
    type_text,
    press_hotkey,
    scroll_screen,
    is_sensitive_context,
)
from jarvis.tools.files import (
    search_files,
    move_files,
    read_clipboard,
    write_clipboard,
)
from jarvis.tools.browser import browser_open, browser_search, browser_fill_form
from jarvis.model_router import select_model


def test_permission_gate():
    print("[TEST] Permission Gate rules...")

    # 1. Safe tools must pass without raising
    safe_calls = [
        ("take_screenshot", {"prompt": "What is on screen?"}),
        ("fix_screen_error", {"extra_context": ""}),
        ("search_files", {"query": "test"}),
        ("read_clipboard", {}),
        ("write_clipboard", {"text": "hello"}),
        ("browser_open", {"url": "https://example.com"}),
        ("browser_search", {"query": "python"}),
        ("scroll_screen", {"clicks": 2, "direction": "down"}),
        ("type_text", {"text": "hello world"}),
        ("press_hotkey", {"keys": "ctrl+c"}),
        ("move_files", {"sources": ["/tmp/a.txt", "/tmp/b.txt"], "destination": "/tmp/dest"}),
        ("browser_fill_form", {"fields": {"name": "Alice"}, "submit": False}),
        ("click_at", {"x": 500, "y": 500}),
    ]

    for tool, args in safe_calls:
        try:
            gate_check(tool, args)
        except Exception as e:
            raise AssertionError(f"Expected safe tool `{tool}` to pass, but got: {e}")

    # 2. Dangerous calls must trigger gate (and raise PermissionDenied if denied)
    # Simulate user saying 'no'
    with patch("jarvis.permission_gate._ask_user", return_value=False):
        # Sensitive click: Bitwarden / password manager
        try:
            gate_check("click_element", {"description": "Click master password input in Bitwarden"})
            raise AssertionError("Should have blocked sensitive click in Bitwarden")
        except PermissionDenied:
            pass

        # Sensitive click: Banking
        try:
            gate_check("click_element", {"description": "Confirm bank transfer in Chase"})
            raise AssertionError("Should have blocked sensitive click in Chase banking")
        except PermissionDenied:
            pass

        # Sensitive click: Terminal running sudo
        try:
            gate_check("click_element", {"description": "Click in terminal running sudo"})
            raise AssertionError("Should have blocked sensitive click in sudo terminal")
        except PermissionDenied:
            pass

        # Bulk file move (> 3 files)
        try:
            gate_check("move_files", {
                "sources": ["/tmp/1.txt", "/tmp/2.txt", "/tmp/3.txt", "/tmp/4.txt"],
                "destination": "/tmp/dest"
            })
            raise AssertionError("Should have blocked moving 4 files without confirmation")
        except PermissionDenied:
            pass

        # Form submission
        try:
            gate_check("browser_fill_form", {
                "fields": {"email": "user@test.com"},
                "submit": True
            })
            raise AssertionError("Should have blocked form submission without confirmation")
        except PermissionDenied:
            pass

        # Deleting files
        try:
            gate_check("delete_file", {"path": "/tmp/a.txt"})
            raise AssertionError("Should have blocked delete_file")
        except PermissionDenied:
            pass

    print("  ✓ Permission Gate passed all safe and dangerous checks.")


def test_screen_vision_in_memory():
    print("[TEST] Screen Vision In-Memory capture & privacy...")
    img = capture_screen_image()
    assert img.width > 0 and img.height > 0, "Screenshot image must have valid dimensions"

    # Test take_screenshot with mocked OpenAI client
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="I see a desktop screen with code."))]
    mock_client.chat.completions.create.return_value = mock_resp

    with patch("jarvis.brain._get_client", return_value=mock_client):
        # By default, save_to_disk is False: verify no file written to default path
        default_file = Path.home() / "jarvis_screenshot.png"
        if default_file.exists():
            default_file.unlink()

        result = take_screenshot(prompt="Describe this")
        assert "desktop screen" in result
        assert not default_file.exists(), "Screenshot must NOT be written to disk when save_to_disk=False"

        # When explicitly requested:
        with tempfile.TemporaryDirectory() as tmpdir:
            explicit_path = Path(tmpdir) / "custom_shot.png"
            take_screenshot(prompt="Describe", save_to_disk=True, file_path=str(explicit_path))
            assert explicit_path.exists(), "Screenshot should be written when save_to_disk=True"

    print("  ✓ Screen vision captures in RAM and respects disk privacy invariant.")


def test_files_and_clipboard():
    print("[TEST] File tools and Clipboard...")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        p1 = Path(tmpdir) / "alpha.py"
        p2 = Path(tmpdir) / "beta.txt"
        p3 = Path(tmpdir) / "gamma.py"
        p1.write_text("def jarvis_magic(): return 42\n")
        p2.write_text("Hello Jarvis world\n")
        p3.write_text("print('test')\n")

        # 1. Search by name
        res_name = search_files("*.py", directory=tmpdir)
        assert "alpha.py" in res_name and "gamma.py" in res_name

        # 2. Search by content grep
        res_content = search_files("jarvis_magic", directory=tmpdir, search_content=True)
        assert "alpha.py" in res_content and "jarvis_magic" in res_content

        # 3. Move files
        dest_dir = Path(tmpdir) / "subfolder"
        res_move = move_files(sources=[str(p1), str(p2)], destination=str(dest_dir))
        assert (dest_dir / "alpha.py").exists()
        assert (dest_dir / "beta.txt").exists()
        assert "Successfully moved 2 item(s)" in res_move

    # 4. Clipboard read/write
    write_res = write_clipboard("Jarvis test payload 12345")
    assert "Copied 25 characters" in write_res
    read_res = read_clipboard()
    assert "Jarvis test payload 12345" in read_res

    print("  ✓ Files & clipboard tools function correctly.")


def test_computer_control():
    print("[TEST] Computer Control (Mouse & Keyboard)...")
    ensure_display_auth()

    # Hotkey test
    h_res = press_hotkey("ctrl+alt+t")
    assert "Pressed" in h_res

    # Scroll test
    s_res = scroll_screen(clicks=2, direction="down")
    assert "Scrolled down by 2" in s_res

    # Typing test
    t_res = type_text("Jarvis type test", press_enter=False)
    assert "Typed" in t_res

    # Click test
    c_res = click_at(x=100, y=100, clicks=1, button="left")
    assert "Clicked" in c_res

    print("  ✓ Computer control tools execute cleanly.")


def test_model_routing():
    print("[TEST] Model Routing for vision and control...")
    # Vision queries should route to strong model (gpt-4o)
    m1, r1 = select_model("Can you look at my screen and tell me what is there?")
    assert m1 == "gpt-4o", f"Expected gpt-4o for screen query, got {m1}"

    m2, r2 = select_model("fix this error on my screen")
    assert m2 == "gpt-4o", f"Expected gpt-4o for error query, got {m2}"

    m3, r3 = select_model("click the blue button")
    assert m3 == "gpt-4o", f"Expected gpt-4o for click query, got {m3}"

    # Simple command routes to fast model (gpt-4o-mini)
    m4, r4 = select_model("open terminal")
    assert m4 == "gpt-4o-mini", f"Expected gpt-4o-mini for simple app open, got {m4}"

    print("  ✓ Model router routes vision & GUI control to gpt-4o and simple commands to gpt-4o-mini.")


if __name__ == "__main__":
    print("\n════════════════════════════════════════════════════════════════════")
    print(" Running Jarvis Screen Vision & Computer Control Test Suite ")
    print("════════════════════════════════════════════════════════════════════\n")
    test_permission_gate()
    test_screen_vision_in_memory()
    test_files_and_clipboard()
    test_computer_control()
    test_model_routing()
    print("\n════════════════════════════════════════════════════════════════════")
    print(" ALL TESTS PASSED SUCCESSFULLY! ")
    print("════════════════════════════════════════════════════════════════════\n")
