"""
jarvis/brain.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The Brain: sends user text to the OpenAI model, runs the tool-calling loop,
and returns a final spoken reply.

Flow per turn:
  user_text → model → [tool call → permission_gate.check → run tool] × N
            → model writes spoken reply → return reply string
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import json
import os
import time

from openai import OpenAI

from jarvis import config
from jarvis.beep import tool_start_chime
from jarvis.logger import action_log, logger
from jarvis.model_router import select_model
from jarvis.permission_gate import check as gate_check, PermissionDenied
from jarvis.streaming_tts import SentenceSplitter, StreamingTTSPlayer
from jarvis.timing import current_timing
from jarvis.tools import TOOL_REGISTRY, get_tool_schemas

# ── OpenAI client (key comes from env, never hardcoded) ───────────────────────
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is not set. "
                "Export it before starting Jarvis."
            )
        _client = OpenAI(api_key=api_key)
    return _client


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Jarvis, a voice-controlled AI assistant for a Linux laptop.
You have access to a set of tools to control the system on the user's behalf.

Guidelines:
- Be concise. Your replies will be spoken aloud, so avoid markdown, bullet points, or long lists.
- If a task needs multiple steps, call tools one at a time and wait for each result.
- You may chain tool calls to accomplish complex tasks.
- Never attempt to bypass the permission gate. If a tool is denied, explain that to the user.
- If you are unsure about a destructive action, ask the user to confirm before proceeding.
- When reading logs or errors, give a brief human-friendly summary.
- Keep replies under 3 sentences where possible.
"""


# ── Main turn function ────────────────────────────────────────────────────────

def process_turn(
    user_text: str,
    conversation_history: list[dict],
    speak_fn=None,
    stream_to_voice: bool = True,
) -> str:
    """
    Run one full conversation turn using model streaming for minimum latency.

    Parameters
    ----------
    user_text : str
        The user's transcribed or typed input.
    conversation_history : list[dict]
        Running message list (mutated in place for multi-turn context).
    speak_fn : callable | None
        If provided and stream_to_voice is False, used for final speech.
    stream_to_voice : bool
        If True, sentences are streamed to TTS the moment they form.

    Returns
    -------
    str
        The model's final text reply.
    """
    client = _get_client()
    tools = get_tool_schemas()

    # Model routing: pick fast model vs strong model
    chosen_model, route_reason = select_model(user_text)
    current_timing.model_used = chosen_model

    # Append user message
    conversation_history.append({"role": "user", "content": user_text})

    # Dynamically inject ONLY relevant memory items and active project context
    from jarvis.memory import memory_manager
    mem_context = memory_manager.get_relevant_prompt_section(user_text)
    dynamic_system_prompt = SYSTEM_PROMPT
    if mem_context:
        dynamic_system_prompt += f"\n\nContext & Memories:\n{mem_context}"

    for iteration in range(config.MAX_TOOL_ITERATIONS):
        logger.info(f"Brain iteration {iteration + 1} (model: {chosen_model})")

        # Set up streaming TTS player if voice streaming is active and not already handled
        tts_player = None
        if stream_to_voice and speak_fn is not None:
            tts_player = StreamingTTSPlayer(client=client, speak_callback=speak_fn)
            tts_player.start()

        splitter = SentenceSplitter()
        accumulated_content: list[str] = []
        raw_tool_calls: dict[int, dict] = {}
        chimed_for_tools = False

        try:
            stream = client.chat.completions.create(
                model=chosen_model,
                messages=[{"role": "system", "content": dynamic_system_prompt}] + conversation_history,
                tools=tools,
                tool_choice="auto",
                stream=True,
            )

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # ── Tool Calls streaming ──────────────────────────────────
                if delta.tool_calls:
                    if not chimed_for_tools:
                        chimed_for_tools = True
                        # Abort any accidental speech and play immediate tool chime
                        if tts_player:
                            tts_player.abort()
                            tts_player = None
                        tool_start_chime()

                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in raw_tool_calls:
                            raw_tool_calls[idx] = {
                                "id": tc.id or "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            raw_tool_calls[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                raw_tool_calls[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                raw_tool_calls[idx]["function"]["arguments"] += tc.function.arguments

                # ── Content streaming ─────────────────────────────────────
                elif delta.content:
                    current_timing.mark_first_token()
                    text_piece = delta.content
                    accumulated_content.append(text_piece)

                    if tts_player:
                        ready_sentences = splitter.feed(text_piece)
                        for sentence in ready_sentences:
                            tts_player.feed_sentence(sentence)

        except Exception as exc:
            logger.error(f"Stream error: {exc}")
            if tts_player:
                tts_player.abort()
            raise

        # ── Handle Tool Execution if tools were called ────────────────────
        if raw_tool_calls:
            if tts_player:
                tts_player.abort()
                tts_player = None

            tool_calls_list = [raw_tool_calls[i] for i in sorted(raw_tool_calls.keys())]
            assistant_msg = {
                "role": "assistant",
                "content": "".join(accumulated_content) or None,
                "tool_calls": tool_calls_list,
            }
            conversation_history.append(assistant_msg)

            for tc in tool_calls_list:
                tool_name = tc["function"]["name"]
                current_timing.tools_called.append(tool_name)
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                tool_result = _execute_tool(tool_name, args, speak_fn)
                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })
            # Loop continues to next iteration for model's spoken reply
            continue

        # ── Finish conversational reply ───────────────────────────────────
        full_reply = "".join(accumulated_content).strip() or "(no reply)"

        if tts_player:
            # Feed remaining text and wait for playback
            rem_sentences = splitter.finish()
            for s in rem_sentences:
                tts_player.feed_sentence(s)
            tts_player.finish()

        conversation_history.append({"role": "assistant", "content": full_reply})
        memory_manager.short_term.set_messages(conversation_history)
        return full_reply

    # Hit iteration limit
    fallback = "I reached the maximum number of tool calls for this request. Please try a simpler command."
    conversation_history.append({"role": "assistant", "content": fallback})
    memory_manager.short_term.set_messages(conversation_history)
    return fallback


def _execute_tool(tool_name: str, args: dict, speak_fn) -> str:
    """Run a single tool call through the permission gate."""
    logger.info(f"Tool requested: {tool_name}  args={args!r}")

    # ── Permission gate ───────────────────────────────────────────────────
    try:
        gate_check(tool_name, args, speak_fn=speak_fn)
    except PermissionDenied as exc:
        result = str(exc)
        action_log(tool_name, args, result, approved=False)
        return result

    # ── Run the tool ──────────────────────────────────────────────────────
    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        result = f"Unknown tool: `{tool_name}`. It is not registered."
        action_log(tool_name, args, result)
        return result

    try:
        result = tool_fn(**args)
    except TypeError as exc:
        result = f"Tool `{tool_name}` was called with wrong arguments: {exc}"
    except Exception as exc:
        result = f"Tool `{tool_name}` raised an error: {exc}"

    action_log(tool_name, args, result, approved=True)
    logger.info(f"Tool result ({tool_name}): {result[:200]!r}")
    return result
