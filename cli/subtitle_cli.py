#!/usr/bin/env python3
"""Subtitle Generator CLI - Generate subtitles using whisper.cpp and ffmpeg.

Usage:
    subtitle-cli "C:\\path\\to\\video.mp4"
    subtitle-cli "video.mp4" --language es --translate
    subtitle-cli "video.mp4" --whisper-path "C:\\tools\\whisper-cli.exe" --model-path "C:\\tools\\model.bin"
"""

__version__ = "0.2.1"

import argparse
import datetime
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "whisper_path": "",
    "model_path": "",
    "ffmpeg_path": "ffmpeg",
    "language": "en",
    "translate": "no",
    "mode": "full",
    "chunk_size": "30",
    "segment_size": "120",
    "output_dir": "",
}


def get_config_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "subtitle_generator" / "config.txt"
    return Path.home() / ".config" / "subtitle_generator" / "config.txt"


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    path = get_config_path()
    if not path.exists():
        return config
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                if key in config:
                    config[key] = value.strip()
    except Exception:
        pass
    return config


def save_config(args) -> None:
    """Persist current settings to config file for future sessions."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"whisper_path={args.whisper_path}",
        f"model_path={args.model_path}",
        f"ffmpeg_path={args.ffmpeg_path}",
        f"language={args.language}",
        f"translate={'yes' if args.translate else 'no'}",
        f"segment_size={args.segment_size}",
    ]
    if hasattr(args, "output_dir") and args.output_dir:
        lines.append(f"output_dir={args.output_dir}")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# SRT parsing and writing
# ---------------------------------------------------------------------------

def parse_srt_timestamp(ts: str) -> float:
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", ts)
    if not m:
        return 0.0
    h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    return h * 3600 + mi * 60 + s + ms / 1000.0


def format_srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    seconds -= h * 3600
    m = int(seconds // 60)
    seconds -= m * 60
    s = int(seconds)
    ms = int(round((seconds - s) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_file(path: Path) -> list:
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\r?\n\r?\n", content)
    entries = []
    for block in blocks:
        lines = [l for l in re.split(r"\r?\n", block) if l.strip()]
        if len(lines) >= 3:
            time_match = re.match(
                r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})",
                lines[1],
            )
            if time_match:
                start = time_match[1].replace(".", ",")
                end = time_match[2].replace(".", ",")
                text = "\n".join(lines[2:]).strip()
                if text and text != "[BLANK_AUDIO]":
                    entries.append({"start": start, "end": end, "text": text})
    return entries


def offset_entries(entries: list, offset_seconds: float) -> list:
    result = []
    for e in entries:
        new_start = parse_srt_timestamp(e["start"]) + offset_seconds
        new_end = parse_srt_timestamp(e["end"]) + offset_seconds
        result.append({
            "start": format_srt_timestamp(new_start),
            "end": format_srt_timestamp(new_end),
            "text": e["text"],
        })
    return result


def write_srt_file(path: Path, entries: list):
    lines = []
    for i, e in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{e['start']} --> {e['end']}")
        lines.append(e["text"])
        lines.append("")
    tmp = path.with_suffix(".srt.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    if path.exists():
        path.unlink()
    tmp.rename(path)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class Logger:
    def __init__(self, output_srt: str = ""):
        if output_srt:
            self.log_path = Path(output_srt).with_suffix(".log")
        else:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_path = Path(tempfile.gettempdir()) / f"subtitle_generator_v{__version__}_{ts}.log"
        self._file = open(self.log_path, "w", encoding="utf-8")

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        self._file.write(line + "\n")
        self._file.flush()

    def close(self):
        self._file.close()


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

def print_progress(percent: float, width: int = 40):
    filled = int(width * percent / 100)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    sys.stderr.write(f"\r  [{bar}] {percent:5.1f}%")
    sys.stderr.flush()


def clear_progress():
    sys.stderr.write("\r" + " " * 60 + "\r")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

LANGUAGES = [
    ("auto", "Auto Detect"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
    ("ru", "Russian"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("sv", "Swedish"),
    ("fi", "Finnish"),
    ("no", "Norwegian"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("tr", "Turkish"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
    ("id", "Indonesian"),
    ("uk", "Ukrainian"),
    ("el", "Greek"),
    ("cs", "Czech"),
    ("ro", "Romanian"),
    ("da", "Danish"),
    ("hu", "Hungarian"),
    ("he", "Hebrew"),
]


def _is_windows():
    return sys.platform == "win32"


def _getch():
    """Read a single keypress, returning special keys as escape sequences."""
    if _is_windows():
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # special key prefix
            ch2 = msvcrt.getwch()
            return "\x00" + ch2
        return ch
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch += sys.stdin.read(2)
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _select_menu(title: str, options: list, default_idx: int = 0) -> int:
    """Arrow-key menu selector with scrolling window. Returns selected index."""
    idx = default_idx
    total = len(options)
    max_visible = min(total, 10)

    while True:
        # Calculate visible window
        if total <= max_visible:
            start = 0
            end = total
        else:
            half = max_visible // 2
            start = max(0, idx - half)
            end = start + max_visible
            if end > total:
                end = total
                start = end - max_visible

        # Clear and redraw
        sys.stderr.write(f"\r\x1b[K  {title}\n")
        if start > 0:
            sys.stderr.write(f"\x1b[K  \x1b[90m  ↑ {start} more above\x1b[0m\n")
        else:
            sys.stderr.write(f"\x1b[K\n")
        for i in range(start, end):
            opt = options[i]
            prefix = " ▸ " if i == idx else "   "
            highlight = "\x1b[36m" if i == idx else ""
            reset = "\x1b[0m" if i == idx else ""
            sys.stderr.write(f"\x1b[K{prefix}{highlight}{opt}{reset}\n")
        if end < total:
            sys.stderr.write(f"\x1b[K  \x1b[90m  ↓ {total - end} more below\x1b[0m\n")
        else:
            sys.stderr.write(f"\x1b[K\n")
        sys.stderr.write(f"\x1b[K  (↑/↓ to move, Enter to select)\n")
        sys.stderr.flush()

        key = _getch()

        # Move cursor back up to redraw
        lines_to_clear = max_visible + 4  # title + top indicator + options + bottom indicator + hint
        sys.stderr.write(f"\x1b[{lines_to_clear}A")

        if _is_windows():
            if key in ("\x00H", "\xe0H"):  # Up
                idx = (idx - 1) % total
            elif key in ("\x00P", "\xe0P"):  # Down
                idx = (idx + 1) % total
            elif key == "\r":  # Enter
                break
            elif key == "\x1b":  # Escape
                break
        else:
            if key == "\x1b[A":  # Up
                idx = (idx - 1) % total
            elif key == "\x1b[B":  # Down
                idx = (idx + 1) % total
            elif key in ("\r", "\n"):  # Enter
                break
            elif key == "\x1b":  # Escape
                break

    # Final draw with selection highlighted
    lines_to_clear = max_visible + 4
    sys.stderr.write(f"\r\x1b[K  {title}\n")
    sys.stderr.write(f"\x1b[K   \x1b[32m▸ {options[idx]}\x1b[0m\n")
    sys.stderr.write("\x1b[K\n")
    sys.stderr.flush()
    return idx


def _input_path(prompt: str, default: str = "", must_exist: bool = True) -> str:
    """Prompt for a file/directory path with a default value."""
    display_default = default if default else "(none)"
    sys.stderr.write(f"  {prompt}\n")
    sys.stderr.write(f"  \x1b[90mDefault: {display_default}\x1b[0m\n")
    sys.stderr.write("  > ")
    sys.stderr.flush()
    value = input().strip()
    # Strip surrounding quotes (common when dragging files into terminal)
    if value and len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        value = value[1:-1]
    if not value:
        value = default
    if value and must_exist and not Path(value).exists():
        sys.stderr.write(f"  \x1b[33m⚠ Path not found: {value}\x1b[0m\n")
        sys.stderr.write(f"  \x1b[33m  (Continuing anyway — will fail at generation if invalid)\x1b[0m\n")
    sys.stderr.write("\n")
    return value


def _input_value(prompt: str, default: str = "") -> str:
    """Prompt for a text value with a default."""
    sys.stderr.write(f"  {prompt} \x1b[90m[{default}]\x1b[0m: ")
    sys.stderr.flush()
    value = input().strip()
    sys.stderr.write("\n")
    return value if value else default


def run_interactive(config: dict) -> dict:
    """Run interactive wizard, returns a dict of resolved arguments."""
    sys.stderr.write("\n\x1b[1m  ── Subtitle Generator (Interactive Mode) ──\x1b[0m\n\n")

    # Video file
    video = _input_path("Video file path:", must_exist=True)
    if not video:
        sys.stderr.write("  \x1b[31m✗ Video file is required.\x1b[0m\n")
        sys.exit(1)

    # Language selection
    lang_options = [f"{name} ({code})" for code, name in LANGUAGES]
    default_lang_idx = 0
    for i, (code, _) in enumerate(LANGUAGES):
        if code == config.get("language", "en"):
            default_lang_idx = i
            break
    lang_idx = _select_menu("Select audio language:", lang_options, default_lang_idx)
    language = LANGUAGES[lang_idx][0]

    # Translation (default to translate when source is not English)
    translate_options = ["No translation", "Translate to English"]
    if config.get("translate", "no") == "yes":
        translate_default = 1
    elif language != "en":
        translate_default = 1
    else:
        translate_default = 0
    translate_idx = _select_menu("Translation:", translate_options, translate_default)
    translate = translate_idx == 1

    # Segment size
    segment_options = ["60s — frequent progress updates", "120s — balanced (default)", "300s — minimal updates, best boundary handling"]
    segment_default = 1
    saved_seg = config.get("segment_size", "120")
    if saved_seg == "60":
        segment_default = 0
    elif saved_seg == "300":
        segment_default = 2
    else:
        segment_default = 1
    seg_idx = _select_menu("Segment size:", segment_options, segment_default)
    segment_size = [60, 120, 300][seg_idx]

    # Output path
    video_stem = Path(video).stem if video else "output"
    default_output = str(Path(video).parent / f"{video_stem}.srt") if video else ""
    output_dir = config.get("output_dir", "")
    if output_dir and Path(output_dir).is_dir():
        default_output = str(Path(output_dir) / f"{video_stem}.srt")
    output = _input_path("Output SRT path:", default=default_output, must_exist=False)

    # Whisper path
    whisper_path = _input_path("whisper-cli.exe path:", default=config.get("whisper_path", ""))

    # Model path
    model_path = _input_path("Model file (.bin) path:", default=config.get("model_path", ""))

    # FFmpeg path
    ffmpeg_path = _input_path("ffmpeg path:", default=config.get("ffmpeg_path", "ffmpeg"))

    return {
        "video": video,
        "language": language,
        "translate": translate,
        "segment_size": segment_size,
        "output": output,
        "whisper_path": whisper_path,
        "model_path": model_path,
        "ffmpeg_path": ffmpeg_path,
    }


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def extract_audio(ffmpeg_path: str, input_path: str, audio_path: str, logger: Logger,
                  start: float = None, duration: float = None):
    args = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
    if start is not None:
        h = int(start // 3600)
        m = int((start % 3600) // 60)
        s = start - h * 3600 - m * 60
        args += ["-ss", f"{h:02d}:{m:02d}:{s:06.3f}"]
    if duration is not None:
        args += ["-t", str(duration)]
    args += ["-i", input_path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", audio_path]
    logger.log(f"ffmpeg: {args}")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"ffmpeg failed: {err}")


def run_whisper(whisper_path: str, model_path: str, audio_path: str, output_base: str,
                language: str, translate: bool, logger: Logger) -> Path:
    args = [whisper_path, "-m", model_path, "-f", audio_path,
            "-l", language, "--output-srt", "--output-file", output_base]
    if translate:
        args.append("--translate")
    logger.log(f"whisper: {args}")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"whisper.cpp failed: {err}")
    srt_path = Path(f"{output_base}.srt")
    if not srt_path.exists():
        raise RuntimeError("whisper.cpp did not produce output SRT file")
    return srt_path


def generate_subtitles(media_path: str, output_srt: Path, whisper_path: str,
                      model_path: str, ffmpeg_path: str, language: str,
                      translate: bool, segment_size: int, logger: Logger):
    temp_dir = Path(tempfile.mkdtemp(prefix="subtitle_gen_"))
    try:
        # Extract full audio
        sys.stderr.write("  Extracting audio...\n")
        print_progress(5)
        audio_path = str(temp_dir / "full_audio.wav")
        extract_audio(ffmpeg_path, media_path, audio_path, logger)

        # Calculate duration from WAV file (16kHz, mono, 16-bit = 32000 bytes/sec)
        wav_size = os.path.getsize(audio_path)
        duration = (wav_size - 44) / 32000
        logger.log(f"Duration from WAV: {duration:.0f}s ({wav_size} bytes)")

        if duration <= 0:
            raise RuntimeError("Could not determine audio duration")

        print_progress(10)
        segment_count = math.ceil(duration / segment_size)
        sys.stderr.write(f"\n  Processing {segment_count} segment(s) ({duration:.0f}s total)...\n")

        if segment_count <= 1:
            # Short file: single pass
            output_base = str(temp_dir / "output")
            srt_path = run_whisper(whisper_path, model_path, audio_path,
                                   output_base, language, translate, logger)
            entries = parse_srt_file(srt_path)
            write_srt_file(output_srt, entries)
            print_progress(100)
        else:
            # Segmented processing
            all_entries = []
            for i in range(segment_count):
                offset = i * segment_size
                seg_duration = min(segment_size, duration - offset)
                progress = 10 + ((i + 1) / segment_count) * 85
                print_progress(progress)

                seg_audio = str(temp_dir / f"seg_{i}.wav")
                extract_audio(ffmpeg_path, audio_path, seg_audio, logger,
                              start=offset, duration=seg_duration)

                seg_output = str(temp_dir / f"seg_{i}")
                try:
                    srt_path = run_whisper(whisper_path, model_path, seg_audio,
                                           seg_output, language, translate, logger)
                except RuntimeError as e:
                    logger.log(f"Segment {i+1}/{segment_count} failed: {e}, skipping")
                    continue

                seg_entries = parse_srt_file(srt_path)
                all_entries.extend(offset_entries(seg_entries, offset))

                # Clean up segment files
                Path(seg_audio).unlink(missing_ok=True)
                srt_path.unlink(missing_ok=True)

            if not all_entries:
                raise RuntimeError("No subtitles were generated from any segment")

            write_srt_file(output_srt, all_entries)
            print_progress(100)

        clear_progress()
        sys.stderr.write("  Done!\n")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser(config: dict) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-cli",
        description="Generate subtitles for a video using whisper.cpp (local, no API key).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               '  subtitle-cli "video.mp4"\n'
               '  subtitle-cli "video.mp4" --language es --translate\n'
               '  subtitle-cli --interactive\n',
    )
    parser.add_argument("video", nargs="?", type=str, default=None,
                        help="Path to the video file (supports tab completion)")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Launch interactive mode with menus for all options")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("--whisper-path", default=config.get("whisper_path", ""),
                        help=f"Path to whisper-cli.exe (saved: {config.get('whisper_path') or 'not set'})")
    parser.add_argument("--model-path", default=config.get("model_path", ""),
                        help=f"Path to whisper model .bin (saved: {config.get('model_path') or 'not set'})")
    parser.add_argument("--ffmpeg-path", default=config.get("ffmpeg_path", "ffmpeg"),
                        help=f"Path to ffmpeg (saved: {config.get('ffmpeg_path', 'ffmpeg')})")
    parser.add_argument("--language", "-l", default=config.get("language", "en"),
                        help=f"Audio language code (saved: {config.get('language', 'en')})")
    parser.add_argument("--translate", "-t", action="store_true",
                        default=config.get("translate", "no") == "yes",
                        help="Translate to English subtitles")
    parser.add_argument("--segment-size", type=int,
                        default=int(config.get("segment_size", "120")),
                        help=f"Seconds per segment for progress (saved: {config.get('segment_size', '120')})")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output SRT file path (default: video name with .srt)")
    parser.add_argument("--output-dir", type=str, default=config.get("output_dir", ""),
                        help="Output directory for SRT file")
    return parser


def resolve_output_path(video_path: str, output: str, output_dir: str) -> Path:
    if output:
        return Path(output)
    video = Path(video_path)
    srt_name = video.stem + ".srt"
    if output_dir and Path(output_dir).is_dir():
        return Path(output_dir) / srt_name
    return video.parent / srt_name


def validate_paths(args, logger: Logger) -> list:
    errors = []
    if not Path(args.video).exists():
        errors.append(f"Video file not found: {args.video}")
    if not args.whisper_path:
        errors.append("whisper-cli path not set. Use --whisper-path or configure in settings.")
    elif not Path(args.whisper_path).exists():
        errors.append(f"whisper-cli not found: {args.whisper_path}")
    if not args.model_path:
        errors.append("Model path not set. Use --model-path or configure in settings.")
    elif not Path(args.model_path).exists():
        errors.append(f"Model file not found: {args.model_path}")
    if not shutil.which(args.ffmpeg_path) and not Path(args.ffmpeg_path).exists():
        errors.append(f"ffmpeg not found: {args.ffmpeg_path}")
    for e in errors:
        logger.log(f"VALIDATION ERROR: {e}")
    return errors


def _prompt_missing(args, config: dict):
    """Prompt interactively for any required values that are missing."""
    prompted = False

    if not args.video:
        if not prompted:
            sys.stderr.write("\n\x1b[1m  ── Missing parameters ──\x1b[0m\n\n")
            prompted = True
        args.video = _input_path("Video file path:", must_exist=True)
        if not args.video:
            sys.stderr.write("  \x1b[31m✗ Video file is required.\x1b[0m\n")
            sys.exit(1)

    if not args.whisper_path or not Path(args.whisper_path).exists():
        if not prompted:
            sys.stderr.write("\n\x1b[1m  ── Missing parameters ──\x1b[0m\n\n")
            prompted = True
        args.whisper_path = _input_path(
            "whisper-cli.exe path:", default=config.get("whisper_path", ""))

    if not args.model_path or not Path(args.model_path).exists():
        if not prompted:
            sys.stderr.write("\n\x1b[1m  ── Missing parameters ──\x1b[0m\n\n")
            prompted = True
        args.model_path = _input_path(
            "Model file (.bin) path:", default=config.get("model_path", ""))

    if not shutil.which(args.ffmpeg_path) and not Path(args.ffmpeg_path).exists():
        if not prompted:
            sys.stderr.write("\n\x1b[1m  ── Missing parameters ──\x1b[0m\n\n")
            prompted = True
        args.ffmpeg_path = _input_path(
            "ffmpeg path:", default=config.get("ffmpeg_path", "ffmpeg"))

    if prompted:
        sys.stderr.write("\n")


def main():
    config = load_config()
    parser = build_parser(config)
    args = parser.parse_args()

    # Full interactive mode: prompt for everything
    if args.interactive:
        opts = run_interactive(config)
        args.video = opts["video"]
        args.language = opts["language"]
        args.translate = opts["translate"]
        args.segment_size = opts["segment_size"]
        args.whisper_path = opts["whisper_path"]
        args.model_path = opts["model_path"]
        args.ffmpeg_path = opts["ffmpeg_path"]
        args.output = opts["output"]
        args.output_dir = ""
    else:
        # Prompt for any missing required values
        _prompt_missing(args, config)

    try:
        output_srt = resolve_output_path(args.video, args.output, args.output_dir)
    except Exception:
        output_srt = Path(args.video).with_suffix(".srt") if args.video else Path("output.srt")
    logger = Logger(output_srt=str(output_srt))
    sys.stderr.write(f"  Log: {logger.log_path}\n")

    logger.log(f"Subtitle Generator CLI v{__version__}")
    logger.log(f"Video: {args.video}")
    logger.log(f"Output: {output_srt}")
    logger.log(f"Whisper: {args.whisper_path}")
    logger.log(f"Model: {args.model_path}")
    logger.log(f"FFmpeg: {args.ffmpeg_path}")
    logger.log(f"Language: {args.language}, Translate: {args.translate}, Segment: {args.segment_size}s")

    try:
        errors = validate_paths(args, logger)
        if errors:
            sys.stderr.write("Error:\n")
            for e in errors:
                sys.stderr.write(f"  \u2022 {e}\n")
            sys.stderr.write(f"\nLog: {logger.log_path}\n")
            print(str(output_srt))
            return 1

        sys.stderr.write(f"Subtitle Generator v{__version__}\n")
        sys.stderr.write(f"  Input:  {args.video}\n")
        sys.stderr.write(f"  Output: {output_srt}\n\n")

        generate_subtitles(
            media_path=args.video,
            output_srt=output_srt,
            whisper_path=args.whisper_path,
            model_path=args.model_path,
            ffmpeg_path=args.ffmpeg_path,
            language=args.language,
            translate=args.translate,
            segment_size=args.segment_size,
            logger=logger,
        )

        logger.log("Completed successfully")
        save_config(args)
        sys.stderr.write(f"\n  Log: {logger.log_path}\n")
        print(str(output_srt))
        return 0

    except KeyboardInterrupt:
        clear_progress()
        logger.log("Cancelled by user")
        sys.stderr.write("\n  Cancelled.\n")
        sys.stderr.write(f"  Log: {logger.log_path}\n")
        print(str(output_srt))
        return 130

    except Exception as e:
        clear_progress()
        logger.log(f"FATAL: {e}")
        sys.stderr.write(f"\n  Failed: {e}\n")
        sys.stderr.write(f"  Log: {logger.log_path}\n")
        print(str(output_srt))
        return 1

    finally:
        logger.close()


if __name__ == "__main__":
    sys.exit(main())
