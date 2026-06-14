"""Tests for subtitle_generator.config — defaults and load/save round-trip."""

import os
import tempfile
import types
import unittest

import _support  # noqa: F401  (sets up sys.path)
from subtitle_generator import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="sg_cfg_test_")
        self._old_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp

    def tearDown(self):
        if self._old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._old_appdata
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_config_path_under_appdata(self):
        path = config.get_config_path()
        self.assertTrue(str(path).startswith(self._tmp))
        self.assertEqual(path.name, "config.txt")

    def test_load_returns_defaults_when_missing(self):
        cfg = config.load_config()
        self.assertEqual(cfg["ffmpeg_path"], "ffmpeg")
        self.assertEqual(cfg["language"], "en")
        self.assertEqual(cfg["segment_size"], "120")

    def test_save_then_load_round_trip(self):
        args = types.SimpleNamespace(
            whisper_path=r"C:\w\whisper-cli.exe",
            model_path=r"C:\w\model.bin",
            ffmpeg_path="ffmpeg",
            language="es",
            translate=True,
            segment_size=300,
            output_dir=r"C:\out",
        )
        config.save_config(args)
        cfg = config.load_config()
        self.assertEqual(cfg["whisper_path"], r"C:\w\whisper-cli.exe")
        self.assertEqual(cfg["model_path"], r"C:\w\model.bin")
        self.assertEqual(cfg["language"], "es")
        self.assertEqual(cfg["translate"], "yes")
        self.assertEqual(cfg["segment_size"], "300")
        self.assertEqual(cfg["output_dir"], r"C:\out")

    def test_unknown_keys_ignored(self):
        config.get_config_path().parent.mkdir(parents=True, exist_ok=True)
        config.get_config_path().write_text(
            "language=fr\nbogus_key=whatever\n", encoding="utf-8"
        )
        cfg = config.load_config()
        self.assertEqual(cfg["language"], "fr")
        self.assertNotIn("bogus_key", cfg)


if __name__ == "__main__":
    unittest.main()
