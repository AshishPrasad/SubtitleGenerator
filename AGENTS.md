# Agent Instructions

Guidance for coding agents working in this repo. Keep changes surgical and verified.

## What this is

Offline subtitle generator (whisper.cpp + ffmpeg) with two front-ends:

- **Python CLI** — `cli/` (Windows, Python 3.8+, **stdlib only**, no external packages).
- **VLC extension** — `vlc-extension/` (Lua UI + PowerShell backend).

## Repo map

| Path | Role |
|------|------|
| `cli/subtitle_cli.py` | Thin backward-compatible shim → `subtitle_generator.cli:main`. |
| `cli/subtitle_generator/` | Package. **Core:** `config`, `srt`, `transcribe`, `logging_`. **UI/usage:** `cli`, `interactive`, `progress`, `languages`. |
| `vlc-extension/subtitle_generator.lua` | Entry: VLC hooks; `dofile`-loads the modules below. |
| `vlc-extension/sg_core.lua` / `sg_ui.lua` | Core logic / dialogs. |
| `vlc-extension/generate_subtitles.ps1` | PowerShell backend (ffmpeg + whisper). |
| `tests/cli/` · `tests/vlc-extension/` | Tests (see below). |

## Critical convention: keep the two pipelines in sync

The subtitle-generation logic is **duplicated** in `cli/subtitle_generator/transcribe.py` + `srt.py` (Python) and `vlc-extension/generate_subtitles.ps1` (PowerShell). **Any change to one must be mirrored in the other**, or behavior diverges.

The shared pipeline:
1. Extract 16 kHz mono WAV via ffmpeg; derive duration from WAV size.
2. Segment with **overlap padding** (`SEGMENT_OVERLAP_SECONDS`) for cross-boundary context.
3. Run whisper with **`--max-context 0`** (stops repetition loops).
4. **Owned-window commit**: keep only captions whose start is in `[ownedStart, ownedEnd)` — first segment owns from 0, last segment owns to ∞ — so overlap regions aren't duplicated.
5. **Post-process** (`postprocess_entries` / `Postprocess-Entries`): merge contiguous duplicate captions, trim overlaps, clamp over-long "stuck" captions, drop blank/`[BLANK_AUDIO]` captions, sort, sequential `1..N` indices.

Other shared defaults: `segment_size` default is **120** everywhere (Python config, VLC `sg_core.lua`, Settings dialog, docs).

## Tests — always run before committing

```powershell
python tests/run_all.py
```

- `tests/cli/` — Python `unittest` (srt cleanup, end-to-end segmentation at 1–5h, config, CLI parsing).
- `tests/vlc-extension/` — Lua UI via `lupa` (optional; skipped if not installed) + PowerShell `test_*.ps1` (self-contained; run every `test_*.ps1`; skipped if no `pwsh`/`powershell`).
- A plain `unittest discover -s tests` does **not** recurse (separate non-package folders, and `vlc-extension` has a hyphen). Use `run_all.py` or target a specific group.
- New cleanup/segmentation behavior needs tests in **both** the Python (`test_srt.py` / `test_transcribe.py`) and PowerShell (`test_postprocess.ps1` / `test_owned_window.ps1`) suites.

## Workflow rules

- Run the full suite and confirm green **before** any commit or push.
- Include the trailer `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` on agent-authored commits.
- **Commit work before** running checkout-based mutation tests — `git checkout -- <file>` discards uncommitted edits to that file.
- On history rewrites, verify the resulting tree is byte-identical (`git diff --stat <backup> HEAD` empty) and keep a backup branch until verified.
- Windows: use PowerShell-native commands and backslash paths.
