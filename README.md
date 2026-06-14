# Subtitle Generator

**Version: 2.0.0**

Generate subtitles for any video using **whisper.cpp** (local speech-to-text). Works entirely offline — no internet or API keys required.

## Features

- Transcribes audio in 30+ languages
- Translates non-English audio to English subtitles (auto-enabled when source language is not English)
- Progress tracking with real-time updates
- Configurable segment size (default: 120s balanced)
- Handles special characters in file paths (parentheses, spaces, unicode)
- Accurate segment boundaries via overlap context, with automatic cleanup of repeated, overlapping, and over-long "stuck" captions
- Your video files are never modified — only a new `.srt` file is created

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐     ┌──────────┐
│  Video File │ ──▶ │   ffmpeg    │ ──▶ │  whisper.cpp    │ ──▶ │ .srt file│
│  (untouched)│     │extract audio│     │ transcribe/     │     │(subtitles)│
│             │     │  → 16kHz WAV│     │ translate       │     │          │
└─────────────┘     └─────────────┘     └─────────────────┘     └──────────┘
```

## Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| **ffmpeg** | Extracts audio from video | `winget install ffmpeg` or [ffmpeg.org](https://ffmpeg.org/download.html) |
| **whisper.cpp** | Speech recognition engine | [GitHub releases](https://github.com/ggerganov/whisper.cpp/releases) |
| **Whisper model** | Model weights (.bin) | [HuggingFace](https://huggingface.co/ggerganov/whisper.cpp/tree/main) — recommend `ggml-small.bin` |

### Model Comparison

| Model | Size | Speed (2hr video) | Accuracy |
|-------|------|-------------------|----------|
| tiny | 75 MB | ~12 min | ~85-90% |
| base | 142 MB | ~20 min | ~92-95% |
| **small** | **466 MB** | **~50 min** | **~95-97%** |
| medium | 1.5 GB | ~3 hrs | ~97-98% |
| large | 2.9 GB | ~6 hrs | ~98-99% |

## Components

This project provides two ways to generate subtitles:

| Component | Description | Documentation |
|-----------|-------------|---------------|
| **[VLC Extension](vlc-extension/README.md)** | GUI integrated into VLC's View menu. Full File mode, Live mode, auto-reload. Includes PowerShell/batch backend scripts. | [vlc-extension/README.md](vlc-extension/README.md) |
| **[Python CLI](cli/README.md)** | Standalone command-line tool. Python 3.8+, no external packages. | [cli/README.md](cli/README.md) |

### Quick Start — VLC Extension

```powershell
# Install — copy all three Lua files (entry + core + UI) into the extensions folder
Copy-Item "vlc-extension\*.lua" "$env:APPDATA\vlc\lua\extensions\"
New-Item -ItemType Directory -Path "$env:APPDATA\vlc\lua\extensions\scripts" -Force
Copy-Item "vlc-extension\generate_subtitles.*" "$env:APPDATA\vlc\lua\extensions\scripts\"
# Restart VLC → View → Subtitle Generator → Settings → configure paths → Generate
```

### Quick Start — Python CLI

```powershell
python cli/subtitle_cli.py "C:\path\to\video.mp4"
python cli/subtitle_cli.py "video.mp4" --language es --translate
```

## Supported Languages

| Code | Language | Code | Language | Code | Language |
|------|----------|------|----------|------|----------|
| `auto` | Auto Detect | `ja` | Japanese | `tr` | Turkish |
| `en` | English | `ko` | Korean | `vi` | Vietnamese |
| `es` | Spanish | `zh` | Chinese | `th` | Thai |
| `fr` | French | `ru` | Russian | `id` | Indonesian |
| `de` | German | `ar` | Arabic | `uk` | Ukrainian |
| `it` | Italian | `hi` | Hindi | `el` | Greek |
| `pt` | Portuguese | `nl` | Dutch | `cs` | Czech |
| | | `pl` | Polish | `ro` | Romanian |
| | | `sv` | Swedish | `da` | Danish |
| | | `fi` | Finnish | `hu` | Hungarian |
| | | `no` | Norwegian | `he` | Hebrew |
| | | `ta` | Tamil | `te` | Telugu |

## Project Structure

```
SubtitleGenerator/
├── cli/
│   ├── subtitle_cli.py             # Backward-compatible entry point (thin shim)
│   ├── subtitle_generator/         # Python package
│   │   ├── __init__.py             # Version
│   │   ├── config.py               # Core: load/save configuration
│   │   ├── srt.py                  # Core: SRT parse/write + caption cleanup
│   │   ├── transcribe.py           # Core: ffmpeg + whisper + segmentation pipeline
│   │   ├── logging_.py             # File logger
│   │   ├── progress.py             # UI: terminal progress bar
│   │   ├── languages.py            # Supported language table
│   │   ├── interactive.py          # UI: arrow-key menus and prompts
│   │   ├── cli.py                  # Usage: argparse + main() entry point
│   │   └── __main__.py             # Enables `python -m subtitle_generator`
│   └── README.md
├── vlc-extension/
│   ├── subtitle_generator.lua      # Entry: VLC lifecycle hooks (loads modules below)
│   ├── sg_core.lua                 # Core logic (config, paths, media, process control)
│   ├── sg_ui.lua                   # UI (dialogs and widget handling)
│   ├── generate_subtitles.ps1      # Main processing script (ffmpeg + whisper)
│   ├── generate_subtitles.bat      # Batch wrapper for VLC to launch PowerShell
│   └── README.md
├── tests/                          # test suite (run: python tests/run_all.py)
│   ├── cli/                        # CLI package tests (srt, transcribe, config, cli)
│   ├── vlc-extension/              # VLC Lua tests (lupa) + PowerShell backend tests
│   ├── run_all.py                  # Runs all tests (Python + PowerShell)
│   └── README.md
└── README.md                      # This file
```

## Tests

Run the full suite (CLI Python tests + VLC Lua and PowerShell backend tests) from the repo root:

```powershell
python tests/run_all.py
```

Tests are grouped by component under `tests/cli/` and `tests/vlc-extension/`. The Lua tests are optional (run only if [`lupa`](https://pypi.org/project/lupa/) is installed) and the PowerShell backend tests run via `pwsh`/`powershell`; both are skipped automatically when unavailable. See [tests/README.md](tests/README.md).

## License

MIT License
