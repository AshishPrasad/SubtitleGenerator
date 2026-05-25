@echo off
REM Subtitle Generator - Batch Wrapper
REM Launches the PowerShell script detached for VLC extension integration
REM
REM Arguments:
REM   1: Media file path
REM   2: Output SRT path
REM   3: whisper.cpp binary path
REM   4: Model file path
REM   5: ffmpeg path
REM   6: Language (e.g., en)
REM   7: Mode (full or live)
REM   8: Chunk size in seconds
REM   9: Translate to English (yes or no)

set MEDIA_PATH=%~1
set OUTPUT_SRT=%~2
set WHISPER_PATH=%~3
set MODEL_PATH=%~4
set FFMPEG_PATH=%~5
set LANGUAGE=%~6
set MODE=%~7
set CHUNK_SIZE=%~8
set TRANSLATE=%~9

if "%MEDIA_PATH%"=="" (
    echo Error: Media path is required
    exit /b 1
)

if "%OUTPUT_SRT%"=="" (
    echo Error: Output SRT path is required
    exit /b 1
)

if "%WHISPER_PATH%"=="" (
    echo Error: whisper.cpp path is required
    exit /b 1
)

if "%MODEL_PATH%"=="" (
    echo Error: Model path is required
    exit /b 1
)

if "%FFMPEG_PATH%"=="" set FFMPEG_PATH=ffmpeg
if "%LANGUAGE%"=="" set LANGUAGE=en
if "%MODE%"=="" set MODE=full
if "%CHUNK_SIZE%"=="" set CHUNK_SIZE=30
if "%TRANSLATE%"=="" set TRANSLATE=no

REM Get script directory
set SCRIPT_DIR=%~dp0

REM Launch PowerShell script
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%generate_subtitles.ps1" ^
    -MediaPath "%MEDIA_PATH%" ^
    -OutputSrt "%OUTPUT_SRT%" ^
    -WhisperPath "%WHISPER_PATH%" ^
    -ModelPath "%MODEL_PATH%" ^
    -FfmpegPath "%FFMPEG_PATH%" ^
    -Language "%LANGUAGE%" ^
    -Mode "%MODE%" ^
    -ChunkSize %CHUNK_SIZE% ^
    -Translate "%TRANSLATE%"
