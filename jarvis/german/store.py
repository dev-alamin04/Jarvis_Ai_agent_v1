"""
jarvis/german/store.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Persistent SQLite storage for the German Study Companion.

Manages:
  • B1 Vocabulary bank and newly introduced words.
  • User grammar and vocabulary mistakes with gentle explanations.
  • Quiz records and progress tracking.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.logger import logger

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
GERMAN_DB_PATH = PROJECT_ROOT / "data" / "german_study.db"

_db_lock = threading.Lock()

_STARTER_B1_VOCABULARY = [
    {
        "word": "die Herausforderung",
        "level": "B1",
        "translation": "challenge",
        "example_sentence": "Neue Programmieraufgaben sind eine spannende Herausforderung.",
        "notes": "Feminine noun: -ung suffix is always feminine (die).",
    },
    {
        "word": "die Erfahrung",
        "level": "B1",
        "translation": "experience",
        "example_sentence": "Ich habe bereits viel Erfahrung mit Python und Linux gesammelt.",
        "notes": "Plural: die Erfahrungen.",
    },
    {
        "word": "die Gelegenheit",
        "level": "B1",
        "translation": "opportunity / occasion",
        "example_sentence": "Das heutige Gespräch ist eine tolle Gelegenheit zum Deutschlernen.",
        "notes": "Feminine noun: -heit suffix is always feminine (die).",
    },
    {
        "word": "die Verantwortung",
        "level": "B1",
        "translation": "responsibility",
        "example_sentence": "Als Entwickler trage ich Verantwortung für sicheren Code.",
        "notes": "Phrase: Verantwortung übernehmen (to take responsibility).",
    },
    {
        "word": "die Zuverlässigkeit",
        "level": "B1",
        "translation": "reliability",
        "example_sentence": "Zuverlässigkeit ist eine der wichtigsten Eigenschaften im Beruf.",
        "notes": "Feminine noun: -keit suffix is always feminine.",
    },
    {
        "word": "die Überraschung",
        "level": "B1",
        "translation": "surprise",
        "example_sentence": "Das schnelle Testergebnis war eine positive Überraschung.",
        "notes": "Plural: die Überraschungen.",
    },
    {
        "word": "sich entscheiden für",
        "level": "B1",
        "translation": "to decide on / choose (Akkusativ)",
        "example_sentence": "Wir haben uns für eine saubere Architektur entschieden.",
        "notes": "Reflexive verb with preposition 'für' + Akkusativ.",
    },
    {
        "word": "sich gewöhnen an",
        "level": "B1",
        "translation": "to get used to (Akkusativ)",
        "example_sentence": "Man gewöhnt sich schnell an die deutschen Artikel.",
        "notes": "Reflexive verb with preposition 'an' + Akkusativ.",
    },
    {
        "word": "nachhaltig",
        "level": "B1",
        "translation": "sustainable / lasting",
        "example_sentence": "Tägliches kurzes Üben hat einen nachhaltigen Lerneffekt.",
        "notes": "Adjective / Adverb.",
    },
    {
        "word": "überzeugen",
        "level": "B1",
        "translation": "to convince / persuade",
        "example_sentence": "Gute Argumente und sauberer Code überzeugen jedes Team.",
        "notes": "Inseparable prefix: überzeugen, überzeugte, überzeugt.",
    },
    {
        "word": "begeistert",
        "level": "B1",
        "translation": "enthusiastic / thrilled",
        "example_sentence": "Ich bin begeistert von deinen Fortschritten auf Deutsch!",
        "notes": "Usually used with 'von' + Dativ: begeistert von etwas sein.",
    },
    {
        "word": "selbstverständlich",
        "level": "B1",
        "translation": "self-evident / of course / naturally",
        "example_sentence": "Es ist selbstverständlich, dass Fehler zum Lernen dazugehören.",
        "notes": "Very common conversational phrase: 'Aber selbstverständlich!'",
    },
    {
        "word": "der Unterschied",
        "level": "B1",
        "translation": "difference",
        "example_sentence": "Es gibt einen großen Unterschied zwischen Theorie und Praxis.",
        "notes": "Masculine noun: der Unterschied, die Unterschiede.",
    },
    {
        "word": "die Voraussetzung",
        "level": "B1",
        "translation": "prerequisite / condition",
        "example_sentence": "Gute Konzentration ist die beste Voraussetzung zum Lernen.",
        "notes": "Feminine noun: die Voraussetzung.",
    },
    {
        "word": "unterstützen",
        "level": "B1",
        "translation": "to support / assist",
        "example_sentence": "Jarvis unterstützt dich gerne beim Deutsch üben.",
        "notes": "Regular verb with Akkusativ object.",
    },
    {
        "word": "beeindruckend",
        "level": "B1",
        "translation": "impressive",
        "example_sentence": "Dein Wortschatz ist schon wirklich beeindruckend.",
        "notes": "Participle used as adjective.",
    },
    {
        "word": "regelmäßig",
        "level": "B1",
        "translation": "regularly / regular",
        "example_sentence": "Wer regelmäßig zehn Minuten spricht, macht schnelle Fortschritte.",
        "notes": "Adverb / Adjective.",
    },
]


def _get_db() -> sqlite3.Connection:
    """Connect to SQLite database and ensure tables exist."""
    GERMAN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(GERMAN_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with _db_lock:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS german_vocabulary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word TEXT UNIQUE,
                    level TEXT DEFAULT 'B1',
                    translation TEXT,
                    example_sentence TEXT,
                    notes TEXT,
                    introduced_at TEXT,
                    times_quizzed INTEGER DEFAULT 0,
                    times_correct INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS german_mistakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_phrase TEXT,
                    correction TEXT,
                    explanation TEXT,
                    category TEXT,
                    created_at TEXT,
                    times_quizzed INTEGER DEFAULT 0
                )
            """)

            # Seed starter vocabulary if empty
            cursor = conn.execute("SELECT COUNT(*) as count FROM german_vocabulary")
            if cursor.fetchone()["count"] == 0:
                for item in _STARTER_B1_VOCABULARY:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO german_vocabulary
                        (word, level, translation, example_sentence, notes, introduced_at)
                        VALUES (?, ?, ?, ?, ?, NULL)
                        """,
                        (
                            item["word"],
                            item["level"],
                            item["translation"],
                            item["example_sentence"],
                            item["notes"],
                        ),
                    )
    return conn


def get_next_vocabulary_to_introduce() -> dict[str, Any] | None:
    """Get the next unintroduced B1 vocabulary word from the bank."""
    conn = _get_db()
    with _db_lock:
        cursor = conn.execute(
            """
            SELECT * FROM german_vocabulary
            WHERE introduced_at IS NULL
            ORDER BY id ASC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if not row:
            # If all have been introduced, pick the least quizzed one
            cursor = conn.execute(
                """
                SELECT * FROM german_vocabulary
                ORDER BY times_quizzed ASC, id ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()

    return dict(row) if row else None


def mark_vocabulary_introduced(word_id: int) -> None:
    """Mark a vocabulary word as introduced in today's session."""
    now_iso = datetime.now().isoformat()
    conn = _get_db()
    with _db_lock:
        with conn:
            conn.execute(
                "UPDATE german_vocabulary SET introduced_at = ? WHERE id = ?",
                (now_iso, word_id),
            )


def record_mistake(
    user_phrase: str,
    correction: str,
    explanation: str,
    category: str = "Grammatik",
) -> int:
    """Record a user mistake with gentle correction and explanation."""
    now_iso = datetime.now().isoformat()
    conn = _get_db()
    with _db_lock:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO german_mistakes
                (user_phrase, correction, explanation, category, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_phrase.strip(), correction.strip(), explanation.strip(), category.strip(), now_iso),
            )
            return cursor.lastrowid or 0


def get_recent_vocabulary(limit: int = 10) -> list[dict[str, Any]]:
    """Get recently introduced vocabulary words."""
    conn = _get_db()
    with _db_lock:
        cursor = conn.execute(
            """
            SELECT * FROM german_vocabulary
            WHERE introduced_at IS NOT NULL
            ORDER BY introduced_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cursor.fetchall()]


def get_common_mistakes(limit: int = 10) -> list[dict[str, Any]]:
    """Get recorded user mistakes for review and quiz generation."""
    conn = _get_db()
    with _db_lock:
        cursor = conn.execute(
            """
            SELECT * FROM german_mistakes
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cursor.fetchall()]


def get_study_statistics() -> dict[str, Any]:
    """Retrieve aggregate learning statistics."""
    conn = _get_db()
    with _db_lock:
        total_vocab = conn.execute("SELECT COUNT(*) as c FROM german_vocabulary").fetchone()["c"]
        learned_vocab = conn.execute("SELECT COUNT(*) as c FROM german_vocabulary WHERE introduced_at IS NOT NULL").fetchone()["c"]
        total_mistakes = conn.execute("SELECT COUNT(*) as c FROM german_mistakes").fetchone()["c"]

    return {
        "total_vocabulary": total_vocab,
        "learned_vocabulary": learned_vocab,
        "recorded_mistakes": total_mistakes,
    }


def add_custom_vocabulary(
    word: str,
    translation: str,
    example_sentence: str = "",
    notes: str = "",
    level: str = "B1",
) -> None:
    """Add a new custom vocabulary word to the study store."""
    now_iso = datetime.now().isoformat()
    conn = _get_db()
    with _db_lock:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO german_vocabulary
                (word, level, translation, example_sentence, notes, introduced_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (word.strip(), level, translation.strip(), example_sentence.strip(), notes.strip(), now_iso),
            )
