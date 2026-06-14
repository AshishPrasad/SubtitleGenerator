# Tests

Unit tests for the Subtitle Generator, organized by component. The Python tests
are pure-stdlib (`unittest`) — no external packages required.

```
tests/
├── cli/                    # Python CLI package (subtitle_generator)
│   ├── test_srt.py         # Timestamp parse/format, SRT parsing, caption cleanup
│   ├── test_transcribe.py  # End-to-end segmentation pipeline (1-5h), owned-window
│   ├── test_config.py      # Config defaults and save/load round-trip
│   ├── test_cli.py         # Argument parser, output-path resolution, validation
│   └── _support.py         # Adds cli/ to sys.path
├── vlc-extension/          # VLC extension (Lua UI + PowerShell backend)
│   ├── test_lua_extension.py   # Lua modules (sg_core/sg_ui) against a mocked `vlc`
│   ├── test_postprocess.ps1    # PowerShell backend: caption cleanup
│   ├── test_owned_window.ps1   # PowerShell backend: segment-boundary dedup (1-5h)
│   └── _support.py
└── run_all.py              # Runs every group (Python + PowerShell) together
```

Coverage by component:

| Component | Tests |
|-----------|-------|
| CLI (Python) | `test_srt.py`, `test_transcribe.py`, `test_config.py`, `test_cli.py` |
| VLC Lua UI | `test_lua_extension.py` (needs `lupa`, else skipped) |
| VLC PowerShell backend | `test_postprocess.ps1` (cleanup parity with `test_srt.py`), `test_owned_window.ps1` (boundary dedup parity with `test_transcribe.py`) |

## Run

Everything (Python CLI + Lua + PowerShell backend), from the repository root:

```powershell
python tests/run_all.py
```

A single Python group:

```powershell
python -m unittest discover -s tests/cli -v
python -m unittest discover -s tests/vlc-extension -v
```

Just the PowerShell backend tests:

```powershell
pwsh -NoProfile -File tests/vlc-extension/test_postprocess.ps1
pwsh -NoProfile -File tests/vlc-extension/test_owned_window.ps1
```

> Note: a plain `unittest discover -s tests` won't recurse into the two groups
> (they are separate non-package folders, and `vlc-extension` contains a hyphen),
> so use `run_all.py` or point `-s` at a specific group.

## Optional dependencies

- **Lua tests** (`test_lua_extension.py`) use the
  [`lupa`](https://pypi.org/project/lupa/) embedded Lua runtime. If `lupa` is not
  installed they are **skipped automatically**. Install with `pip install lupa`.
- **PowerShell backend tests** (`test_*.ps1`) run via `pwsh`/`powershell`
  and need no extra modules (self-contained assertions). `run_all.py` runs every
  `tests/vlc-extension/test_*.ps1` and **skips** them automatically if no
  PowerShell executable is found.

