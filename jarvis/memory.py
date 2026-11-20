"""
jarvis/memory.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Persistent Memory and Context Management for Jarvis.

Features:
  1. ShortTermMemory:
     • Retains recent conversation turns for a configurable TTL (default 180s / 3 mins).
     • Enables natural follow-ups like "play it again" or "the other one".
     • Resets automatically if idle time exceeds TTL.
  2. LongTermMemory:
     • Local SQLite database (`data/memory.db`).
     • Stores facts: project names/paths, preferred apps, server names, custom notes.
     • Per-project context: active project, path, type (Laravel, Flutter, Python, etc.),
       and recently executed commands.
     • Intelligent context extraction: injects ONLY relevant memories into the prompt.
  3. Security & Privacy:
     • Robust regex filtering scrubs API keys, tokens, passwords, and secrets before
       they can ever be saved into memory.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis import config
from jarvis.config import PROJECT_ROOT, get
from jarvis.logger import logger

# ── Config defaults ───────────────────────────────────────────────────────────
_DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "memory.db"
_DEFAULT_TTL_SECONDS = 180  # 3 minutes
_DEFAULT_MAX_TURNS = 10     # Max short-term turns (pairs of user/assistant exchanges)


# ── Secret Filter ─────────────────────────────────────────────────────────────

# Patterns matching sensitive credentials
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}", re.IGNORECASE),                         # OpenAI style keys
    re.compile(r"AIza[0-9A-Za-z-_]{35}", re.IGNORECASE),                        # Google API keys
    re.compile(r"gh[pousr]-[A-Za-z0-9_]{36,}", re.IGNORECASE),                  # GitHub tokens
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE),               # Bearer tokens
    re.compile(r"(api[_-]?key|password|token|secret|auth)\s*[:=]\s*['\"]?[^\s,'\"]{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|DSA|PGP)? PRIVATE KEY-----", re.IGNORECASE),
]


def scrub_secrets(text: str) -> tuple[str, bool]:
    """
    Remove secrets, passwords, and tokens from text.
    Returns (cleaned_text, had_secrets).
    """
    cleaned = text
    had_secrets = False
    for pat in _SECRET_PATTERNS:
        if pat.search(cleaned):
            had_secrets = True
            cleaned = pat.sub("[REDACTED_SECRET]", cleaned)
    return cleaned, had_secrets


def is_pure_secret(text: str) -> bool:
    """Check if the given string is primarily an API key or password."""
    t = text.strip()
    for pat in _SECRET_PATTERNS:
        m = pat.search(t)
        if m and (len(m.group(0)) >= len(t) * 0.7 or len(t.split()) <= 3):
            return True
    return False


# ── Project Type Detector ─────────────────────────────────────────────────────

def detect_project_type(path_str: str) -> str:
    """Inspect folder contents to identify the project framework/language."""
    p = Path(path_str).expanduser().resolve()
    if not p.is_dir():
        return "Unknown"

    if (p / "artisan").exists():
        return "Laravel"
    if (p / "pubspec.yaml").exists():
        return "Flutter"
    if (p / "package.json").exists():
        try:
            content = (p / "package.json").read_text(encoding="utf-8")
            if "next" in content:
                return "Next.js"
            if "react" in content:
                return "React"
            if "vue" in content:
                return "Vue"
            if "express" in content:
                return "Express/Node.js"
        except Exception:
            pass
        return "Node.js"
    if (p / "pyproject.toml").exists() or (p / "requirements.txt").exists() or (p / "setup.py").exists():
        return "Python"
    if (p / "Cargo.toml").exists():
        return "Rust"
    if (p / "go.mod").exists():
        return "Go"
    if (p / "pom.xml").exists() or (p / "build.gradle").exists():
        return "Java"
    return "Generic"


# ── Short-Term Conversation Memory ───────────────────────────────────────────

class ShortTermMemory:
    """
    Tracks recent conversation history with a sliding expiration TTL.
    If the time between turns exceeds `ttl_seconds`, context resets.
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS, max_turns: int = _DEFAULT_MAX_TURNS):
        self.ttl_seconds = ttl_seconds
        self.max_turns = max_turns
        self._messages: list[dict[str, Any]] = []
        self._last_interaction: float = 0.0
        self._lock = threading.Lock()

    def get_messages(self) -> list[dict[str, Any]]:
        """
        Return the active conversation history.
        Prunes automatically if expired.
        """
        with self._lock:
            now = time.time()
            if self._messages and self._last_interaction > 0:
                elapsed = now - self._last_interaction
                if elapsed > self.ttl_seconds:
                    logger.info(
                        f"Short-term conversation memory expired ({elapsed:.1f}s > {self.ttl_seconds}s). Resetting context."
                    )
                    self._messages.clear()

            # Return message dictionaries without any internal metadata keys
            clean_msgs = []
            for m in self._messages:
                entry = {k: v for k, v in m.items() if k != "_timestamp"}
                clean_msgs.append(entry)
            return clean_msgs

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a raw message (user, assistant, tool) to history."""
        with self._lock:
            self._last_interaction = time.time()
            m_copy = dict(message)
            m_copy["_timestamp"] = self._last_interaction
            self._messages.append(m_copy)

            # Trim older turns if exceeding limit (keeping complete user/assistant pairs)
            if len(self._messages) > self.max_turns * 3:
                self._messages = self._messages[-(self.max_turns * 3):]

    def set_messages(self, messages: list[dict[str, Any]]) -> None:
        """Replace history in place (useful for full turn updates)."""
        with self._lock:
            self._last_interaction = time.time()
            self._messages = [dict(m, _timestamp=self._last_interaction) for m in messages]

    def clear(self) -> None:
        """Explicitly reset short-term memory."""
        with self._lock:
            self._messages.clear()
            self._last_interaction = 0.0

    @property
    def last_interaction_time(self) -> float:
        return self._last_interaction


# ── Long-Term Memory (SQLite) ─────────────────────────────────────────────────

class LongTermMemory:
    """
    SQLite-backed store for facts, preferences, server details, and project context.
    """

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            config_path = get("memory.db_path", "data/memory.db")
            self.db_path = PROJECT_ROOT / config_path
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        self._seed_initial_facts()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT UNIQUE NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    name TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    project_type TEXT DEFAULT 'Unknown',
                    is_active INTEGER DEFAULT 0,
                    last_commands TEXT DEFAULT '[]',
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _seed_initial_facts(self) -> None:
        """Seed initial facts from config.yaml if the facts table is empty."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM facts")
            if cur.fetchone()[0] == 0:
                logger.info("Seeding initial facts from configuration...")
                now = datetime.now(timezone.utc).isoformat()
                initial_facts = []

                # Seed projects from config
                projects = get("projects") or {}
                for name, p_path in projects.items():
                    p_type = detect_project_type(p_path)
                    initial_facts.append(
                        (f"Project '{name}' is at {p_path} (Type: {p_type})", "project", now, now)
                    )
                    conn.execute("""
                        INSERT OR REPLACE INTO projects (name, path, project_type, is_active, last_commands, updated_at)
                        VALUES (?, ?, ?, 0, '[]', ?)
                    """, (name, str(p_path), p_type, now))

                # Seed default apps from config
                apps = get("apps") or {}
                if apps:
                    app_desc = ", ".join(f"{k} -> {v}" for k, v in list(apps.items())[:6])
                    initial_facts.append(
                        (f"Configured desktop applications: {app_desc}", "preference", now, now)
                    )

                # Seed services from config
                services = get("services") or {}
                if services:
                    srv_desc = ", ".join(f"{k} ({v.get('name', k)})" for k, v in services.items())
                    initial_facts.append(
                        (f"Known system services: {srv_desc}", "server", now, now)
                    )

                for fact, cat, c_at, u_at in initial_facts:
                    conn.execute("""
                        INSERT OR IGNORE INTO facts (content, category, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                    """, (fact, cat, c_at, u_at))
                conn.commit()

    # ── Fact Operations ────────────────────────────────────────────────────────

    def remember(self, text: str, category: str = "general") -> str:
        """
        Store a fact in memory. Filters out sensitive credentials.
        Returns a human-readable confirmation.
        """
        raw = text.strip()
        if not raw:
            return "Cannot remember an empty fact."

        # Safety check: reject pure credentials
        if is_pure_secret(raw):
            logger.warning("Refused to store sensitive secret/password in memory.")
            return "For security reasons, I cannot store API keys, passwords, or tokens in memory."

        cleaned, had_secret = scrub_secrets(raw)
        if had_secret:
            logger.warning(f"Redacted sensitive secret from memory fact: {cleaned}")

        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT INTO facts (content, category, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(content) DO UPDATE SET updated_at=excluded.updated_at
            """, (cleaned, category, now, now))
            conn.commit()

        logger.info(f"Fact remembered: {cleaned!r}")
        return f"I'll remember that: '{cleaned}'"

    def recall(self, query: str, limit: int = 5) -> list[str]:
        """
        Find stored facts matching the query.
        Splits query into keywords and matches against content.
        """
        words = [w.lower().strip() for w in re.findall(r"\w{2,}", query)]
        if not words:
            # Return most recent facts
            with self._lock, self._get_connection() as conn:
                rows = conn.execute("SELECT content FROM facts ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
                return [r["content"] for r in rows]

        with self._lock, self._get_connection() as conn:
            all_rows = conn.execute("SELECT content FROM facts").fetchall()

        # Score by keyword matches
        scored: list[tuple[int, str]] = []
        for r in all_rows:
            content = r["content"]
            content_lower = content.lower()
            score = sum(1 for w in words if w in content_lower)
            if score > 0:
                scored.append((score, content))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def forget(self, query: str) -> int:
        """
        Delete facts that match the given search query.
        Returns the count of deleted facts.
        """
        raw_query = query.strip()
        if not raw_query:
            return 0

        words = [w.lower().strip() for w in re.findall(r"\w{2,}", raw_query)]
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            if not words:
                cur.execute("DELETE FROM facts WHERE content LIKE ?", (f"%{raw_query}%",))
                deleted = cur.rowcount
            else:
                # Find matching row IDs
                all_facts = cur.execute("SELECT id, content FROM facts").fetchall()
                to_delete = []
                for row in all_facts:
                    content_lower = row["content"].lower()
                    if any(w in content_lower for w in words):
                        to_delete.append(row["id"])

                if to_delete:
                    cur.executemany("DELETE FROM facts WHERE id = ?", [(i,) for i in to_delete])
                    deleted = len(to_delete)
                else:
                    deleted = 0

            conn.commit()

        logger.info(f"Forgot {deleted} fact(s) matching query {query!r}")
        return deleted

    # ── Project Context ────────────────────────────────────────────────────────

    def set_active_project(self, name: str, path: str | None = None) -> dict[str, Any]:
        """Set a project as the currently active project and detect its type."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            # Deactivate all
            conn.execute("UPDATE projects SET is_active = 0")

            # Check if project already exists
            cur = conn.cursor()
            existing = cur.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()

            if existing:
                resolved_path = path or existing["path"]
                p_type = detect_project_type(resolved_path)
                conn.execute("""
                    UPDATE projects SET is_active = 1, path = ?, project_type = ?, updated_at = ?
                    WHERE name = ?
                """, (resolved_path, p_type, now, name))
            else:
                resolved_path = path or str(PROJECT_ROOT)
                p_type = detect_project_type(resolved_path)
                conn.execute("""
                    INSERT INTO projects (name, path, project_type, is_active, last_commands, updated_at)
                    VALUES (?, ?, ?, 1, '[]', ?)
                """, (name, resolved_path, p_type, now))

            conn.commit()

        logger.info(f"Active project set to '{name}' at {resolved_path} ({p_type})")
        return {
            "name": name,
            "path": resolved_path,
            "project_type": p_type,
            "is_active": True,
        }

    def get_active_project(self) -> dict[str, Any] | None:
        """Get the current active project, if any."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE is_active = 1 LIMIT 1").fetchone()
            if not row:
                return None
            try:
                last_cmds = json.loads(row["last_commands"])
            except Exception:
                last_cmds = []
            return {
                "name": row["name"],
                "path": row["path"],
                "project_type": row["project_type"],
                "last_commands": last_cmds,
            }

    def record_project_command(self, command: str) -> None:
        """Log a shell command into the active project's recent commands list."""
        cleaned_cmd, _ = scrub_secrets(command.strip())
        with self._lock, self._get_connection() as conn:
            row = conn.execute("SELECT name, last_commands FROM projects WHERE is_active = 1 LIMIT 1").fetchone()
            if not row:
                return
            try:
                cmds: list[str] = json.loads(row["last_commands"])
            except Exception:
                cmds = []

            # Avoid immediate duplicate
            if not cmds or cmds[-1] != cleaned_cmd:
                cmds.append(cleaned_cmd)
                if len(cmds) > 6:
                    cmds = cmds[-6:]

            conn.execute(
                "UPDATE projects SET last_commands = ?, updated_at = ? WHERE name = ?",
                (json.dumps(cmds), datetime.now(timezone.utc).isoformat(), row["name"]),
            )
            conn.commit()

    # ── Context Extraction for Brain Prompt ────────────────────────────────────

    def get_relevant_context(self, user_text: str) -> str:
        """
        Extract only the relevant memories and project context for the current user turn.
        Never overloads the prompt with the entire database.
        """
        lines: list[str] = []

        # 1. Active project context
        active_proj = self.get_active_project()
        if active_proj:
            proj_str = (
                f"- Active Project: '{active_proj['name']}' at {active_proj['path']} "
                f"[{active_proj['project_type']}]"
            )
            if active_proj["last_commands"]:
                recent = ", ".join(f"`{c}`" for c in active_proj["last_commands"][-3:])
                proj_str += f" | Recent commands: {recent}"
            lines.append(proj_str)

        # 2. Targeted fact retrieval matching user text keywords
        matching_facts = self.recall(user_text, limit=3)
        for f in matching_facts:
            lines.append(f"- Memory: {f}")

        if not lines:
            return ""

        return "\n".join(lines)


# ── Global Manager Instance ───────────────────────────────────────────────────

class MemoryManager:
    """Unified access point for both short-term and long-term memory."""

    def __init__(self):
        ttl = int(get("memory.short_term_ttl_seconds", _DEFAULT_TTL_SECONDS))
        self.short_term = ShortTermMemory(ttl_seconds=ttl)
        self.long_term = LongTermMemory()

    def get_relevant_prompt_section(self, user_text: str) -> str:
        """Produce the dynamic system prompt snippet containing only relevant memories."""
        return self.long_term.get_relevant_context(user_text)

    def record_command(self, cmd: str) -> None:
        self.long_term.record_project_command(cmd)

    def get_active_project(self) -> dict[str, Any] | None:
        return self.long_term.get_active_project()

    def set_active_project(self, name: str, path: str | None = None) -> dict[str, Any]:
        return self.long_term.set_active_project(name, path)


# Global singleton instance
memory_manager = MemoryManager()
