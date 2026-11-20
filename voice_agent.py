#!/usr/bin/env python3
"""
voice_agent.py — project-root launcher for the voice agent.
Run with:
    python voice_agent.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from jarvis.voice_agent import main

if __name__ == "__main__":
    main()
