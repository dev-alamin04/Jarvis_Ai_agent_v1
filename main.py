#!/usr/bin/env python3
"""
main.py — project-root launcher (convenience wrapper).
Run from /home/alamin/Server/jarvis/:
    python main.py
"""
import sys
from pathlib import Path

# Ensure the project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from jarvis.main import main

if __name__ == "__main__":
    main()
