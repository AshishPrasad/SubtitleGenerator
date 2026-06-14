# PowerShell owned-window tests for vlc-extension/generate_subtitles.ps1
#
# Parity with tests/cli/test_transcribe.py: simulates the segmented pipeline at
# 1-5 hour durations and verifies the extracted Select-OwnedEntries function
# commits each caption exactly once by its OWNING segment, so captions in the
# overlap regions at segment boundaries are never duplicated or dropped.
#
# Each segment emits DISTINCT text for the same timestamp (the clip start is
# encoded in the text), simulating whisper's context-dependent transcription:
# postprocess cannot merge those, so only the owned-window commit prevents a
# duplicate. Self-contained (no Pester). Exits non-zero on any failure.

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $here)
$scriptPath = Join-Path $repo 'vlc-extension\generate_subtitles.ps1'

$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "Parse errors in $scriptPath" }
$want = 'Convert-ToSrtTimestamp', 'Parse-SrtTimestamp', 'Offset-SrtTimestamp',
        'Postprocess-Entries', 'Select-OwnedEntries'
$funcs = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) |
    Where-Object { $want -contains $_.Name }
$prelude = @'
$script:SegmentOverlapSeconds = 3.0
$script:MaxCaptionSeconds = 10.0
$script:MinCaptionSeconds = 0.2
$script:DuplicateGapSeconds = 0.5
'@
$body = ($funcs | ForEach-Object { $_.Extent.Text }) -join "`n`n"
Invoke-Expression ($prelude + "`n" + $body)

$script:failures = 0
function Assert-True($cond, $msg) {
    if ($cond) { Write-Host "  [PASS] $msg" }
    else { Write-Host "  [FAIL] $msg" -ForegroundColor Red; $script:failures++ }
}

$SegmentSize = 120
$Overlap = $script:SegmentOverlapSeconds

# The clip_start of the segment that OWNS time t (mirrors generate_subtitles).
function Owner-ClipStart([double]$t, [int]$S, [double]$ov) {
    $i = [Math]::Floor($t / $S)
    return [Math]::Max(0.0, $i * $S - $ov)
}

# Simulate the segmented pipeline for a duration; return committed + expected.
function Run-Duration([double]$duration) {
    $S = $SegmentSize; $ov = $Overlap
    $segCount = [int][Math]::Ceiling($duration / $S)

    # Ground-truth caption times: every interior segment boundary and its
    # immediate neighbours (where overlap duplicates would appear), plus a
    # mid-point per segment.
    $raw = New-Object System.Collections.ArrayList
    for ($k = 1; $k -lt $segCount; $k++) {
        foreach ($c in @(($k * $S - 1.0), [double]($k * $S), ($k * $S + 1.0))) {
            if ($c -ge 1.0 -and $c -lt ($duration - 2)) { [void]$raw.Add([Math]::Round($c, 3)) }
        }
    }
    for ($i = 0; $i -lt $segCount; $i++) {
        $mid = $i * $S + $S / 2.0
        if ($mid -lt ($duration - 2)) { [void]$raw.Add([Math]::Round($mid, 3)) }
    }
    $gt = @($raw | Sort-Object -Unique)

    $all = @()
    for ($i = 0; $i -lt $segCount; $i++) {
        $offset = $i * $S
        $segDuration = [Math]::Min($S, $duration - $offset)
        $clipStart = [Math]::Max(0.0, $offset - $ov)
        $clipEnd = [Math]::Min($duration, $offset + $segDuration + $ov)

        # Per-segment "whisper output" (clip-relative), distinct text per segment.
        $segOut = @()
        foreach ($t in $gt) {
            if ($t -ge ($clipStart - 1e-9) -and $t -lt ($clipEnd - 1e-9)) {
                $rel = $t - $clipStart
                $segOut += @{
                    Start = (Convert-ToSrtTimestamp $rel)
                    End   = (Convert-ToSrtTimestamp ($rel + 1.0))
                    Text  = ("cap@{0:F3}|clip{1:F1}" -f $t, $clipStart)
                }
            }
        }

        $ownedStart = if ($i -eq 0) { 0 } else { $offset }
        $ownedEnd = if (($offset + $S) -ge $duration) { [double]::PositiveInfinity } else { $offset + $segDuration }
        $all += @(Select-OwnedEntries -Entries $segOut -ClipStart $clipStart -OwnedStart $ownedStart -OwnedEnd $ownedEnd)
    }

    $clean = @(Postprocess-Entries -Entries $all)
    $expected = @($gt | ForEach-Object { "cap@{0:F3}|clip{1:F1}" -f $_, (Owner-ClipStart $_ $SegmentSize $Overlap) })
    return @{ Clean = $clean; Expected = $expected; Gt = $gt }
}

Write-Host "PowerShell owned-window tests (generate_subtitles.ps1)"

foreach ($hours in 1..5) {
    $duration = [double]($hours * 3600)
    $r = Run-Duration $duration
    $texts = @($r.Clean | ForEach-Object { $_.Text })

    # 1) Exactly one caption per ground-truth time, from the correct owner.
    Assert-True ($texts.Count -eq $r.Gt.Count) "${hours}h: caption count == ground truth ($($texts.Count) vs $($r.Gt.Count))"
    $gotSet = ($texts | Sort-Object) -join "`n"
    $expSet = ($r.Expected | Sort-Object) -join "`n"
    Assert-True ($gotSet -eq $expSet) "${hours}h: each caption committed once by its owning segment"

    # 2) Output sorted and non-overlapping.
    $starts = @($r.Clean | ForEach-Object { Parse-SrtTimestamp $_.Start })
    $sorted = @($starts | Sort-Object)
    Assert-True (($starts -join ',') -eq ($sorted -join ',')) "${hours}h: output sorted by start"
    $noOverlap = $true
    for ($i = 0; $i -lt $r.Clean.Count - 1; $i++) {
        if ((Parse-SrtTimestamp $r.Clean[$i].End) -gt (Parse-SrtTimestamp $r.Clean[$i + 1].Start)) { $noOverlap = $false }
    }
    Assert-True $noOverlap "${hours}h: no overlapping ranges"
}

if ($script:failures -gt 0) {
    Write-Host "FAILED: $($script:failures) assertion(s)" -ForegroundColor Red
    exit 1
}
Write-Host "OK: all PowerShell owned-window tests passed"
exit 0
