"""
jarvis/tools/vision.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Screen Vision Tools.

Provides:
  • take_screenshot: captures the screen or active window in RAM, sends it
    to OpenAI vision (gpt-4o) to describe content, read errors, or locate UI elements.
    PRIVACY INVARIANT: Never saved to disk unless explicitly requested by the user,
    and never sent anywhere except the OpenAI model call for that command.
  • locate_element: internal helper for click_element that finds pixel coordinates.
  • fix_screen_error: analyzes an error visible on screen, locates the code, and
    proposes a concrete fix.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path
from typing import Any

import mss
from PIL import Image

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger


def _ensure_display_env():
    """Ensure DISPLAY and mutter auth cookie are set up for Xwayland/X11."""
    try:
        from jarvis.tools.computer import ensure_display_auth
        ensure_display_auth()
    except Exception:
        pass


def _track_vision_usage(response: Any, model: str = "gpt-4o") -> None:
    """Record token usage and estimated cost for vision model calls."""
    try:
        if hasattr(response, "usage") and response.usage:
            from jarvis.cost.tracker import track_model_call
            track_model_call(
                model=model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
    except Exception:
        pass


def capture_screen_image(target: str = "screen", region: dict | None = None) -> Image.Image:
    """
    Capture the screen or a region into a PIL Image in memory.
    Never touches disk.
    """
    _ensure_display_env()

    with mss.MSS() as sct:
        if region:
            # region dict: {"top": int, "left": int, "width": int, "height": int}
            shot = sct.grab(region)
        elif target == "window":
            # Attempt to get active window geometry if possible
            geom = None
            try:
                from jarvis.tools.computer import get_active_window_geometry
                geom = get_active_window_geometry()
            except Exception:
                pass

            if geom:
                shot = sct.grab(geom)
            else:
                # Default to full screen if window geom unavailable
                shot = sct.grab(sct.monitors[0])
        else:
            # Default to full screen (monitor 0 = all monitors, monitor 1 = primary)
            shot = sct.grab(sct.monitors[0] if len(sct.monitors) > 0 else sct.monitors[1])

        # Convert raw BGRA bytes into PIL RGB Image in memory
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img


def _image_to_base64_png(img: Image.Image) -> str:
    """Encode PIL Image to base64 PNG in memory."""
    buf = io.BytesIO()
    try:
        # Resize if enormous to save latency/tokens while keeping detail
        max_dim = 1920
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    finally:
        buf.close()


def take_screenshot(
    prompt: str = "Describe what is currently visible on the screen in detail.",
    target: str = "screen",
    save_to_disk: bool = False,
    file_path: str | None = None,
) -> str:
    """
    Capture the screen (or active window) and send it to the vision model (gpt-4o).

    Privacy: Never saved to disk unless save_to_disk is True.
    Never sent anywhere except the OpenAI API call.

    Parameters
    ----------
    prompt : str
        What to look for or analyze (e.g. "What error is on screen?", "Describe the window").
    target : str
        "screen" for entire desktop, or "window" for active window.
    save_to_disk : bool
        If True, save the image file to disk (only when user explicitly requests).
    file_path : str | None
        Destination path if save_to_disk is True (defaults to ~/jarvis_screenshot.png).
    """
    logger.info(f"take_screenshot: target={target}, save_to_disk={save_to_disk}")

    try:
        img = capture_screen_image(target=target)
    except Exception as exc:
        logger.error(f"Failed to capture screen: {exc}")
        return f"Failed to capture screenshot: {exc}"

    # Only save to disk if user explicitly asked
    if save_to_disk:
        dest = Path(file_path).expanduser().resolve() if file_path else Path.home() / "jarvis_screenshot.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
        logger.info(f"Screenshot explicitly saved to {dest}")

    # Convert to in-memory base64 PNG
    b64_png = _image_to_base64_png(img)

    # Call OpenAI vision model
    from jarvis.brain import _get_client
    client = _get_client()

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_png}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=600,
        )
        _track_vision_usage(response, model="gpt-4o")
        return response.choices[0].message.content or "(no response from vision model)"
    except Exception as exc:
        logger.error(f"Vision API error: {exc}")
        return f"Error analyzing screenshot with vision model: {exc}"


def locate_element(description: str) -> dict[str, Any]:
    """
    Take an in-memory screenshot and use gpt-4o to find the pixel coordinate of a UI element.

    Returns dict:
      {"found": bool, "x": int, "y": int, "label": str}
    """
    logger.info(f"locate_element: searching for '{description}'")

    img = capture_screen_image(target="screen")
    width, height = img.size
    b64_png = _image_to_base64_png(img)

    from jarvis.brain import _get_client
    client = _get_client()

    prompt = (
        f"You are a computer vision assistant. The attached screenshot has resolution {width}x{height} pixels.\n"
        f"Locate the UI element described as: '{description}'.\n"
        f"Return ONLY a JSON object (no markdown, no backticks) with this structure:\n"
        f'{{"found": true, "x": <int_center_x>, "y": <int_center_y>, "label": "<element_label>"}}\n'
        f'If the element is not visible or cannot be found, return:\n'
        f'{{"found": false, "x": 0, "y": 0, "label": ""}}'
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_png}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=200,
        )
        _track_vision_usage(response, model="gpt-4o")
        content = (response.choices[0].message.content or "").strip()
        # Clean json backticks if any
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
        content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
        return data
    except Exception as exc:
        logger.error(f"locate_element failed: {exc}")
        return {"found": False, "x": 0, "y": 0, "label": "", "error": str(exc)}


def fix_screen_error(extra_context: str = "") -> str:
    """
    When the user says 'fix this error' with an error on screen:
      1. Takes in-memory screenshot.
      2. Reads and parses the error, stack trace, and file paths.
      3. Finds the related local source code and inspects it.
      4. Formulates a concrete diagnosis and code fix.
    """
    logger.info("fix_screen_error: analyzing visible screen error")

    img = capture_screen_image(target="screen")
    b64_png = _image_to_base64_png(img)

    from jarvis.brain import _get_client
    client = _get_client()

    prompt = (
        "An error, exception, or traceback is currently displayed on screen.\n"
        f"Additional context: {extra_context}\n\n"
        "Analyze the error carefully. Extract the exact error message, file paths, line numbers, "
        "and determine what caused the failure. Return ONLY a JSON object with this format:\n"
        "{\n"
        '  "error_title": "Short title or exception name",\n'
        '  "details": "Summary of what failed",\n'
        '  "files": [\n'
        '    {"file_path": "/path/or/filename.ext", "line": 42}\n'
        '  ],\n'
        '  "root_cause": "Explanation of why the error happened",\n'
        '  "proposed_fix": "Concrete code fix or command to resolve it"\n'
        "}\n"
        "Return ONLY the JSON object."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_png}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=800,
        )
        _track_vision_usage(response, model="gpt-4o")
        content = (response.choices[0].message.content or "").strip()
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
        content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
    except Exception as exc:
        logger.error(f"Error parsing screen error: {exc}")
        return f"Unable to analyze error from screen: {exc}"

    error_title = data.get("error_title", "Error")
    details = data.get("details", "")
    root_cause = data.get("root_cause", "")
    proposed_fix = data.get("proposed_fix", "")
    files = data.get("files", [])

    code_context = ""
    # Try reading the referenced files from local filesystem
    from jarvis.tools.files import search_files
    for item in files:
        fpath_str = item.get("file_path", "")
        line_num = item.get("line")
        if not fpath_str:
            continue

        resolved = Path(fpath_str).expanduser()
        if not resolved.exists():
            # Search project files by filename
            fname = Path(fpath_str).name
            search_res = search_files(fname, max_results=1)
            for line in search_res.splitlines():
                if fname in line:
                    cand = Path(line.split()[0]).expanduser().resolve()
                    if cand.exists():
                        resolved = cand
                        break

        if resolved.exists() and resolved.is_file():
            try:
                lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
                total = len(lines)
                if line_num and isinstance(line_num, int) and 1 <= line_num <= total:
                    start = max(0, line_num - 10)
                    end = min(total, line_num + 10)
                    snippet = "\n".join(f"{i+1:4d} | {lines[i]}" for i in range(start, end))
                    code_context += f"\nFile: {resolved} (lines {start+1}-{end}):\n{snippet}\n"
                else:
                    snippet = "\n".join(f"{i+1:4d} | {lines[i]}" for i in range(min(total, 30)))
                    code_context += f"\nFile: {resolved} (top lines):\n{snippet}\n"
            except Exception as e:
                logger.warning(f"Could not read local file {resolved}: {e}")

    # Build clear response
    result_lines = [
        f"**Error Identified**: {error_title}",
        f"**Details**: {details}",
        f"**Root Cause**: {root_cause}",
    ]
    if code_context:
        result_lines.append(f"**Code Context**:\n```\n{code_context.strip()}\n```")
    result_lines.append(f"**Proposed Fix**:\n{proposed_fix}")

    return "\n\n".join(result_lines)
