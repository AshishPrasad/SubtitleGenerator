"""SRT parsing, writing, and caption cleanup (core logic, no UI/IO side effects)."""

import re
from pathlib import Path

# Tuning constants for hallucination / boundary cleanup
MAX_CAPTION_SECONDS = 10.0      # hard cap so a stuck/hallucinated caption can't linger
MIN_CAPTION_SECONDS = 0.2
DUPLICATE_GAP_SECONDS = 0.5     # consecutive identical text within this gap = repetition


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


def postprocess_entries(entries: list) -> list:
    """Clean up parsed SRT entries to fix the two common whisper artifacts:

    - Repetition loops (the same caption emitted over and over on silence/music)
      are collapsed by merging contiguous identical captions.
    - Overlapping captions are removed by trimming the previous caption's end to
      the next caption's start.
    - Over-long ("stuck") captions are clamped to MAX_CAPTION_SECONDS so a single
      hallucinated caption cannot linger for an extended duration.
    """
    items = []
    for e in entries:
        text = e["text"].strip()
        if not text:
            continue
        items.append({
            "start": parse_srt_timestamp(e["start"]),
            "end": parse_srt_timestamp(e["end"]),
            "text": text,
        })
    items.sort(key=lambda x: (x["start"], x["end"]))

    cleaned = []
    for it in items:
        if it["end"] <= it["start"]:
            it["end"] = it["start"] + MIN_CAPTION_SECONDS
        if cleaned:
            prev = cleaned[-1]
            # Merge a contiguous run of identical captions (repetition loop on
            # silence/music) into a single caption by extending the previous end.
            if it["text"] == prev["text"] and it["start"] <= prev["end"] + DUPLICATE_GAP_SECONDS:
                prev["end"] = max(prev["end"], it["end"])
                continue
            # No overlapping captions: trim the previous one to this start
            if prev["end"] > it["start"]:
                prev["end"] = it["start"]
        cleaned.append(it)

    # Clamp over-long captions (stuck subtitle / hallucinated span)
    for it in cleaned:
        if it["end"] - it["start"] > MAX_CAPTION_SECONDS:
            it["end"] = it["start"] + MAX_CAPTION_SECONDS

    # Final ordering/overlap safety pass
    for i in range(len(cleaned) - 1):
        if cleaned[i]["end"] > cleaned[i + 1]["start"]:
            cleaned[i]["end"] = cleaned[i + 1]["start"]
        if cleaned[i]["end"] <= cleaned[i]["start"]:
            cleaned[i]["end"] = cleaned[i]["start"] + 0.05

    return [{
        "start": format_srt_timestamp(it["start"]),
        "end": format_srt_timestamp(it["end"]),
        "text": it["text"],
    } for it in cleaned]


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
