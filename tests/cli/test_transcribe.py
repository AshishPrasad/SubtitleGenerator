"""End-to-end tests for the segmentation pipeline in subtitle_generator.transcribe.

These mock ffmpeg (`extract_audio`), whisper (`run_whisper`), and the WAV-size
probe so the full `generate_subtitles` flow — segmentation, overlap extraction,
the owned-window commit, and the post-processing cleanup — can be exercised
without any external binaries, at realistic multi-hour durations.

The key property verified: a caption is committed exactly once regardless of how
many overlapping segments transcribe it (no drops, no duplicates at boundaries).
"""

import os
import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from unittest import mock

import _support  # noqa: F401  (sets up sys.path)
from subtitle_generator import srt, transcribe

WAV_BYTES_PER_SEC = 32000  # 16kHz mono 16-bit
WAV_HEADER = 44


class _FakeLogger:
    def log(self, msg):
        pass


def _owner_clip_start(t: float, segment_size: int) -> float:
    """The clip_start of the segment that OWNS time t (= the segment whose
    owned window [i*S, (i+1)*S) contains t). Mirrors generate_subtitles."""
    i = int(t // segment_size)
    return max(0.0, i * segment_size - transcribe.SEGMENT_OVERLAP_SECONDS)


def _ground_truth_times(duration: float, segment_size: int) -> list:
    """Caption times across the whole timeline, densely covering segment
    boundaries (and the points just before/after them) where overlap-induced
    duplicates would otherwise appear."""
    times = set()
    t = 30.0
    while t < duration - 2:
        times.add(round(t, 3))
        t += 30.0
    # Add every interior segment boundary and its immediate neighbours.
    b = segment_size
    while b < duration - 2:
        for cand in (b - 1.0, float(b), b + 1.0):
            if 1.0 <= cand < duration - 2:
                times.add(round(cand, 3))
        b += segment_size
    return sorted(times)


def _run_pipeline(duration: float, segment_size: int):
    """Run generate_subtitles with mocked ffmpeg/whisper at the given duration.
    Returns (parsed_output_entries, ground_truth_times)."""
    gt = _ground_truth_times(duration, segment_size)
    clip_bounds = {}  # audio_path -> (start, duration)

    def fake_extract(ffmpeg_path, input_path, audio_path, logger, start=None, duration=None):
        Path(audio_path).write_bytes(b"\0")
        if start is None:
            clip_bounds[audio_path] = (0.0, globals()["_target_duration"])
        else:
            clip_bounds[audio_path] = (float(start), float(duration))

    def fake_whisper(whisper_path, model_path, audio_path, output_base,
                     language, translate, logger):
        clip_start, clip_dur = clip_bounds[audio_path]
        clip_end = clip_start + clip_dur
        entries = []
        for t in gt:
            if clip_start - 1e-9 <= t < clip_end - 1e-9:
                rel = t - clip_start
                # Encode the emitting segment (its clip_start) into the text so a
                # caption transcribed by two overlapping segments yields DISTINCT
                # text — postprocess can't merge it, so only the owned-window
                # commit prevents a duplicate.
                entries.append({
                    "start": srt.format_srt_timestamp(rel),
                    "end": srt.format_srt_timestamp(rel + 1.0),
                    "text": f"cap@{t:.3f}|clip{clip_start:.1f}",
                })
        out = Path(f"{output_base}.srt")
        srt.write_srt_file(out, entries)
        return out

    real_getsize = os.path.getsize

    def fake_getsize(path):
        if str(path).endswith("full_audio.wav"):
            return int(duration * WAV_BYTES_PER_SEC) + WAV_HEADER
        return real_getsize(path)

    globals()["_target_duration"] = duration
    out_dir = tempfile.mkdtemp(prefix="sg_pipe_test_")
    output_srt = Path(out_dir) / "out.srt"
    try:
        with mock.patch.object(transcribe, "extract_audio", fake_extract), \
             mock.patch.object(transcribe, "run_whisper", fake_whisper), \
             mock.patch.object(transcribe.os.path, "getsize", fake_getsize), \
             contextlib.redirect_stderr(io.StringIO()):
            transcribe.generate_subtitles(
                media_path="movie.mp4",
                output_srt=output_srt,
                whisper_path="whisper",
                model_path="model",
                ffmpeg_path="ffmpeg",
                language="en",
                translate=False,
                segment_size=segment_size,
                logger=_FakeLogger(),
            )
        return srt.parse_srt_file(output_srt), gt
    finally:
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)


class MultiHourPipelineTests(unittest.TestCase):
    DURATIONS = {
        "1h": 3600,
        "2h": 7200,
        "3h": 10800,
        "4h": 14400,
        "5h": 18000,
    }
    SEGMENT_SIZE = 120

    def _check(self, duration):
        entries, gt = _run_pipeline(float(duration), self.SEGMENT_SIZE)
        texts = [e["text"] for e in entries]

        # Expected: each caption committed exactly once, by its OWNING segment.
        expected = {f"cap@{t:.3f}|clip{_owner_clip_start(t, self.SEGMENT_SIZE):.1f}" for t in gt}

        # 1) Every ground-truth caption appears exactly once (no drop, no dup),
        #    and from the correct owning segment (proves the owned-window commit).
        self.assertEqual(len(texts), len(gt), "caption count mismatch")
        self.assertEqual(set(texts), expected, "wrong owner / missing / duplicate caption")
        self.assertEqual(len(texts), len(set(texts)), "duplicate captions present")

        # 2) Output is sorted and non-overlapping with positive durations.
        starts = [srt.parse_srt_timestamp(e["start"]) for e in entries]
        ends = [srt.parse_srt_timestamp(e["end"]) for e in entries]
        self.assertEqual(starts, sorted(starts), "output not sorted by start")
        for i in range(len(entries)):
            self.assertGreater(ends[i], starts[i], "non-positive caption duration")
            if i + 1 < len(entries):
                self.assertLessEqual(ends[i], starts[i + 1], "captions overlap")

    def test_1_hour(self):
        self._check(self.DURATIONS["1h"])

    def test_2_hours(self):
        self._check(self.DURATIONS["2h"])

    def test_3_hours(self):
        self._check(self.DURATIONS["3h"])

    def test_4_hours(self):
        self._check(self.DURATIONS["4h"])

    def test_5_hours(self):
        self._check(self.DURATIONS["5h"])

    def test_segment_count_matches_ceil(self):
        import math
        for duration in self.DURATIONS.values():
            calls = []

            def fake_extract(ffmpeg_path, input_path, audio_path, logger, start=None, duration=None):
                Path(audio_path).write_bytes(b"\0")
                if start is not None:
                    calls.append(start)

            def fake_whisper(whisper_path, model_path, audio_path, output_base,
                             language, translate, logger):
                out = Path(f"{output_base}.srt")
                srt.write_srt_file(out, [])
                return out

            real_getsize = os.path.getsize

            def fake_getsize(path, _d=duration):
                if str(path).endswith("full_audio.wav"):
                    return int(_d * WAV_BYTES_PER_SEC) + WAV_HEADER
                return real_getsize(path)

            out_dir = tempfile.mkdtemp(prefix="sg_cnt_test_")
            try:
                with mock.patch.object(transcribe, "extract_audio", fake_extract), \
                     mock.patch.object(transcribe, "run_whisper", fake_whisper), \
                     mock.patch.object(transcribe.os.path, "getsize", fake_getsize), \
                     contextlib.redirect_stderr(io.StringIO()):
                    try:
                        transcribe.generate_subtitles(
                            media_path="m.mp4",
                            output_srt=Path(out_dir) / "o.srt",
                            whisper_path="w", model_path="m", ffmpeg_path="f",
                            language="en", translate=False,
                            segment_size=self.SEGMENT_SIZE, logger=_FakeLogger(),
                        )
                    except RuntimeError:
                        pass  # empty captions -> "no subtitles" is fine for counting
                expected = math.ceil(duration / self.SEGMENT_SIZE)
                self.assertEqual(len(calls), expected,
                                 f"{duration}s -> expected {expected} segments, got {len(calls)}")
            finally:
                import shutil
                shutil.rmtree(out_dir, ignore_errors=True)


class ShortFilePipelineTests(unittest.TestCase):
    def test_single_pass_under_one_segment(self):
        # Duration below segment_size uses the single-pass branch (no segmentation).
        entries, gt = _run_pipeline(90.0, 120)
        texts = sorted(e["text"] for e in entries)
        self.assertEqual(texts, sorted(f"cap@{t:.3f}|clip0.0" for t in gt))


if __name__ == "__main__":
    unittest.main()
