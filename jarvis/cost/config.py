"""
jarvis/cost/config.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cost configuration loader and budget parameters.
Reads from config/cost_config.yaml with fallback defaults and environment overrides.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml

from jarvis.logger import logger

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
COST_CONFIG_PATH = PROJECT_ROOT / "config" / "cost_config.yaml"

# Default rates (USD per million tokens, per minute, or per million characters)
_DEFAULT_RATES: dict[str, dict[str, float]] = {
    "gpt-4o": {
        "prompt_per_million": 2.50,
        "completion_per_million": 10.00,
    },
    "gpt-4o-mini": {
        "prompt_per_million": 0.15,
        "completion_per_million": 0.60,
    },
    "gpt-4-turbo": {
        "prompt_per_million": 10.00,
        "completion_per_million": 30.00,
    },
    "gpt-3.5-turbo": {
        "prompt_per_million": 0.50,
        "completion_per_million": 1.50,
    },
    "whisper-1": {
        "per_minute": 0.006,
    },
    "tts-1": {
        "per_million_chars": 15.00,
    },
    "tts-1-hd": {
        "per_million_chars": 30.00,
    },
}

_DEFAULT_EXPENSIVE_TOOLS = [
    "take_screenshot",
    "fix_screen_error",
    "describe_screen",
    "recon_full_scan",
    "server_deploy",
    "laravel_debug_and_fix",
]


def load_cost_config() -> dict[str, Any]:
    """Load configuration from config/cost_config.yaml with safe defaults."""
    if COST_CONFIG_PATH.exists():
        try:
            with open(COST_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return data.get("cost", {})
        except Exception as exc:
            logger.warning(f"[Cost Config] Error reading {COST_CONFIG_PATH}: {exc}")
    return {}


def get_daily_limit() -> float:
    """Return daily budget limit in USD."""
    env_val = os.environ.get("JARVIS_DAILY_LIMIT_USD")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    cfg = load_cost_config()
    return float(cfg.get("daily_limit_usd", 1.00))


def get_monthly_limit() -> float:
    """Return monthly budget limit in USD."""
    env_val = os.environ.get("JARVIS_MONTHLY_LIMIT_USD")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    cfg = load_cost_config()
    return float(cfg.get("monthly_limit_usd", 30.00))


def get_warning_threshold() -> float:
    """Ratio at which Jarvis warns by voice (default 0.80 = 80%)."""
    cfg = load_cost_config()
    return float(cfg.get("warning_threshold", 0.80))


def get_hard_limit_threshold() -> float:
    """Ratio at which Jarvis switches model and gates actions (default 1.00 = 100%)."""
    cfg = load_cost_config()
    return float(cfg.get("hard_limit_threshold", 1.00))


def get_cheaper_model() -> str:
    """Model to downgrade to when spending limit is reached."""
    cfg = load_cost_config()
    return str(cfg.get("cheaper_model", "gpt-4o-mini"))


def get_rates() -> dict[str, dict[str, float]]:
    """Return pricing rate table."""
    cfg = load_cost_config()
    rates = dict(_DEFAULT_RATES)
    if "rates" in cfg and isinstance(cfg["rates"], dict):
        rates.update(cfg["rates"])
    return rates


def get_expensive_tools() -> list[str]:
    """Return list of expensive tool names."""
    cfg = load_cost_config()
    tools = cfg.get("expensive_tools")
    if isinstance(tools, list):
        return [str(t) for t in tools]
    return list(_DEFAULT_EXPENSIVE_TOOLS)
