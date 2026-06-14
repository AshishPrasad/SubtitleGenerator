# PowerShell backend tests for vlc-extension/generate_subtitles.ps1
#
# Parity with tests/cli/test_srt.py: verifies the caption cleanup
# (Postprocess-Entries) merges repetition loops, trims overlapping ranges,
# clamps stuck captions, drops blanks, sorts by time, and that the written .srt
# file is sorted/deduped with sequential indices.
#
# Self-contained (no Pester needed). Exits non-zero if any assertion fails.

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $here)
$scriptPath = Join-Path $repo 'vlc-extension\generate_subtitles.ps1'

# Extract only the function definitions + tuning vars from the backend script
# via the AST, so we don't run its main body (which needs ffmpeg/whisper).
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "Parse errors in $scriptPath" }
$want = 'Convert-ToSrtTimestamp', 'Parse-SrtTimestamp', 'Parse-SrtFile',
        'Offset-SrtTimestamp', 'Write-SrtFile', 'Postprocess-Entries'
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

# ── Tiny assertion harness ──────────────────────────────────────────────────
$script:failures = 0
function Assert-True($cond, $msg) {
    if ($cond) {
        Write-Host "  [PASS] $msg"
    } else {
        Write-Host "  [FAIL] $msg" -ForegroundColor Red
        $script:failures++
    }
}
function E($s, $e, $t) {
    @{ Start = (Convert-ToSrtTimestamp $s); End = (Convert-ToSrtTimestamp $e); Text = $t }
}
function Dur($entry) { (Parse-SrtTimestamp $entry.End) - (Parse-SrtTimestamp $entry.Start) }

Write-Host "PowerShell postprocess tests (generate_subtitles.ps1)"

# 1) Repetition loop collapses to one caption and is clamped.
$rep = @()
for ($i = 0; $i -lt 8; $i++) { $rep += (E (10 + 2 * $i) (12 + 2 * $i) 'Thank you.') }
$out = @(Postprocess-Entries -Entries $rep)
Assert-True ($out.Count -eq 1) "repetition loop collapses to 1 (got $($out.Count))"
Assert-True ((Dur $out[0]) -le ($script:MaxCaptionSeconds + 1e-6)) "merged caption clamped (dur=$(Dur $out[0]))"

# 2) Stuck caption clamped to MaxCaptionSeconds.
$out = @(Postprocess-Entries -Entries @((E 60 120 '[Music]')))
Assert-True ([Math]::Abs((Dur $out[0]) - $script:MaxCaptionSeconds) -lt 1e-6) "stuck caption clamped (dur=$(Dur $out[0]))"

# 3) Overlapping ranges are trimmed (no overlap in output).
$out = @(Postprocess-Entries -Entries @((E 0 5 'Hello'), (E 3 7 'World')))
Assert-True ($out.Count -eq 2) "overlap keeps both captions"
Assert-True ((Parse-SrtTimestamp $out[0].End) -le (Parse-SrtTimestamp $out[1].Start)) "overlapping ranges trimmed"

# 4) Distinct captions unchanged.
$out = @(Postprocess-Entries -Entries @((E 1 3 'one'), (E 4 6 'two')))
Assert-True ($out.Count -eq 2 -and $out[0].Text -eq 'one' -and $out[1].Text -eq 'two') "distinct captions unchanged"

# 5) Blank/whitespace captions dropped.
$out = @(Postprocess-Entries -Entries @((E 1 2 '   '), (E 3 4 'kept')))
Assert-True ($out.Count -eq 1 -and $out[0].Text -eq 'kept') "blank caption dropped"

# 6) Out-of-order input is sorted by time.
$out = @(Postprocess-Entries -Entries @((E 5 6 'b'), (E 1 2 'a')))
Assert-True ($out[0].Text -eq 'a' -and $out[1].Text -eq 'b') "out-of-order input sorted"

# 6b) No output caption exceeds the max duration (not elongated unnecessarily).
$mixed = @((E 0 2 'ok'), (E 5 45 'long1'), (E 50 53 'ok2'), (E 60 600 'long2'))
$out = @(Postprocess-Entries -Entries $mixed)
$allWithinMax = $true
foreach ($e in $out) { if ((Dur $e) -gt ($script:MaxCaptionSeconds + 1e-6)) { $allWithinMax = $false } }
Assert-True $allWithinMax "no caption exceeds max duration"

# 6c) A caption is not stretched across a silent gap to the next utterance.
$out = @(Postprocess-Entries -Entries @((E 1 3 'hello'), (E 50 52 'world')))
$first = @($out | Where-Object { $_.Text -eq 'hello' })[0]
Assert-True ([Math]::Abs((Parse-SrtTimestamp $first.End) - 3.0) -lt 1e-6) "caption not stretched across silent gap"

# 6d) Parse-SrtFile drops [BLANK_AUDIO] markers (no captions during silence).
$blankSrt = Join-Path $env:TEMP ("sg_blank_{0}.srt" -f ([guid]::NewGuid().ToString('N')))
@"
1
00:00:00,000 --> 00:00:01,000
Hello

2
00:00:01,000 --> 00:00:05,000
[BLANK_AUDIO]

3
00:00:05,000 --> 00:00:06,000
World
"@ | Set-Content -Path $blankSrt -Encoding UTF8
try {
    $parsedBlank = @(Parse-SrtFile -Path $blankSrt)
    $texts = @($parsedBlank | ForEach-Object { $_.Text })
    Assert-True ($texts -notcontains '[BLANK_AUDIO]' -and $texts.Count -eq 2) "[BLANK_AUDIO] markers filtered on parse"
}
finally { Remove-Item $blankSrt -Force -ErrorAction SilentlyContinue }

# 7) Final written .srt file is sorted, non-overlapping, deduped, sequential.
$messy = @(
    (E 14 16 'Thank you.'), (E 10 12 'Thank you.'), (E 12 14 'Thank you.'),
    (E 3 7 'World'), (E 0 5 'Hello'), (E 60 120 '[Music]'),
    (E 2 3 '   '), (E 40 42 'mid')
)
$clean = @(Postprocess-Entries -Entries $messy)
$tmp = Join-Path $env:TEMP ("sg_ps_test_{0}.srt" -f ([guid]::NewGuid().ToString('N')))
try {
    Write-SrtFile -Path $tmp -Entries $clean
    $parsed = @(Parse-SrtFile -Path $tmp)

    $starts = @($parsed | ForEach-Object { Parse-SrtTimestamp $_.Start })
    $sorted = @($starts | Sort-Object)
    Assert-True (($starts -join ',') -eq ($sorted -join ',')) "final file sorted by start"

    $noOverlap = $true
    for ($i = 0; $i -lt $parsed.Count - 1; $i++) {
        if ((Parse-SrtTimestamp $parsed[$i].End) -gt (Parse-SrtTimestamp $parsed[$i + 1].Start)) { $noOverlap = $false }
    }
    Assert-True $noOverlap "final file has no overlapping ranges"

    $thankYou = @($parsed | Where-Object { $_.Text -eq 'Thank you.' })
    Assert-True ($thankYou.Count -eq 1) "repetition deduped in final file"

    $blanks = @($parsed | Where-Object { $_.Text.Trim() -eq '' })
    Assert-True ($blanks.Count -eq 0) "no blank captions in final file"

    $music = @($parsed | Where-Object { $_.Text -eq '[Music]' })[0]
    Assert-True ((Dur $music) -le ($script:MaxCaptionSeconds + 1e-6)) "stuck caption clamped in final file"

    $raw = Get-Content $tmp -Raw
    $blocks = [regex]::Split($raw.Trim(), '(?:\r?\n){2,}') | Where-Object { $_.Trim() -ne '' }
    $indices = @($blocks | ForEach-Object { [int](($_ -split '\r?\n')[0]) })
    $expected = @(1..$parsed.Count)
    Assert-True (($indices -join ',') -eq ($expected -join ',')) "sequential 1..N indices in file"
}
finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

if ($script:failures -gt 0) {
    Write-Host "FAILED: $($script:failures) assertion(s)" -ForegroundColor Red
    exit 1
}
Write-Host "OK: all PowerShell postprocess tests passed"
exit 0
