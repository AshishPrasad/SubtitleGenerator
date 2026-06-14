# VLC Extension - Subtitle Generator

The VLC Lua extension provides a graphical interface for generating subtitles directly from VLC's View menu.

## Installation

Run these commands in PowerShell:

```powershell
# Install — copy all three Lua files (entry + core + UI) into the extensions folder
Copy-Item "vlc-extension\*.lua" "$env:APPDATA\vlc\lua\extensions\"
New-Item -ItemType Directory -Path "$env:APPDATA\vlc\lua\extensions\scripts" -Force
Copy-Item "vlc-extension\generate_subtitles.*" "$env:APPDATA\vlc\lua\extensions\scripts\"
```

> The extension is split into three files that must live side by side in
> `%APPDATA%\vlc\lua\extensions\`: `subtitle_generator.lua` (entry/VLC hooks),
> `sg_core.lua` (core logic), and `sg_ui.lua` (dialogs). Copying `*.lua` installs
> all three.

Then **restart VLC** for the extension to appear.

## Configuration

1. Open VLC and play any video
2. Go to **View → Subtitle Generator**
3. Click **Settings** (or go to View menu item #2)
4. Fill in the paths:

| Setting | Example Value |
|---------|---------------|
| **whisper.cpp binary** | `C:\tools\whisper-cpp\whisper-cli.exe` |
| **Model file (.bin)** | `C:\tools\whisper-cpp\models\ggml-small.bin` |
| **ffmpeg path** | `ffmpeg` (if in PATH) or full path like `C:\tools\ffmpeg\bin\ffmpeg.exe` |
| **Script path (.bat)** | Leave empty (auto-detected) or set full path |

5. Optionally configure:
   - **Chunk size**: Seconds per chunk in Live mode (default: 30)
   - **Segment size**: Seconds per segment in Full mode (controls progress update frequency)
     - `60s` — progress updates every ~15s
     - `120s` — updates every ~30s, fewer boundary gaps (default)
     - `300s` — updates every ~75s, minimal boundary gaps
   - **Output directory**: Where to save SRT files (default: same folder as video)

6. Click **Save**

## Generating Subtitles

### Basic Usage (Transcription)

1. Play a video in VLC
2. Go to **View → Subtitle Generator**
3. Select **Mode**: Full File (recommended) or Live
4. Select **Language** from the dropdown (matches the audio language)
5. Click **Generate Subtitles**
6. Click **Check Status** to monitor progress (updates every ~15 seconds)
7. When complete, click **Load Existing SRT** to display subtitles

### Translation (non-English audio → English subtitles)

1. Play a video with non-English audio
2. Go to **View → Subtitle Generator**
3. Select the **audio's language** from the dropdown
4. The **"Translate to English"** option is automatically selected when a non-English language is chosen
5. Click **Generate Subtitles**
6. The generated SRT file will contain English subtitles

### Live Mode with Auto-Reload

1. Select **Live (Experimental)** mode
2. Click **Generate Subtitles** — subtitles auto-reload as chunks finish
3. Click **Check Status** at any time to see progress and refresh subtitles
4. Click **Stop Auto-Reload** when you no longer want automatic updates

## Modes

### Full File Mode (Recommended)
- Extracts all audio at once, processes in overlapping segments with progress tracking
- Overlap gives whisper cross-boundary context, so words at segment edges are transcribed correctly
- Output is cleaned up: repeated captions are collapsed, overlaps removed, and over-long "stuck" captions clamped
- Progress updates after each segment completes
- Most accurate results with configurable segment size
- Best for: Videos, TV shows, recorded lectures
- Typical time: ~50 min for a 2-hour video (small model)

### Live Mode (Experimental)
- Processes audio in configurable chunks (default: 30 seconds)
- SRT file is updated as each chunk completes
- Auto-reload refreshes subtitles in VLC automatically
- May have slight timing gaps at chunk boundaries
- Best for: Long videos where you want partial results quickly

### Translation Mode
- Translates any supported language to English subtitles
- whisper.cpp handles recognition and translation in a single step (not a separate tool)
- Works with both Full File and Live modes
- The original video file is **never modified** — only a new `.srt` file is created

## Configuration Reference

Settings are stored in `%APPDATA%\vlc\subtitle_generator_config.txt`

| Setting | Description | Default |
|---------|-------------|---------|
| `whisper_path` | Path to whisper-cli.exe | (required) |
| `model_path` | Path to .bin model file | (required) |
| `ffmpeg_path` | Path to ffmpeg | `ffmpeg` |
| `script_path` | Path to generate_subtitles.bat | (auto-detect) |
| `language` | Language code for audio | `en` |
| `translate` | Translate to English (`yes`/`no`) | `yes` (auto for non-English) |
| `chunk_size` | Seconds per chunk (Live mode) | `30` |
| `segment_size` | Seconds per segment (Full mode) | `120` |
| `output_dir` | Directory for SRT output | (same as media) |
| `model_size` | Model size hint | `base` |

## Generated Files (Debugging)

When subtitle generation runs, these files are created alongside the output SRT (or in `%TEMP%`):

| File | Location | Purpose |
|------|----------|---------|
| `<video>.srt` | Same folder as video (or `output_dir`) | Generated subtitles |
| `<video>.status` | Same folder as SRT | Progress/status file — contains status, progress %, config paths, input/output paths |
| `<video>.log` | Same folder as SRT | Detailed log with timestamps for every step |
| `subtitle_gen_launch.bat` | `%TEMP%` | Temp launcher script showing the exact command being run |
| `subtitle_generator_<random>\` | `%TEMP%` | Temp folder with intermediate WAV segments (cleaned up on success) |

### Status file format

The `.status` file is updated in real-time and contains:
```
status=running|complete|error
progress=0-100
error=<message if failed>
timestamp=2025-01-15 14:30:00
media_path=C:\...\video.mp4
output_srt=C:\...\video.srt
whisper_path=C:\...\whisper-cli.exe
model_path=C:\...\ggml-small.bin
ffmpeg_path=C:\...\ffmpeg.exe
language=en
mode=full
chunk_size=120
translate=yes
```

### Reading the log file

The `.log` file records every step with timestamps:
```
[2025-01-15 14:30:01] Starting subtitle generation
[2025-01-15 14:30:01] Media: C:\...\video.mp4
[2025-01-15 14:30:01] Whisper: C:\...\whisper-cli.exe
[2025-01-15 14:30:02] Extracting full audio...
[2025-01-15 14:30:10] Running whisper: whisper-cli.exe -m model.bin ...
[2025-01-15 14:31:30] Whisper completed successfully
[2025-01-15 14:31:30] STATUS: complete
```

## Troubleshooting

### "ffmpeg failed to extract audio"
- Ensure ffmpeg is installed: run `ffmpeg -version` in a terminal
- If installed via winget, **restart VLC** (PATH changes require restart)
- Use the full path to ffmpeg.exe in Settings if it's not in PATH
- Test manually: `ffmpeg -i "video.mp4" -ar 16000 -ac 1 test.wav`

### "whisper.cpp failed to process audio"
- Use **`whisper-cli.exe`** not `main.exe` (deprecated in newer versions)
- Verify the model file path is correct and file is not corrupted
- Test manually: `whisper-cli.exe -m model.bin -f audio.wav`
- Ensure the model file size matches expected (e.g., small = ~466 MB)

### Command prompt opens but no output appears
- Check the `.log` file next to where the SRT would be saved
- Check `%TEMP%\subtitle_gen_launch.bat` to see the exact command being run
- Run that batch file manually from a terminal to see errors directly

### Stuck at a progress percentage
- In Full File mode, each segment takes ~15-30 seconds to process — this is normal
- For a 2-hour video with `small` model, expect ~50 minutes total
- The process runs in the background — you can keep watching or close the dialog
- Check the `.status` file for current progress, or click **Check Status** in VLC

### Extension not appearing in VLC
- Ensure `subtitle_generator.lua`, `sg_core.lua`, and `sg_ui.lua` are all in `%APPDATA%\vlc\lua\extensions\` (the entry file loads the other two at runtime)
- Restart VLC completely (File → Quit, then reopen)
- Check VLC messages (Tools → Messages) for Lua errors

### Subtitles not loading
- Check that the `.srt` file was generated (look in the same folder as the video)
- Try loading manually: VLC → Subtitle → Add Subtitle File
- In Live mode, click **Check Status** to trigger a reload
