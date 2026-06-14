"""Subtitle Generator package.

Generate subtitles for a video using whisper.cpp (local speech-to-text).

The package is split into core logic and UI/usage modules:

Core logic
    config      - load/save user configuration
    srt         - SRT parsing, writing, and caption cleanup
    transcribe  - audio extraction + whisper invocation + segmentation pipeline
    logging_    - file logger

UI / usage
    progress    - terminal progress bar
    languages   - supported language table
    interactive - arrow-key menus and prompts
    cli         - argument parsing and the main() entry point
"""

__version__ = "2.0.0"
