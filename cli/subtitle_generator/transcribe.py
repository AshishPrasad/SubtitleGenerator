"""Core processing: audio extraction, whisper invocation, segmentation pipeline."""

import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .logging_ import Logger
from .progress import clear_progress, print_progress
from .srt import (
    offset_entries,
    parse_srt_file,
    parse_srt_timestamp,
    postprocess_entries,
    write_srt_file,
)

# Context padding extracted around each segment so whisper has cross-boundary
# context (fixes garbled/incorrect transcription at segment boundaries).
SEGMENT_OVERLAP_SECONDS = 3.0


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
            "-l", language, "--output-srt", "--output-file", output_base,
            "--max-context", "0"]
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
            entries = postprocess_entries(entries)
            write_srt_file(output_srt, entries)
            print_progress(100)
        else:
            # Segmented processing with overlap for accurate boundaries
            all_entries = []
            for i in range(segment_count):
                offset = i * segment_size
                seg_duration = min(segment_size, duration - offset)
                progress = 10 + ((i + 1) / segment_count) * 85
                print_progress(progress)

                # Extract with overlap padding so whisper has cross-boundary context
                clip_start = max(0.0, offset - SEGMENT_OVERLAP_SECONDS)
                clip_end = min(duration, offset + seg_duration + SEGMENT_OVERLAP_SECONDS)
                clip_duration = clip_end - clip_start

                seg_audio = str(temp_dir / f"seg_{i}.wav")
                extract_audio(ffmpeg_path, audio_path, seg_audio, logger,
                              start=clip_start, duration=clip_duration)

                seg_output = str(temp_dir / f"seg_{i}")
                try:
                    srt_path = run_whisper(whisper_path, model_path, seg_audio,
                                           seg_output, language, translate, logger)
                except RuntimeError as e:
                    logger.log(f"Segment {i+1}/{segment_count} failed: {e}, skipping")
                    continue

                # Shift timestamps to absolute time (relative to clip start)
                seg_entries = offset_entries(parse_srt_file(srt_path), clip_start)

                # Commit only captions whose start falls in this segment's owned
                # window; the overlap regions are context-only and are owned by the
                # adjacent segments, which avoids duplicated boundary captions.
                owned_start = 0.0 if i == 0 else offset
                owned_end = float("inf") if i == segment_count - 1 else offset + seg_duration
                for e in seg_entries:
                    cs = parse_srt_timestamp(e["start"])
                    if owned_start - 1e-3 <= cs < owned_end:
                        all_entries.append(e)

                # Clean up segment files
                Path(seg_audio).unlink(missing_ok=True)
                srt_path.unlink(missing_ok=True)

            if not all_entries:
                raise RuntimeError("No subtitles were generated from any segment")

            all_entries = postprocess_entries(all_entries)
            write_srt_file(output_srt, all_entries)
            print_progress(100)

        clear_progress()
        sys.stderr.write("  Done!\n")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
