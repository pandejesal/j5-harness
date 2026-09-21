#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Automated Mnemosyne mirror export → MEMORY-MIRROR.md with staleness alerting.

.DESCRIPTION
    Runs mnemosyne export --json, pipes to build_mirror.py, atomic writes MEMORY-MIRROR.md.
    Emits MIRROR-STALE-<date>.md if mirror age >26h or export count drops >10% vs prior.
    Logs to 05-Session-Logs/mirror-<date>.log.

.NOTES
    Requires: mnemosyne.exe in PATH (C:\Users\DELL\anaconda3\Scripts\mnemosyne.exe)
    Requires: build_mirror.py in vault (06-Mnemosyne/tools/build_mirror.py)
    Scheduled: Daily 06:00 via Windows Task Scheduler
#>

param(
    [switch]$DryRun,
    [string]$VaultRoot = "C:\Users\DELL\Documents\Obsidian Vault",
    [string]$MnemosyneBin = "C:\Users\DELL\anaconda3\Scripts\mnemosyne.exe",
    [string]$MirrorPath = "C:\Users\DELL\Documents\Obsidian Vault\06-Mnemosyne\MEMORY-MIRROR.md",
    [string]$ExportDir = "C:\Users\DELL\Documents\Obsidian Vault\06-Mnemosyne\exports",
    [string]$BuildMirrorPy = "C:\Users\DELL\Documents\Obsidian Vault\06-Mnemosyne\tools\build_mirror.py",
    [string]$LogDir = "C:\Users\DELL\Documents\Obsidian Vault\05-Session-Logs",
    [string]$StaleDir = "C:\Users\DELL\Documents\Obsidian Vault\00-Inbox",
    [int]$MaxAgeHours = 26,
    [double]$CountDropPct = 10.0
)

$ErrorActionPreference = "Stop"

function Log {
    param([string]$msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    if ($global:logFile) { Add-Content -Path $global:logFile -Value $line }
}

function Get-ExportCount {
    param([string]$jsonFile)
    if (-not (Test-Path $jsonFile)) { return 0 }
    try {
        $data = Get-Content $jsonFile -Raw | ConvertFrom-Json
        return ($data.working_memories?.Count + $data.episodic_memories?.Count + $data.consolidations?.Count)
    } catch { return 0 }
}

function Write-StaleAlert {
    param([string]$reason)
    $date = Get-Date -Format "yyyy-MM-dd"
    $path = Join-Path $global:staleDir "MIRROR-STALE-$date.md"
    $content = @"
# Mirror Staleness Alert — $date

**Reason:** $reason
**Mirror:** $global:mirrorPath
**Detected:** $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Run manual mirror:
\`\`\`powershell
mnemosyne export "$env:USERPROFILE\Documents\Obsidian Vault\06-Mnemosyne\exports\mnemosyne-export-$(Get-Date -Format yyyy-MM-dd).json"
python $env:USERPROFILE\Documents\Obsidian Vault\06-Mnemosyne\tools\build_mirror.py
\`\`\`
"@
    $content | Set-Content -Path $path -Encoding UTF8
    Log "STALE ALERT: $reason → $path"
}

# Initialize
$global:mirrorPath = $MirrorPath
$global:staleDir = $StaleDir
$logFile = Join-Path $LogDir "mirror-$(Get-Date -Format yyyyMMdd).log"
$global:logFile = $logFile
if (-not (Test-Path (Split-Path $logFile -Parent))) { New-Item -ItemType Directory -Path (Split-Path $logFile -Parent) -Force | Out-Null }
Log "=== Mirror job start ==="

# Verify prerequisites
if (-not (Test-Path $MnemosyneBin)) { Log "ERROR: mnemosyne.exe not found at $MnemosyneBin"; exit 1 }
if (-not (Test-Path $BuildMirrorPy)) { Log "ERROR: build_mirror.py not found at $BuildMirrorPy"; exit 1 }
if (-not (Test-Path $ExportDir)) { New-Item -ItemType Directory -Path $ExportDir -Force | Out-Null }

$exportFile = Join-Path $ExportDir "mnemosyne-export-$(Get-Date -Format yyyy-MM-dd).json"
$tempExport = $exportFile + ".tmp"
$tempMirror = $MirrorPath + ".tmp"

# Export
Log "Running mnemosyne export..."
if ($DryRun) { Log "DRY-RUN: would run `$MnemosyneBin export --json > $exportFile`" }
else {
    & $MnemosyneBin export --json > $tempExport 2>&1
    if ($LASTEXITCODE -ne 0) { Log "ERROR: mnemosyne export failed (exit $LASTEXITCODE)"; exit 1 }
    Move-Item -Path $tempExport -Destination $exportFile -Force
    Log "Export written: $exportFile"
}

# Build mirror
$count = Get-ExportCount $exportFile
Log "Export count: $count items"

if ($DryRun) { Log "DRY-RUN: would run python $BuildMirrorPy --stdin < $exportFile > $tempMirror" }
else {
    $json = Get-Content $exportFile -Raw
    $result = $json | python $BuildMirrorPy --stdin
    if ($LASTEXITCODE -ne 0) { Log "ERROR: build_mirror.py failed"; exit 1 }
    $result | Set-Content -Path $tempMirror -Encoding UTF8
    Move-Item -Path $tempMirror -Destination $MirrorPath -Force
    Log "Mirror updated: $MirrorPath"
}

# Staleness checks
$mirrorAge = (Get-Date) - (Get-Item $MirrorPath).LastWriteTime
if ($mirrorAge.TotalHours -gt $MaxAgeHours) {
    Write-StaleAlert "Mirror age $([math]::Round($mirrorAge.TotalHours,1))h > $MaxAgeHours h threshold"
}

$priorExport = Get-ChildItem $ExportDir -Filter "mnemosyne-export-*.json" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 1 -First 1
if ($priorExport) {
    $priorCount = Get-ExportCount $priorExport.FullName
    if ($priorCount -gt 0) {
        $dropPct = (($priorCount - $count) / $priorCount) * 100
        if ($dropPct -gt $CountDropPct) {
            Write-StaleAlert "Export count dropped $([math]::Round($dropPct,1))% ($priorCount → $count) > $CountDropPct% threshold"
        }
    }
}

Log "=== Mirror job complete ==="
exit 0