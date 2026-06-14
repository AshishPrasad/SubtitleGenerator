"""Tests for subtitle_generator.srt — timestamps, parsing, and caption cleanup."""

import os
import tempfile
import unittest
from pathlib import Path

import _support  # noqa: F401  (sets up sys.path)
from subtitle_generator import srt


def _fmt(seconds: float) -> str:
    return srt.format_srt_timestamp(seconds)


class TimestampTests(unittest.TestCase):
    def test_parse_basic(self):
        self.assertAlmostEqual(srt.parse_srt_timestamp("01:02:03,500"), 3723.5, places=3)

    def test_parse_accepts_dot_separator(self):
        self.assertAlmostEqual(srt.parse_srt_timestamp("00:00:01.250"), 1.25, places=3)

    def test_parse_invalid_returns_zero(self):
        self.assertEqual(srt.parse_srt_timestamp("not a timestamp"), 0.0)

    def test_format_basic(self):
        self.assertEqual(srt.format_srt_timestamp(3723.5), "01:02:03,500")

    def test_round_trip(self):
        for value in (0.0, 1.001, 59.999, 3600.25, 7325.123):
            again = srt.parse_srt_timestamp(srt.format_srt_timestamp(value))
            self.assertAlmostEqual(again, value, places=3)


class ParseSrtFileTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        fd, name = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        path = Path(name)
        path.write_text(text, encoding="utf-8")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_parses_entries_and_filters_blank(self):
        content = (
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\n[BLANK_AUDIO]\n\n"
            "3\n00:00:02,000 --> 00:00:03,000\nWorld\n\n"
        )
        entries = srt.parse_srt_file(self._write(content))
        self.assertEqual([e["text"] for e in entries], ["Hello", "World"])

    def test_missing_file_returns_empty(self):
        self.assertEqual(srt.parse_srt_file(Path("does_not_exist.srt")), [])

    def test_multiline_text_joined(self):
        content = "1\n00:00:00,000 --> 00:00:02,000\nline one\nline two\n\n"
        entries = srt.parse_srt_file(self._write(content))
        self.assertEqual(entries[0]["text"], "line one\nline two")


class OffsetTests(unittest.TestCase):
    def test_offset_shifts_both_ends(self):
        entries = [{"start": "00:00:01,000", "end": "00:00:02,000", "text": "x"}]
        out = srt.offset_entries(entries, 10.0)
        self.assertEqual(out[0]["start"], "00:00:11,000")
        self.assertEqual(out[0]["end"], "00:00:12,000")


class PostprocessTests(unittest.TestCase):
    def _entries(self, triples):
        return [{"start": _fmt(s), "end": _fmt(e), "text": t} for s, e, t in triples]

    def test_repetition_loop_collapses_and_clamps(self):
        # 8 contiguous identical captions over 16s -> single caption clamped to MAX
        triples = [(10 + 2 * i, 12 + 2 * i, "Thank you.") for i in range(8)]
        out = srt.postprocess_entries(self._entries(triples))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["start"], "00:00:10,000")
        dur = srt.parse_srt_timestamp(out[0]["end"]) - srt.parse_srt_timestamp(out[0]["start"])
        self.assertLessEqual(dur, srt.MAX_CAPTION_SECONDS + 1e-6)

    def test_stuck_caption_is_clamped(self):
        out = srt.postprocess_entries(self._entries([(60, 120, "[Music]")]))
        dur = srt.parse_srt_timestamp(out[0]["end"]) - srt.parse_srt_timestamp(out[0]["start"])
        self.assertAlmostEqual(dur, srt.MAX_CAPTION_SECONDS, places=3)

    def test_overlapping_captions_are_trimmed(self):
        out = srt.postprocess_entries(self._entries([
            (0, 5, "Hello there"),
            (3, 7, "general kenobi"),
        ]))
        self.assertEqual(len(out), 2)
        # previous caption end must not exceed next caption start
        self.assertLessEqual(
            srt.parse_srt_timestamp(out[0]["end"]),
            srt.parse_srt_timestamp(out[1]["start"]),
        )

    def test_distinct_captions_unchanged(self):
        triples = [(1, 3, "one"), (4, 6, "two")]
        out = srt.postprocess_entries(self._entries(triples))
        self.assertEqual([(e["start"], e["end"], e["text"]) for e in out], [
            ("00:00:01,000", "00:00:03,000", "one"),
            ("00:00:04,000", "00:00:06,000", "two"),
        ])

    def test_blank_text_dropped(self):
        out = srt.postprocess_entries(self._entries([(1, 2, "   "), (3, 4, "kept")]))
        self.assertEqual([e["text"] for e in out], ["kept"])

    def test_out_of_order_input_is_sorted(self):
        out = srt.postprocess_entries(self._entries([(5, 6, "b"), (1, 2, "a")]))
        self.assertEqual([e["text"] for e in out], ["a", "b"])

    def test_output_sorted_by_actual_timestamps(self):
        import random
        triples = [(i * 5, i * 5 + 2, f"c{i:02d}") for i in range(20)]
        shuffled = triples[:]
        random.Random(42).shuffle(shuffled)
        out = srt.postprocess_entries(self._entries(shuffled))
        starts = [srt.parse_srt_timestamp(e["start"]) for e in out]
        self.assertEqual(starts, sorted(starts), "starts not monotonically sorted")
        self.assertEqual([e["text"] for e in out], [f"c{i:02d}" for i in range(20)])

    def test_no_caption_overlaps_in_output(self):
        out = srt.postprocess_entries(self._entries([
            (0, 4, "a"), (2, 6, "b"), (5, 9, "c"),
        ]))
        for i in range(len(out) - 1):
            self.assertLessEqual(
                srt.parse_srt_timestamp(out[i]["end"]),
                srt.parse_srt_timestamp(out[i + 1]["start"]),
            )

    def test_no_caption_exceeds_max_duration(self):
        # Mixed input incl. several over-long captions: none may exceed the cap.
        out = srt.postprocess_entries(self._entries([
            (0, 2, "ok"), (5, 45, "long1"), (50, 53, "ok2"), (60, 600, "long2"),
        ]))
        for e in out:
            dur = srt.parse_srt_timestamp(e["end"]) - srt.parse_srt_timestamp(e["start"])
            self.assertLessEqual(dur, srt.MAX_CAPTION_SECONDS + 1e-6, f"{e['text']} too long")

    def test_caption_not_stretched_across_silent_gap(self):
        # Two utterances with a long silent gap between them: the first caption
        # must keep its own (short) end and NOT linger into the silence up to the
        # next caption's start.
        out = srt.postprocess_entries(self._entries([(1, 3, "hello"), (50, 52, "world")]))
        first = next(e for e in out if e["text"] == "hello")
        self.assertEqual(first["end"], "00:00:03,000")
        gap = srt.parse_srt_timestamp(out[1]["start"]) - srt.parse_srt_timestamp(out[0]["end"])
        self.assertGreater(gap, 40, "silent gap was filled by an elongated caption")


class MultiHourTimestampTests(unittest.TestCase):
    def test_format_at_each_hour(self):
        for h in range(1, 6):
            self.assertEqual(srt.format_srt_timestamp(h * 3600), f"{h:02d}:00:00,000")

    def test_hour_boundary_rounding(self):
        self.assertEqual(srt.format_srt_timestamp(3599.999), "00:59:59,999")
        self.assertEqual(srt.format_srt_timestamp(3600.0), "01:00:00,000")
        self.assertEqual(srt.format_srt_timestamp(5 * 3600 - 0.001), "04:59:59,999")

    def test_round_trip_multi_hour(self):
        for h in range(1, 6):
            for extra in (0.0, 0.123, 59.5, 1234.567, 3599.999):
                value = h * 3600 + extra
                back = srt.parse_srt_timestamp(srt.format_srt_timestamp(value))
                self.assertAlmostEqual(back, value, places=3)

    def test_parse_multi_hour(self):
        self.assertAlmostEqual(srt.parse_srt_timestamp("05:00:00,000"), 18000.0, places=3)
        self.assertAlmostEqual(srt.parse_srt_timestamp("03:30:15,250"), 3 * 3600 + 1815.25, places=3)


class WriteSrtTests(unittest.TestCase):
    def test_write_round_trips_through_parse(self):
        entries = [
            {"start": "00:00:00,000", "end": "00:00:01,000", "text": "a"},
            {"start": "00:00:01,000", "end": "00:00:02,000", "text": "b"},
        ]
        fd, name = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        path = Path(name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        srt.write_srt_file(path, entries)
        parsed = srt.parse_srt_file(path)
        self.assertEqual([e["text"] for e in parsed], ["a", "b"])

    def test_write_uses_sequential_indices(self):
        entries = [
            {"start": "00:00:00,000", "end": "00:00:01,000", "text": "a"},
            {"start": "00:00:01,000", "end": "00:00:02,000", "text": "b"},
            {"start": "00:00:02,000", "end": "00:00:03,000", "text": "c"},
        ]
        fd, name = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        path = Path(name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        srt.write_srt_file(path, entries)
        blocks = [b for b in path.read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
        indices = [int(b.splitlines()[0]) for b in blocks]
        self.assertEqual(indices, [1, 2, 3])


class FinalFileTests(unittest.TestCase):
    """The whole point of the cleanup: after postprocess + write, the produced
    .srt FILE is sorted, has no overlapping timestamp ranges, is deduped, drops
    blanks, clamps stuck captions, and uses sequential 1..N indices."""

    @staticmethod
    def _e(start, end, text):
        return {"start": srt.format_srt_timestamp(start),
                "end": srt.format_srt_timestamp(end), "text": text}

    def _build_messy(self):
        # Deliberately unsorted, overlapping, duplicated, blank, and stuck input.
        return [
            self._e(14, 16, "Thank you."),   # part of a repetition run
            self._e(10, 12, "Thank you."),
            self._e(12, 14, "Thank you."),
            self._e(3, 7, "World"),          # overlaps "Hello"
            self._e(0, 5, "Hello"),
            self._e(60, 120, "[Music]"),     # 60s "stuck" caption
            self._e(2, 3, "   "),            # blank -> dropped
            self._e(40, 42, "mid"),
        ]

    def test_written_file_is_sorted_nonoverlapping_deduped(self):
        cleaned = srt.postprocess_entries(self._build_messy())
        fd, name = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        path = Path(name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        srt.write_srt_file(path, cleaned)

        raw = path.read_text(encoding="utf-8")
        parsed = srt.parse_srt_file(path)

        # No blank captions survive
        self.assertTrue(all(e["text"].strip() for e in parsed))

        # The repetition run is deduped to a single "Thank you."
        self.assertEqual(sum(1 for e in parsed if e["text"] == "Thank you."), 1)

        starts = [srt.parse_srt_timestamp(e["start"]) for e in parsed]
        ends = [srt.parse_srt_timestamp(e["end"]) for e in parsed]

        # Sorted by start, every range positive, and NO overlapping ranges.
        self.assertEqual(starts, sorted(starts), "file not sorted by start")
        for i in range(len(parsed)):
            self.assertGreater(ends[i], starts[i], "non-positive timestamp range")
            if i + 1 < len(parsed):
                self.assertLessEqual(ends[i], starts[i + 1], "overlapping timestamp ranges")

        # The 60s "stuck" caption is clamped.
        music = next(e for e in parsed if e["text"] == "[Music]")
        dur = srt.parse_srt_timestamp(music["end"]) - srt.parse_srt_timestamp(music["start"])
        self.assertLessEqual(dur, srt.MAX_CAPTION_SECONDS + 1e-6)

        # Sequential 1..N indices in the file.
        blocks = [b for b in raw.strip().split("\n\n") if b.strip()]
        indices = [int(b.splitlines()[0]) for b in blocks]
        self.assertEqual(indices, list(range(1, len(parsed) + 1)))


if __name__ == "__main__":
    unittest.main()
