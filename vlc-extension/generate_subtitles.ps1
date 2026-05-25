# Subtitle Generator - PowerShell Script
# Extracts audio from media and generates SRT subtitles using whisper.cpp
#
# Usage: generate_subtitles.ps1 -MediaPath <path> -OutputSrt <path> -WhisperPath <path>
#        -ModelPath <path> [-FfmpegPath <path>] [-Language <lang>] [-Mode <full|live>]
#        [-ChunkSize <seconds>]

param(
    [Parameter(Mandatory=$true)]
    [string]$MediaPath,

    [Parameter(Mandatory=$true)]
    [string]$OutputSrt,

    [Parameter(Mandatory=$true)]
    [string]$WhisperPath,

    [Parameter(Mandatory=$true)]
    [string]$ModelPath,

    [string]$FfmpegPath = "ffmpeg",
    [string]$Language = "en",
    [string]$Mode = "full",
    [int]$ChunkSize = 30,
    [string]$Translate = "no"
)

$ErrorActionPreference = "Stop"

# Status file for progress reporting
$StatusFile = $OutputSrt -replace '\.srt$', '.status'
$LogFile = $OutputSrt -replace '\.srt$', '.log'

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$timestamp] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue
}

function Write-Status {
    param([string]$Status, [string]$Progress = "", [string]$Error = "")
    $content = "status=$Status`nprogress=$Progress`nerror=$Error`ntimestamp=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    $content += "`nmedia_path=$MediaPath`noutput_srt=$OutputSrt"
    $content += "`nwhisper_path=$WhisperPath`nmodel_path=$ModelPath`nffmpeg_path=$FfmpegPath"
    $content += "`nlanguage=$Language`nmode=$Mode`nchunk_size=$ChunkSize`ntranslate=$Translate"
    [System.IO.File]::WriteAllText($StatusFile, $content)
    if ($Error) { Write-Log "STATUS: $Status - ERROR: $Error" }
    elseif ($Progress) { Write-Log "STATUS: $Status - Progress: $Progress%" }
    else { Write-Log "STATUS: $Status" }
}

function Get-MediaDuration {
    param([string]$Path)
    try {
        $output = & $FfmpegPath -i $Path -hide_banner 2>&1 | Out-String
        Write-Log "ffmpeg duration probe output: $($output.Substring(0, [Math]::Min(200, $output.Length)))"
        if ($output -match "Duration:\s*(\d+):(\d+):(\d+)\.(\d+)") {
            $hours = [int]$Matches[1]
            $minutes = [int]$Matches[2]
            $seconds = [int]$Matches[3]
            $dur = ($hours * 3600) + ($minutes * 60) + $seconds
            Write-Log "Detected duration: ${dur}s"
            return $dur
        }
    } catch {
        Write-Log "Duration detection failed: $_"
        return 0
    }
    return 0
}

function Convert-ToSrtTimestamp {
    param([double]$Seconds)
    $ts = [TimeSpan]::FromSeconds($Seconds)
    return "{0:D2}:{1:D2}:{2:D2},{3:D3}" -f $ts.Hours, $ts.Minutes, $ts.Seconds, $ts.Milliseconds
}

function Extract-AudioChunk {
    param(
        [string]$InputPath,
        [string]$OutputPath,
        [double]$StartTime,
        [double]$Duration
    )
    $startStr = [TimeSpan]::FromSeconds($StartTime).ToString("hh\:mm\:ss\.fff")
    $ffmpegChunkArgs = @(
        "-y", "-hide_banner", "-loglevel", "error",
        "-ss", $startStr,
        "-t", $Duration.ToString(),
        "-i", $InputPath,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        $OutputPath
    )
    & $FfmpegPath @ffmpegChunkArgs *>$null
    if ($LASTEXITCODE -ne 0) {
        throw "ffmpeg failed to extract audio chunk at $StartTime"
    }
}

function Invoke-Whisper {
    param(
        [string]$AudioPath,
        [string]$OutputBase
    )
    $whisperArgs = @(
        "-m", $ModelPath,
        "-f", $AudioPath,
        "-l", $Language,
        "--output-srt",
        "--output-file", $OutputBase
    )
    if ($Translate -eq "yes") {
        $whisperArgs += "--translate"
    }
    Write-Log "Running whisper: $WhisperPath $($whisperArgs -join ' ')"
    $ErrorActionPreference = "Continue"
    & $WhisperPath @whisperArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
    $whisperExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($whisperExit -ne 0) {
        Write-Log "Whisper failed with exit code: $whisperExit"
        throw "whisper.cpp failed to process audio (exit code: $whisperExit)"
    }
    Write-Log "Whisper completed successfully, output: $OutputBase.srt"
    return "$OutputBase.srt"
}

function Parse-SrtFile {
    param([string]$Path)
    $entries = @()
    if (-not (Test-Path $Path)) { return $entries }

    $content = Get-Content $Path -Raw
    $blocks = $content -split '\r?\n\r?\n' | Where-Object { $_.Trim() -ne "" }

    foreach ($block in $blocks) {
        $lines = $block -split '\r?\n' | Where-Object { $_.Trim() -ne "" }
        if ($lines.Count -ge 3) {
            $timeLine = $lines[1]
            if ($timeLine -match '(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})') {
                $startStr = $Matches[1] -replace '\.', ','
                $endStr = $Matches[2] -replace '\.', ','
                $text = ($lines[2..($lines.Count-1)] -join "`n").Trim()
                if ($text -ne "" -and $text -ne "[BLANK_AUDIO]") {
                    $entries += @{
                        Start = $startStr
                        End = $endStr
                        Text = $text
                    }
                }
            }
        }
    }
    return $entries
}

function Parse-SrtTimestamp {
    param([string]$Timestamp)
    if ($Timestamp -match '(\d{2}):(\d{2}):(\d{2})[,\.](\d{3})') {
        $h = [int]$Matches[1]
        $m = [int]$Matches[2]
        $s = [int]$Matches[3]
        $ms = [int]$Matches[4]
        return ($h * 3600) + ($m * 60) + $s + ($ms / 1000.0)
    }
    return 0
}

function Offset-SrtTimestamp {
    param([string]$Timestamp, [double]$OffsetSeconds)
    $totalSeconds = (Parse-SrtTimestamp $Timestamp) + $OffsetSeconds
    return Convert-ToSrtTimestamp $totalSeconds
}

function Write-SrtFile {
    param([string]$Path, [array]$Entries)
    $sb = [System.Text.StringBuilder]::new()
    $index = 1
    foreach ($entry in $Entries) {
        [void]$sb.AppendLine($index.ToString())
        [void]$sb.AppendLine("$($entry.Start) --> $($entry.End)")
        [void]$sb.AppendLine($entry.Text)
        [void]$sb.AppendLine("")
        $index++
    }
    # Atomic write: write to temp then rename
    $tempPath = "$Path.tmp"
    [System.IO.File]::WriteAllText($tempPath, $sb.ToString(), [System.Text.Encoding]::UTF8)
    if (Test-Path $Path) { Remove-Item $Path -Force }
    Rename-Item $tempPath $Path
}

# === Main Execution ===

try {
    # Write PID file so the VLC extension can kill this process
    $PidFile = $OutputSrt -replace '\.srt$', '.pid'
    [System.IO.File]::WriteAllText($PidFile, $PID.ToString())

    # Validate inputs
    if (-not (Test-Path $MediaPath)) {
        Write-Status -Status "error" -Error "Media file not found: $MediaPath"
        exit 1
    }
    if (-not (Test-Path $WhisperPath)) {
        Write-Status -Status "error" -Error "whisper.cpp binary not found: $WhisperPath"
        exit 1
    }
    if (-not (Test-Path $ModelPath)) {
        Write-Status -Status "error" -Error "Model file not found: $ModelPath"
        exit 1
    }

    Write-Log "Starting subtitle generation"
    Write-Log "Media: $MediaPath"
    Write-Log "Output: $OutputSrt"
    Write-Log "Whisper: $WhisperPath"
    Write-Log "Model: $ModelPath"
    Write-Log "FFmpeg: $FfmpegPath"
    Write-Log "Language: $Language, Mode: $Mode, ChunkSize: $ChunkSize, Translate: $Translate"

    # Verify ffmpeg is accessible
    try {
        $ffmpegTest = & $FfmpegPath -version 2>&1 | Select-Object -First 1
        Write-Log "ffmpeg version: $ffmpegTest"
    } catch {
        Write-Status -Status "error" -Error "ffmpeg not found or not executable: $FfmpegPath"
        exit 1
    }

    # Create temp directory
    $tempDir = Join-Path $env:TEMP "subtitle_generator_$(Get-Random)"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

    Write-Status -Status "running" -Progress "0"

    # Get media duration
    $duration = Get-MediaDuration -Path $MediaPath
    if ($duration -eq 0) {
        Write-Log "WARNING: Could not detect duration from media probe, will calculate from extracted audio"
    }

    if ($Mode -eq "full") {
        # Full file mode: extract all audio at once, then process in segments for progress
        $audioPath = Join-Path $tempDir "full_audio.wav"

        Write-Status -Status "running" -Progress "5"

        # Extract full audio
        $ffmpegArgs = @(
            "-y", "-hide_banner", "-loglevel", "error",
            "-i", $MediaPath,
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            $audioPath
        )
        Write-Log "Extracting full audio: $FfmpegPath $($ffmpegArgs -join ' ')"
        $ffmpegOutput = & $FfmpegPath @ffmpegArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "ffmpeg failed (exit $LASTEXITCODE): $ffmpegOutput"
            throw "ffmpeg failed to extract audio (exit code: $LASTEXITCODE)"
        }
        if (-not (Test-Path $audioPath)) {
            throw "ffmpeg did not produce audio file at: $audioPath"
        }
        Write-Log "Audio extracted successfully: $audioPath ($(((Get-Item $audioPath).Length / 1MB).ToString('F1')) MB)"

        # Calculate accurate duration from WAV file size (more reliable than ffmpeg text parsing)
        # WAV format: 16000 Hz, 1 channel, 16-bit = 32000 bytes/second, 44-byte header
        $wavFileSize = (Get-Item $audioPath).Length
        $wavDuration = [Math]::Floor(($wavFileSize - 44) / 32000)
        if ($wavDuration -gt 0) {
            Write-Log "Duration from WAV file: ${wavDuration}s (ffmpeg probe: ${duration}s)"
            $duration = $wavDuration
        }

        Write-Status -Status "running" -Progress "10"

        # Process in segments for progress reporting
        $segmentSize = $ChunkSize  # In full mode, ChunkSize is used as segment size
        $segmentCount = [Math]::Ceiling($duration / $segmentSize)

        if ($segmentCount -le 1) {
            # Short file: process in one go
            $outputBase = Join-Path $tempDir "output"
            $whisperArgs = @(
                "-m", $ModelPath,
                "-f", $audioPath,
                "-l", $Language,
                "--output-srt",
                "--output-file", $outputBase
            )
            if ($Translate -eq "yes") {
                $whisperArgs += "--translate"
            }
            Write-Log "Running whisper (single segment): $WhisperPath $($whisperArgs -join ' ')"
            $ErrorActionPreference = "Continue"
            & $WhisperPath @whisperArgs *>$null
            $whisperExit = $LASTEXITCODE
            $ErrorActionPreference = "Stop"
            if ($whisperExit -ne 0) {
                Write-Log "Whisper failed with exit code: $whisperExit"
                throw "whisper.cpp failed to process audio (exit code: $whisperExit)"
            }

            Write-Status -Status "running" -Progress "90"

            $whisperSrt = "$outputBase.srt"
            if (Test-Path $whisperSrt) {
                $entries = Parse-SrtFile -Path $whisperSrt
                Write-SrtFile -Path $OutputSrt -Entries $entries
            } else {
                throw "whisper.cpp did not produce output SRT file"
            }
        } else {
            # Long file: process in segments for progress updates
            $allEntries = @()
            $currentSegment = 0

            for ($offset = 0; $offset -lt $duration; $offset += $segmentSize) {
                $currentSegment++
                $segDuration = [Math]::Min($segmentSize, $duration - $offset)
                # Progress: 10% (extraction) + 80% (whisper segments) + 10% (finalize)
                $progress = 10 + [Math]::Round(($currentSegment / $segmentCount) * 80, 1)

                Write-Status -Status "running" -Progress $progress.ToString()

                # Extract audio segment
                $segAudio = Join-Path $tempDir "seg_$currentSegment.wav"
                $startStr = [TimeSpan]::FromSeconds($offset).ToString("hh\:mm\:ss\.fff")
                $ffmpegSegArgs = @(
                    "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", $startStr,
                    "-t", $segDuration.ToString(),
                    "-i", $audioPath,
                    "-ar", "16000",
                    "-ac", "1",
                    "-c:a", "pcm_s16le",
                    $segAudio
                )
                & $FfmpegPath @ffmpegSegArgs *>$null
                if ($LASTEXITCODE -ne 0) {
                    Write-Log "Segment $currentSegment ffmpeg failed, skipping"
                    continue
                }

                # Process segment with whisper
                $segOutputBase = Join-Path $tempDir "seg_$currentSegment"
                $whisperArgs = @(
                    "-m", $ModelPath,
                    "-f", $segAudio,
                    "-l", $Language,
                    "--output-srt",
                    "--output-file", $segOutputBase
                )
                if ($Translate -eq "yes") {
                    $whisperArgs += "--translate"
                }
                $ErrorActionPreference = "Continue"
                & $WhisperPath @whisperArgs *>$null
                $whisperExit = $LASTEXITCODE
                $ErrorActionPreference = "Stop"

                if ($whisperExit -ne 0) {
                    Write-Log "Segment $currentSegment whisper failed (exit $whisperExit), skipping"
                    continue
                }

                # Parse and offset timestamps
                $segSrt = "$segOutputBase.srt"
                if (Test-Path $segSrt) {
                    $segEntries = Parse-SrtFile -Path $segSrt
                    foreach ($entry in $segEntries) {
                        $allEntries += @{
                            Start = (Offset-SrtTimestamp -Timestamp $entry.Start -OffsetSeconds $offset)
                            End = (Offset-SrtTimestamp -Timestamp $entry.End -OffsetSeconds $offset)
                            Text = $entry.Text
                        }
                    }
                }

                # Clean up segment files
                Remove-Item $segAudio -Force -ErrorAction SilentlyContinue
                Remove-Item $segSrt -Force -ErrorAction SilentlyContinue
            }

            Write-Status -Status "running" -Progress "92"

            # Write final SRT
            if ($allEntries.Count -gt 0) {
                Write-SrtFile -Path $OutputSrt -Entries $allEntries
            } else {
                throw "whisper.cpp did not produce any output"
            }
        }

        Write-Status -Status "complete" -Progress "100"

    } elseif ($Mode -eq "live") {
        # Live mode: process in chunks
        if ($duration -eq 0) {
            $duration = 86400  # Fallback for live mode: assume up to 24 hours
            Write-Log "Using maximum duration fallback for live mode: ${duration}s"
        }
        $allEntries = @()
        $chunkCount = [Math]::Ceiling($duration / $ChunkSize)
        $currentChunk = 0

        for ($offset = 0; $offset -lt $duration; $offset += $ChunkSize) {
            $currentChunk++
            $chunkDuration = [Math]::Min($ChunkSize, $duration - $offset)
            $progress = [Math]::Round(($currentChunk / $chunkCount) * 100, 1)

            Write-Status -Status "running" -Progress $progress.ToString()

            # Extract audio chunk
            $chunkAudio = Join-Path $tempDir "chunk_$currentChunk.wav"
            Extract-AudioChunk -InputPath $MediaPath -OutputPath $chunkAudio -StartTime $offset -Duration $chunkDuration

            # Process with whisper
            $chunkOutputBase = Join-Path $tempDir "chunk_$currentChunk"
            try {
                Invoke-Whisper -AudioPath $chunkAudio -OutputBase $chunkOutputBase
            } catch {
                # Skip failed chunks
                Write-Log "Warning: Chunk $currentChunk failed: $_"
                continue
            }

            # Parse chunk SRT and offset timestamps
            $chunkSrt = "$chunkOutputBase.srt"
            if (Test-Path $chunkSrt) {
                $chunkEntries = Parse-SrtFile -Path $chunkSrt
                foreach ($entry in $chunkEntries) {
                    $allEntries += @{
                        Start = (Offset-SrtTimestamp -Timestamp $entry.Start -OffsetSeconds $offset)
                        End = (Offset-SrtTimestamp -Timestamp $entry.End -OffsetSeconds $offset)
                        Text = $entry.Text
                    }
                }
                # Write intermediate SRT (atomic)
                Write-SrtFile -Path $OutputSrt -Entries $allEntries
            }

            # Clean up chunk files to save space
            Remove-Item $chunkAudio -Force -ErrorAction SilentlyContinue
            Remove-Item $chunkSrt -Force -ErrorAction SilentlyContinue
        }

        Write-Status -Status "complete" -Progress "100"
    }

} catch {
    Write-Status -Status "error" -Error $_.Exception.Message
    exit 1
} finally {
    # Clean up temp directory and PID file
    if ($tempDir -and (Test-Path $tempDir)) {
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($PidFile -and (Test-Path $PidFile)) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}
