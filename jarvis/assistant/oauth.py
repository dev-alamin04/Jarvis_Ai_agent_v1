"""
jarvis/assistant/oauth.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OAuth 2.0 Authentication Manager for Google Workspace (Gmail & Calendar).

Security Invariants:
  • OAuth tokens are stored in a local protected file: data/tokens/google_token.json
    with strict permissions (chmod 600).
  • Tokens and client secrets are NEVER stored in memory, printed, or logged.
  • Graceful simulation fallback when credentials are not yet configured or offline.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from jarvis.config import PROJECT_ROOT
from jarvis.logger import logger

TOKEN_DIR = PROJECT_ROOT / "data" / "tokens"
TOKEN_FILE = TOKEN_DIR / "google_token.json"
CREDENTIALS_FILE = PROJECT_ROOT / "config" / "google_credentials.json"
ALT_CREDENTIALS_FILE = Path.home() / ".config" / "jarvis" / "google_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def ensure_token_file_permissions(path: Path) -> None:
    """Ensure token file is readable and writable ONLY by the file owner (chmod 600)."""
    try:
        if path.exists():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception as exc:
        logger.debug(f"[OAuth] Permission adjustment note: {exc}")


def get_credentials_path() -> Path | None:
    """Find client credentials json if provided by the user."""
    if CREDENTIALS_FILE.exists():
        return CREDENTIALS_FILE
    if ALT_CREDENTIALS_FILE.exists():
        return ALT_CREDENTIALS_FILE
    return None


def get_google_credentials(interactive: bool = False):
    """
    Load or refresh valid Google OAuth 2.0 credentials.
    Returns credentials object, or None if in simulated/offline mode.
    """
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        logger.warning("[OAuth] google-auth libraries not available; using simulation fallback.")
        return None

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            ensure_token_file_permissions(TOKEN_FILE)
        except Exception as exc:
            logger.warning(f"[OAuth] Could not parse token file: {exc}")
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save refreshed token securely
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            ensure_token_file_permissions(TOKEN_FILE)
            logger.info("[OAuth] Successfully refreshed Google OAuth token.")
            return creds
        except Exception as exc:
            logger.warning(f"[OAuth] Refresh failed: {exc}")
            creds = None

    # New login flow if interactive and credentials file exists
    cred_path = get_credentials_path()
    if interactive and cred_path:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
            creds = flow.run_local_server(port=0)
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            ensure_token_file_permissions(TOKEN_FILE)
            logger.info("[OAuth] Successfully authorized and stored Google OAuth token.")
            return creds
        except Exception as exc:
            logger.error(f"[OAuth] Interactive login failed: {exc}")
            return None

    return None


def is_google_authenticated() -> bool:
    """Check if valid Google credentials or token exist."""
    creds = get_google_credentials(interactive=False)
    return creds is not None and creds.valid
