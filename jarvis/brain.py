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

from openai import OpenAI

from jarvis import config
from jarvis.logger import action_log, logger
from jarvis.permission_gate import check as gate_check, PermissionDenied
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
) -> str:
    """
    Run one full conversation turn.

    Parameters
    ----------
    user_text : str
        The user's transcribed or typed input.
    conversation_history : list[dict]
        Running message list (mutated in place for multi-turn context).
    speak_fn : callable | None
        If provided, voice output function used by the permission gate.

    Returns
    -------
    str
        The model's final text reply (to be spoken or printed).
    """
    client = _get_client()
    tools = get_tool_schemas()

    # Append user message
    conversation_history.append({"role": "user", "content": user_text})

    for iteration in range(config.MAX_TOOL_ITERATIONS):
        logger.info(f"Brain iteration {iteration + 1}")

        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history,
            tools=tools,
            tool_choice="auto",
        )

        message = response.choices[0].message

        # ── No tool call: model is done ───────────────────────────────────
        if not message.tool_calls:
            reply = message.content or "(no reply)"
            conversation_history.append({"role": "assistant", "content": reply})
            return reply

        # ── Append the assistant's tool-call message ──────────────────────
        conversation_history.append(message.model_dump(exclude_unset=True))

        # ── Execute each tool call ────────────────────────────────────────
        for tc in message.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            tool_result = _execute_tool(tool_name, args, speak_fn)

            # Append tool result message
            conversation_history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

    # Hit iteration limit
    fallback = "I reached the maximum number of tool calls for this request. Please try a simpler command."
    conversation_history.append({"role": "assistant", "content": fallback})
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
