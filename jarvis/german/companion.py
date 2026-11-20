"""
jarvis/german/companion.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
German Study Companion Engine for Jarvis.

Features:
  • B1-level German conversational partner.
  • Gentle grammar and vocabulary corrections with short, clear explanations.
  • Introduces 2–3 new B1 vocabulary words per session.
  • Asks engaging follow-up questions to encourage conversational flow.
  • Persists new words and user mistakes to SQLite (data/german_study.db).
  • Quick quizzes on demand based on past mistakes and learned vocabulary.
  • Automatically coordinates with Speech Recognition (STT) and TTS language.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable

from jarvis.cost.tracker import track_model_call
from jarvis.german.state import is_german_mode_active, set_german_mode
from jarvis.german.store import (
    get_common_mistakes,
    get_next_vocabulary_to_introduce,
    get_recent_vocabulary,
    get_study_statistics,
    mark_vocabulary_introduced,
    record_mistake,
)
from jarvis.logger import logger

_session_lock = threading.Lock()
_active_session_data: dict[str, Any] = {
    "start_time": 0.0,
    "words_introduced": [],
    "mistakes_recorded": [],
    "turns_count": 0,
}

GERMAN_B1_SYSTEM_PROMPT = """You are Jarvis, acting as a friendly, supportive German language tutor for an English-speaking software engineer named Alamin.
Your level is simple, natural German at CEFR B1 level.

Guidelines for your replies:
1. Speak in clear, natural German at B1 level (use Perfekt, Präteritum with modal verbs, weil/dass/wenn clauses, and common everyday vocabulary). Keep sentences manageable and easy to understand when spoken aloud.
2. GENTLE ERROR CORRECTION: If the user makes a grammar, vocabulary, case (Akkusativ/Dativ), or gender (der/die/das) mistake, gently correct it first with a very short, supportive explanation in German (or bilingual if needed). For example:
   "Tipp: Man sagt 'Ich fahre mit dem Bus' (Dativ nach 'mit'), nicht 'mit den Bus'. Alles andere war super!"
3. INTRODUCING NEW WORDS: If instructed or when natural, introduce 1 new B1 word with its article, English meaning, and an example sentence.
4. ENGAGING FOLLOW-UP: Always ask an engaging, open-ended question at the end to keep the conversation going.
5. Keep your spoken response concise (usually 2 to 4 sentences). Avoid bullet points or long markdown lists since this is spoken aloud.
"""


def get_active_session_info() -> dict[str, Any]:
    """Return a copy of the active German session metadata."""
    with _session_lock:
        return {
            "is_active": is_german_mode_active(),
            "turns_count": _active_session_data["turns_count"],
            "words_introduced_count": len(_active_session_data["words_introduced"]),
            "words_introduced": list(_active_session_data["words_introduced"]),
            "mistakes_count": len(_active_session_data["mistakes_recorded"]),
        }


def start_german_session(speak_fn: Callable[[str], None] | None = None) -> str:
    """
    Start a German practice session at B1 level.
    Switches STT/TTS language pipeline to German.
    """
    with _session_lock:
        set_german_mode(True)
        _active_session_data["start_time"] = time.time()
        _active_session_data["words_introduced"] = []
        _active_session_data["mistakes_recorded"] = []
        _active_session_data["turns_count"] = 0

    greeting_german = (
        "Hallo Alamin! Schön, dass wir heute Deutsch auf B1-Niveau üben. "
        "Ich helfe dir bei der Grammatik und neuen Wörtern. "
        "Worüber möchtest du heute sprechen? Zum Beispiel über deinen Arbeitstag oder deine Wochenendpläne?"
    )

    logger.info(f"[German Companion] Started German session: {greeting_german}")

    if speak_fn:
        try:
            speak_fn(greeting_german)
        except Exception as exc:
            logger.debug(f"[German Companion] Speak error: {exc}")
    else:
        try:
            from jarvis.voice_output import speak
            speak(greeting_german)
        except Exception:
            pass

    return (
        "🇩🇪 **German Practice Session Activated (B1 Level)**\n\n"
        f"- **Language Mode**: German (`de` for Whisper STT & TTS)\n"
        "- **Target Level**: CEFR B1 (Everyday conversation, gentle corrections, new vocabulary)\n"
        "- **Commands**: Say *'German quiz'* for a quick test, or *'stop German practice'* when finished.\n\n"
        f"📢 *Jarvis*: \"{greeting_german}\""
    )


def stop_german_session(speak_fn: Callable[[str], None] | None = None) -> str:
    """
    End the current German practice session and return language mode to English.
    """
    with _session_lock:
        set_german_mode(False)
        words = list(_active_session_data["words_introduced"])
        mistakes = list(_active_session_data["mistakes_recorded"])
        turns = _active_session_data["turns_count"]

    vocab_count = len(words)
    words_summary = ", ".join(w.get("word", "") for w in words) if words else "none yet"

    closing_message = (
        f"Super gemacht, Alamin! We are now back in English mode. "
        f"You completed {turns} turns of German conversation. "
    )
    if vocab_count > 0:
        closing_message += f"Today you practiced {vocab_count} new vocabulary word{'s' if vocab_count > 1 else ''}: {words_summary}. "
    closing_message += "Auf Wiedersehen und bis zum nächsten Mal!"

    logger.info(f"[German Companion] Ended German session: {closing_message}")

    if speak_fn:
        try:
            speak_fn(closing_message)
        except Exception as exc:
            logger.debug(f"[German Companion] Speak error: {exc}")
    else:
        try:
            from jarvis.voice_output import speak
            speak(closing_message)
        except Exception:
            pass

    return (
        "🇬🇧 **German Practice Session Ended**\n\n"
        f"- **Language Mode**: English (`en` restored)\n"
        f"- **Conversation Turns**: {turns}\n"
        f"- **New Vocabulary Introduced**: {vocab_count} ({words_summary})\n"
        f"- **Mistakes Reviewed**: {len(mistakes)}\n\n"
        f"📢 *Jarvis*: \"{closing_message}\""
    )


def _check_and_record_mistake_from_text(user_text: str, reply_text: str) -> None:
    """Analyze tutor response to extract any gentle grammar correction provided."""
    # Look for common correction patterns in the tutor's reply
    tip_pattern = re.search(r"(?:Tipp|Hinweis|Korrektur|Achte auf|Besser heißt es):\s*([^.\n]+(?:\.[^.\n]+)?)", reply_text, re.IGNORECASE)
    if tip_pattern:
        tip_text = tip_pattern.group(1).strip()
        explanation = tip_text
        correction = tip_text
        record_mistake(
            user_phrase=user_text,
            correction=correction,
            explanation=explanation,
            category="Grammatik / B1",
        )
        with _session_lock:
            _active_session_data["mistakes_recorded"].append({
                "user_text": user_text,
                "tip": tip_text,
            })


def process_german_turn(
    user_text: str,
    conversation_history: list[dict] | None = None,
    speak_fn: Callable[[str], None] | None = None,
) -> str:
    """
    Process one conversational turn during German practice.
    Maintains B1 level, offers gentle corrections, introduces new vocabulary,
    and asks follow-up questions.
    """
    clean_lower = user_text.lower().strip()

    # 1. Check for stop / exit commands
    exit_triggers = [
        "stop practice", "stop german", "end german", "exit german",
        "back to english", "switch back to english", "quit german",
        "aufhören", "genug für heute", "stop german practice", "i want to stop"
    ]
    if any(trigger in clean_lower for trigger in exit_triggers):
        return stop_german_session(speak_fn=speak_fn)

    # 2. Check for quiz request
    quiz_triggers = [
        "quiz", "quiz me", "german quiz", "deutsch quiz", "ein quiz", "teste mich", "quick quiz"
    ]
    if any(trigger in clean_lower for trigger in quiz_triggers):
        return generate_quick_quiz(speak_fn=speak_fn)

    # 3. Determine if we should introduce a new B1 vocabulary word this turn
    vocab_to_introduce: dict[str, Any] | None = None
    with _session_lock:
        _active_session_data["turns_count"] += 1
        current_introduced = len(_active_session_data["words_introduced"])

    # Target: introduce 2–3 words per session (e.g. at turns 1 and 3)
    if current_introduced < 3 and (_active_session_data["turns_count"] in (1, 3, 5)):
        vocab_candidate = get_next_vocabulary_to_introduce()
        if vocab_candidate:
            vocab_to_introduce = vocab_candidate
            mark_vocabulary_introduced(vocab_candidate["id"])
            with _session_lock:
                _active_session_data["words_introduced"].append(vocab_candidate)

    # Build prompt addition for vocabulary injection
    extra_instructions = ""
    if vocab_to_introduce:
        extra_instructions = (
            f"\nPlease naturally introduce this new B1 vocabulary word in your reply:\n"
            f"- Word: '{vocab_to_introduce['word']}'\n"
            f"- Meaning: '{vocab_to_introduce['translation']}'\n"
            f"- Example: '{vocab_to_introduce['example_sentence']}'\n"
            f"Explain it briefly and give an example, then ask the user a question using or related to this word."
        )

    # Get recent mistakes for context so the tutor knows what the student struggles with
    recent_mistakes = get_common_mistakes(limit=3)
    mistake_context = ""
    if recent_mistakes:
        mistake_context = "\nStudent's common past mistakes:\n" + "\n".join(
            f"- Said: '{m['user_phrase']}' -> Correct: '{m['correction']}' ({m['explanation']})"
            for m in recent_mistakes
        )

    # Generate response via OpenAI model
    import os
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        fallback = (
            f"Sehr gut gesagt! Ich habe dich verstanden: '{user_text}'. "
            "Erzähl mir bitte mehr darüber!"
        )
        if speak_fn:
            speak_fn(fallback)
        return fallback

    client = OpenAI(api_key=api_key)
    system_content = (
        GERMAN_B1_SYSTEM_PROMPT
        + mistake_context
        + extra_instructions
    )

    messages = [{"role": "system", "content": system_content}]
    if conversation_history:
        # Include recent turns for dialogue context
        messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_text})

    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
            max_tokens=250,
        )
        reply = completion.choices[0].message.content.strip()

        # Track cost
        if hasattr(completion, "usage") and completion.usage:
            track_model_call(
                model="gpt-4o",
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
            )
    except Exception as exc:
        logger.error(f"[German Companion] Model error: {exc}")
        reply = (
            f"Das ist ein interessanter Gedanke. "
            f"Kannst du das noch mit einem weiteren Beispiel beschreiben?"
        )

    # Parse any gentle grammar correction from reply and save to DB
    _check_and_record_mistake_from_text(user_text, reply)

    # Speak response aloud in German
    logger.info(f"[German Companion] Reply: {reply}")
    if speak_fn:
        try:
            speak_fn(reply)
        except Exception as exc:
            logger.debug(f"[German Companion] Speak error: {exc}")
    else:
        try:
            from jarvis.voice_output import speak
            speak(reply)
        except Exception:
            pass

    vocab_badge = ""
    if vocab_to_introduce:
        vocab_badge = (
            f"\n\n📚 **Neues B1-Wort**: `{vocab_to_introduce['word']}` "
            f"(*{vocab_to_introduce['translation']}*)\n"
            f"> *{vocab_to_introduce['example_sentence']}*"
        )

    return f"🇩🇪 **Jarvis (B1 Deutsch)**:\n\n{reply}{vocab_badge}"


def generate_quick_quiz(speak_fn: Callable[[str], None] | None = None) -> str:
    """
    Generate a quick quiz question based on learned vocabulary and recorded mistakes.
    """
    # 1. Try to quiz from recorded mistakes first if available
    mistakes = get_common_mistakes(limit=5)
    vocab = get_recent_vocabulary(limit=5)

    quiz_prompt = ""
    spoken_quiz = ""

    if mistakes:
        # Mistake correction quiz
        target_mistake = mistakes[0]
        spoken_quiz = (
            f"Hier ist ein schnelles Quiz zu einer früheren Grammatikfrage! "
            f"Wie lautet die richtige Version von: '{target_mistake['user_phrase']}'?"
        )
        quiz_prompt = (
            f"🎯 **Schnelles Deutsch-Quiz (Grammatik & B1)**\n\n"
            f"**Frage**: Wie korrigierst du diesen Satz?\n"
            f"> *\"{target_mistake['user_phrase']}\"*\n\n"
            f"💡 **Tipp**: {target_mistake['explanation']}\n\n"
            f"📢 *Voice Prompt*: \"{spoken_quiz}\""
        )
    elif vocab:
        # Vocabulary meaning quiz
        target_vocab = vocab[0]
        spoken_quiz = (
            f"Hier ist dein Vokabel-Quiz! Was bedeutet das B1-Wort '{target_vocab['word']}' auf Englisch, "
            f"und kannst du einen Beispielsatz damit bilden?"
        )
        quiz_prompt = (
            f"🎯 **Schnelles Deutsch-Quiz (Wortschatz B1)**\n\n"
            f"**Wort**: `{target_vocab['word']}`\n"
            f"**Frage**: Was bedeutet dieses Wort auf Englisch, oder wie lautet der Plural / Artikel?\n\n"
            f"💡 **Beispiel**: *{target_vocab['example_sentence']}*\n\n"
            f"📢 *Voice Prompt*: \"{spoken_quiz}\""
        )
    else:
        # Default starter B1 quiz question
        spoken_quiz = (
            "Hier ist ein schnelles B1-Quiz: Welcher Artikel gehört zu 'Herausforderung'? "
            "Der, die oder das?"
        )
        quiz_prompt = (
            "🎯 **Schnelles Deutsch-Quiz (B1)**\n\n"
            "**Frage**: Welcher Artikel gehört zum Nomen **Herausforderung**?\n"
            "A) der\n"
            "B) die\n"
            "C) das\n\n"
            "💡 *Tipp: Substantive auf '-ung' sind im Deutschen immer feminin (die).*\n\n"
            f"📢 *Voice Prompt*: \"{spoken_quiz}\""
        )

    logger.info(f"[German Companion] Generated quiz: {spoken_quiz}")

    if speak_fn:
        try:
            speak_fn(spoken_quiz)
        except Exception as exc:
            logger.debug(f"[German Companion] Speak error: {exc}")
    else:
        try:
            from jarvis.voice_output import speak
            speak(spoken_quiz)
        except Exception:
            pass

    return quiz_prompt
