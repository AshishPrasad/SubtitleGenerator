"""Tests for subtitle_generator.cli — parser, output resolution, validation."""

import os
import tempfile
import types
import unittest
from pathlib import Path

import _support  # noqa: F401  (sets up sys.path)
from subtitle_generator import cli
from subtitle_generator.config import DEFAULT_CONFIG


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg):
        self.messages.append(msg)


class ParserTests(unittest.TestCase):
    def _parser(self):
        return cli.build_parser(dict(DEFAULT_CONFIG))

    def test_defaults(self):
        args = self._parser().parse_args(["video.mp4"])
        self.assertEqual(args.video, "video.mp4")
        self.assertFalse(args.translate)
        self.assertEqual(args.language, "en")
        self.assertEqual(args.segment_size, 120)

    def test_flags(self):
        args = self._parser().parse_args(
            ["v.mp4", "--language", "es", "--translate", "--segment-size", "300"]
        )
        self.assertEqual(args.language, "es")
        self.assertTrue(args.translate)
        self.assertEqual(args.segment_size, 300)

    def test_short_flags(self):
        args = self._parser().parse_args(["v.mp4", "-l", "fr", "-t", "-o", "out.srt"])
        self.assertEqual(args.language, "fr")
        self.assertTrue(args.translate)
        self.assertEqual(args.output, "out.srt")

    def test_interactive_without_video(self):
        args = self._parser().parse_args(["--interactive"])
        self.assertTrue(args.interactive)
        self.assertIsNone(args.video)


class ResolveOutputTests(unittest.TestCase):
    def test_explicit_output_wins(self):
        out = cli.resolve_output_path(r"C:\videos\v.mp4", "custom.srt", "")
        self.assertEqual(out, Path("custom.srt"))

    def test_default_is_sibling_of_video(self):
        out = cli.resolve_output_path(os.path.join("dir", "movie.mkv"), None, "")
        self.assertEqual(out, Path("dir") / "movie.srt")

    def test_output_dir_used_when_exists(self):
        tmp = tempfile.mkdtemp(prefix="sg_out_")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        out = cli.resolve_output_path(os.path.join("x", "clip.mp4"), None, tmp)
        self.assertEqual(out, Path(tmp) / "clip.srt")


class ValidateTests(unittest.TestCase):
    def _tmpfile(self, suffix=""):
        fd, name = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(name) and os.remove(name))
        return name

    def test_missing_paths_report_errors(self):
        args = types.SimpleNamespace(
            video="no_such_video.mp4",
            whisper_path="",
            model_path="",
            ffmpeg_path="definitely_not_a_real_ffmpeg_binary_xyz",
        )
        errors = cli.validate_paths(args, _FakeLogger())
        joined = " | ".join(errors)
        self.assertIn("Video file not found", joined)
        self.assertIn("whisper-cli path not set", joined)
        self.assertIn("Model path not set", joined)
        self.assertIn("ffmpeg not found", joined)

    def test_valid_paths_have_no_errors(self):
        video = self._tmpfile(".mp4")
        whisper = self._tmpfile(".exe")
        model = self._tmpfile(".bin")
        ffmpeg = self._tmpfile(".exe")
        args = types.SimpleNamespace(
            video=video,
            whisper_path=whisper,
            model_path=model,
            ffmpeg_path=ffmpeg,
        )
        self.assertEqual(cli.validate_paths(args, _FakeLogger()), [])


if __name__ == "__main__":
    unittest.main()
