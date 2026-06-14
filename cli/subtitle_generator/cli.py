"""Command-line interface: argument parsing, validation, and the main() entry point."""

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import load_config, save_config
from .interactive import _input_path, run_interactive
from .logging_ import Logger
from .progress import clear_progress
from .transcribe import generate_subtitles


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
