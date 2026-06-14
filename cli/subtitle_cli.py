#!/usr/bin/env python3
"""Subtitle Generator CLI - backward-compatible entry point.

The implementation now lives in the ``subtitle_generator`` package (core logic
in ``srt``/``transcribe``/``config``; UI/usage in ``cli``/``interactive``/
``progress``). This thin shim keeps the original invocation working:

    python cli/subtitle_cli.py "C:\\path\\to\\video.mp4"
    python cli/subtitle_cli.py "video.mp4" --language es --translate

Equivalent to ``python -m subtitle_generator``.
"""

import os
import sys

# Ensure the package directory (this file's folder) is importable when the
# script is run directly from anywhere.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from subtitle_generator.cli import main

if __name__ == "__main__":
    sys.exit(main())
