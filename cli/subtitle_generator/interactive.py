"""Interactive mode: arrow-key menus and prompts (UI)."""

import sys
from pathlib import Path

from .languages import LANGUAGES


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
