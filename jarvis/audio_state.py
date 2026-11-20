"""
jarvis/audio_state.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shared audio state flags used by multiple modules:
  - wake word listener
  - voice input recorder
  - voice output (TTS player)

All flags use threading.Event so they are thread-safe and zero-cost to poll.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import threading

# Set while the TTS engine is playing audio → mic ignored to prevent self-triggering
speaking = threading.Event()

# Set while the user wants the mic fully muted (mute hotkey toggled)
muted = threading.Event()

# Set while a command is actively being recorded after wake word
recording = threading.Event()

# Set to signal the wake word thread to stop cleanly (shutdown)
shutdown = threading.Event()
