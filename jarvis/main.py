"""
jarvis/main.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stage-1 entry point: text-only interactive REPL.
Run with:
    python -m jarvis.main
Or via the project launcher:
    python main.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
from jarvis.brain import process_turn
from jarvis.logger import logger


BANNER = """
╔══════════════════════════════════════════════╗
║          J A R V I S  —  Stage 1            ║
║           Text-only interactive mode         ║
║  Type your command and press Enter.          ║
║  Type 'quit' or 'exit' to stop.             ║
╚══════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    logger.info("Jarvis Stage-1 (text mode) started.")

    conversation_history: list[dict] = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "bye"):
            print("Jarvis: Goodbye.")
            sys.exit(0)

        print("Jarvis: thinking…")
        reply = process_turn(
            user_text=user_input,
            conversation_history=conversation_history,
            speak_fn=None,       # no voice in Stage 1
        )
        print(f"Jarvis: {reply}\n")


if __name__ == "__main__":
    main()
