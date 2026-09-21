<#
.SYNOPSIS
  Daily DB health check — size, journal_mode, freelist, page stats.
  Output: .swarm\reliability\db-health.jsonl (append one JSON line per run)
  Warns at >2GB, critical at >8GB.

.RUNBOOK
  backup steps:
    1. copy <db>, <db>-wal, <db>-shm to backup dir
    2. sqlite3 <db> "PRAGMA integrity_check;"
    3. retain last 7 backups, delete older
  restore:
    1. stop all node processes touching the db
    2. copy backup files back
    3. verify integrity_check = ok
#>

param(
  [string]$DbPath = (Join-Path $env:USERPROFILE ".local\share\opencode\opencode.db"),
  [string]$LogDir = (Join-Path $env:USERPROFILE ".swarm\reliability"),
  [string]$BackupDir = (Join-Path $env:USERPROFILE ".swarm\reliability\db-backups")
)

$ErrorActionPreference = "SilentlyContinue"

# --- locate sqlite3 CLI (best-effort) ---
$sqlite = $null
foreach ($c in @("sqlite3", "sqlite3.exe")) {
  $found = Get-Command $c -ErrorAction SilentlyContinue
  if ($found) { $sqlite = $found.Source; break }
}
# fallback: common install paths
if (-not $sqlite) {
  foreach ($p in @(
    "C:\tools\sqlite3.exe",
    "C:\ProgramData\chocolatey\bin\sqlite3.exe",
    "$env:LOCALAPPDATA\Programs\sqlite3\sqlite3.exe"
  )) {
    if (Test-Path $p) { $sqlite = $p; break }
  }
}

# --- gather file stats ---
$dbExists  = Test-Path $DbPath
$walExists = Test-Path "$DbPath-wal"
$shmExists = Test-Path "$DbPath-shm"
$sizeBytes = if ($dbExists) { (Get-Item $DbPath).Length } else { 0 }
$walBytes  = if ($walExists) { (Get-Item "$DbPath-wal").Length } else { 0 }
$shmBytes  = if ($shmExists) { (Get-Item "$DbPath-shm").Length } else { 0 }
$totalMB   = [math]::Round(($sizeBytes + $walBytes + $shmBytes) / 1MB, 2)

# --- severity ---
$severity = "ok"
if ($totalMB -gt 8192) { $severity = "critical" }
elseif ($totalMB -gt 2048) { $severity = "warn" }

# --- PRAGMA stats (best-effort) ---
$pragmaStats = @{}
if ($sqlite -and $dbExists) {
  try {
    $journalRaw = & $sqlite $DbPath "PRAGMA journal_mode;" 2>&1
    $pragmaStats.journal_mode = ($journalRaw | Select-Object -First 1).ToString().Trim()
  } catch { $pragmaStats.journal_mode = "error" }
  try {
    $freelistRaw = & $sqlite $DbPath "PRAGMA freelist_count;" 2>&1
    $pragmaStats.freelist_count = [int](($freelistRaw | Select-Object -First 1).ToString().Trim())
  } catch { $pragmaStats.freelist_count = "error" }
  try {
    $pageCountRaw = & $sqlite $DbPath "PRAGMA page_count;" 2>&1
    $pragmaStats.page_count = [int](($pageCountRaw | Select-Object -First 1).ToString().Trim())
  } catch { $pragmaStats.page_count = "error" }
  try {
    $pageSizeRaw = & $sqlite $DbPath "PRAGMA page_size;" 2>&1
    $pragmaStats.page_size = [int](($pageSizeRaw | Select-Object -First 1).ToString().Trim())
  } catch { $pragmaStats.page_size = "error" }
}

# --- write log entry ---
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$entry = [ordered]@{
  ts              = (Get-Date -Format "o")
  dbPath          = $DbPath
  dbExists        = $dbExists
  sizeMB          = [math]::Round($sizeBytes / 1MB, 2)
  walMB           = [math]::Round($walBytes / 1MB, 2)
  shmMB           = [math]::Round($shmBytes / 1MB, 2)
  totalMB         = $totalMB
  severity        = $severity
  pragma          = $pragmaStats
  sqliteAvailable = [bool]$sqlite
}
$jsonLine = $entry | ConvertTo-Json -Compress
$logFile  = Join-Path $LogDir "db-health.jsonl"
Add-Content -Path $logFile -Value $jsonLine -Encoding UTF8

# --- console output ---
Write-Host "=== DB Health Check ===" -ForegroundColor Cyan
Write-Host "DB:          $DbPath"
Write-Host "Exists:      $dbExists"
Write-Host "DB size:     $([math]::Round($sizeBytes / 1MB, 2)) MB"
Write-Host "WAL size:    $([math]::Round($walBytes / 1MB, 2)) MB"
Write-Host "SHM size:    $([math]::Round($shmBytes / 1MB, 2)) MB"
Write-Host "Total:       $totalMB MB"
if ($pragmaStats.Count -gt 0) {
  Write-Host "PRAGMA:      $($pragmaStats | ConvertTo-Json -Compress)"
}

switch ($severity) {
  "warn"     { Write-Host "⚠️  WARN: DB total >2 GB — consider VACUUM or migration." -ForegroundColor Yellow }
  "critical" { Write-Host "🔴 CRITICAL: DB total >8 GB — immediate action required." -ForegroundColor Red }
  default    { Write-Host "✅ OK — DB within healthy limits." -ForegroundColor Green }
}

Write-Host "`nLogged to: $logFile"

# --- backup reminder ---
if ($severity -ne "ok") {
  Write-Host "`n--- Backup Runbook ---" -ForegroundColor Magenta
  Write-Host "1. Stop all node processes touching the DB."
  Write-Host "2. Copy: $DbPath, $DbPath-wal, $DbPath-shm → $BackupDir"
  Write-Host "3. Run: sqlite3 `"$DbPath`" `"PRAGMA integrity_check;`""
  Write-Host "4. Retain last 7 backups, delete older."
}
