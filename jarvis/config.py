"""
jarvis/config.py
Loads and exposes the YAML configuration. All modules import from here.
"""

import os
from pathlib import Path
import yaml

# Root of the project (one level above this file)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def _load() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


_cfg: dict = _load()


def get(key_path: str, default=None):
    """
    Dot-separated key access, e.g. get("openai.model").
    """
    keys = key_path.split(".")
    node = _cfg
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
        if node is None:
            return default
    return node


def reload():
    """Re-read config from disk (useful after self-update)."""
    global _cfg
    _cfg = _load()


# Convenience accessors -------------------------------------------------

OPENAI_MODEL: str = get("openai.model", "gpt-4o")
TRANSCRIPTION_MODEL: str = get("openai.transcription_model", "whisper-1")
TTS_MODEL: str = get("openai.tts_model", "tts-1")
TTS_VOICE: str = get("openai.tts_voice", "echo")
MAX_TOOL_ITERATIONS: int = get("openai.max_tool_iterations", 6)

ACTION_LOG: Path = PROJECT_ROOT / get("logging.action_log", "logs/actions.log")
SELF_REVIEW_LOG: Path = PROJECT_ROOT / get("logging.self_review_log", "logs/self_review.log")
LOG_LEVEL: str = get("logging.level", "INFO")

PROTECTED_PATHS: list[str] = get("protected_paths") or []
PROJECTS: dict = get("projects") or {}
APPS: dict = get("apps") or {}
HOTKEY_PTT: str = get("hotkey.push_to_talk", "ctrl+shift+space")

GIT_BACKUP_PREFIX: str = get("git.backup_branch_prefix", "jarvis-backup")
GIT_CANDIDATE: str = get("git.candidate_branch", "candidate")
GIT_STABLE: str = get("git.stable_branch", "stable")
