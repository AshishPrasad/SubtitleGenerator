"""Shared test support: makes the `subtitle_generator` package importable.

The package lives in ``cli/`` so tests insert that folder onto ``sys.path``.
This file sits two levels below the repo root (``tests/<group>/_support.py``).
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI_DIR = os.path.join(REPO_ROOT, "cli")
VLC_DIR = os.path.join(REPO_ROOT, "vlc-extension")

if CLI_DIR not in sys.path:
    sys.path.insert(0, CLI_DIR)
