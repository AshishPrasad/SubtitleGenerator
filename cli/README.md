# Python CLI Tool - Subtitle Generator

A standalone command-line interface for generating subtitles without VLC. Requires Python 3.6+ (no external packages needed).

## Usage

```powershell
# Direct mode (all options via flags)
python subtitle_cli.py "C:\path\to\video.mp4"
python subtitle_cli.py "video.mp4" --language es --translate
python subtitle_cli.py "video.mp4" --segment-size 120 -o "C:\Subtitles\output.srt"

# Interactive mode (arrow-key menus for all options)
python subtitle_cli.py --interactive
python subtitle_cli.py -i
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `video` | Path to video file (optional if `--interactive`) | — |
| `--interactive`, `-i` | Launch interactive mode with arrow-key menus | `false` |
| `--whisper-path` | Path to whisper-cli.exe | From config |
| `--model-path` | Path to .bin model file | From config |
| `--ffmpeg-path` | Path to ffmpeg | From config |
| `--language`, `-l` | Audio language code | From config (`en`) |
| `--translate`, `-t` | Translate to English | `false` |
| `--segment-size` | Seconds per segment | From config (`120`) |
| `-o`, `--output` | Output SRT path | Same folder as video |

## Features

- **Interactive mode** (`-i`): Arrow-key menus for language, translate, segment size; prompted paths with defaults
- **Smart defaults**: Translation to English is automatically enabled when a non-English source language is selected
- **Persisted settings**: Saves config after successful runs; pre-fills values on next invocation
- Reads defaults from its own config (`%APPDATA%\subtitle_generator\config.txt`)
- Only the video path is required — all other options fall back to saved settings
- Progress bar with percentage updates per segment
- Uses safe subprocess calls (no shell string building) — handles special characters in paths

## How It Works

1. Loads defaults from config file (`%APPDATA%\subtitle_generator\config.txt`)
2. Extracts audio from the video using ffmpeg → 16kHz mono WAV
3. Calculates exact duration from WAV file size
4. Splits processing into segments and runs whisper-cli.exe on each
5. Merges segment SRT outputs into a single subtitle file
6. Prints the output SRT path to stdout

## Generated Files (Debugging)

| File | Location | Purpose |
|------|----------|---------|
| `<video>.srt` | Same folder as video (or `-o` path) | Generated subtitles |
| `<video>.log` | Same folder as SRT | Detailed run log with all commands and output |

### Log file

The log is saved next to the output SRT file:
```
C:\path\to\video.log
```

Contains: all paths used, ffmpeg/whisper commands, segment progress, errors with stack traces.
