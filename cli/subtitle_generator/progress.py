"""Terminal progress bar (UI)."""

import sys


def print_progress(percent: float, width: int = 40):
    filled = int(width * percent / 100)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    sys.stderr.write(f"\r  [{bar}] {percent:5.1f}%")
    sys.stderr.flush()


def clear_progress():
    sys.stderr.write("\r" + " " * 60 + "\r")
    sys.stderr.flush()
