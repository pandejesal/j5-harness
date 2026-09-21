<#
.SYNOPSIS
  Idempotent MCP orphan reaper -- kills stale node.exe processes from opencode MCP servers.
.DESCRIPTION
  Scans Win32_Process for node.exe matching opencode|stock-scanner|code-review|shadcn.
  Pairs wrapper+child via ParentProcessId. Kills when:
    - parent dead (orphan)
    - age > orphanAgeH from config
    - project disabled in config
  Supports -WhatIf, pre-kill opencode.db handle check, post-kill SQLite WAL checkpoint.
  Logs to Temp\opencode\reliability\mcp-reaper-<date>.log + per-project .swarm\reliability\mcp.jsonl.
  Outputs REAPER-ALERT line when killed>0 or lock-held.
#>

param(
  [switch]$WhatIf,
  [string]$ConfigPath = (Join-Path $PSScriptRoot "reliability.config.json")
)

$ErrorActionPreference = "SilentlyContinue"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# --- load config ---
if (-not (Test-Path $ConfigPath)) {
  Write-Host "[$ts] CONFIG NOT FOUND: $ConfigPath -- using defaults" -ForegroundColor Yellow
  $cfg = @{
    defaults = @{ orphanAgeH = 4; langserverCapMB = 650 }
    projects = @{}
    dirs = @{}
  }
} else {
  $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
}

$orphanAgeH  = $cfg.defaults.orphanAgeH
$logBase     = Join-Path $env:TEMP "opencode\reliability"
if (-not (Test-Path $logBase)) { New-Item -ItemType Directory -Path $logBase -Force | Out-Null }
$logFile     = Join-Path $logBase ("mcp-reaper-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Log($msg) {
  $line = "[$ts] $msg"
  Add-Content -Path $logFile -Value $line -Encoding UTF8
  Write-Host $line
}

Log ("=== MCP Reaper start (WhatIf=" + $WhatIf + ") ===")

# --- discover node.exe processes ---
$allNodes = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
if (-not $allNodes) {
  Log "No node.exe processes found. Nothing to reap."
  Write-Host "REAPER-ALERT: killed=0 lock-held=false" -ForegroundColor Green
  return
}

# --- match MCP-related processes ---
$mcpPattern = "opencode|stock-scanner|code-review|shadcn|mcp"
$mcpProcs   = $allNodes | Where-Object {
  $_.CommandLine -match $mcpPattern
}

if (-not $mcpProcs) {
  Log "No MCP-related node.exe processes found. Nothing to reap."
  Write-Host "REAPER-ALERT: killed=0 lock-held=false" -ForegroundColor Green
  return
}

Log ("Found " + $mcpProcs.Count + " MCP-related node.exe processes")

# --- build parent lookup ---
$procById = @{}
foreach ($p in $allNodes) { $procById[$p.ProcessId] = $p }

# --- determine project from command line ---
function Get-ProjectName($cmdLine) {
  if ($cmdLine -match "wsb.alpha|wsb-alpha") { return "wsb-alpha" }
  if ($cmdLine -match "burgonomic") { return "burgonomics" }
  if ($cmdLine -match "safe.sponsor|safe-sponsor") { return "safe-sponsor-ai" }
  if ($cmdLine -match "resonan") { return "resonance" }
  return "unknown"
}

# --- resolve project dirs for jsonl logging (from config dirs map) ---
function Get-ProjectDir($name) {
  $dir = $cfg.dirs.$name
  if ($dir -and (Test-Path $dir)) { return $dir }
  return $null
}

# --- check if opencode.db is locked by a process ---
function Test-DbLock($dbPath) {
  if (-not (Test-Path $dbPath)) { return $false }
  try {
    $fs = [System.IO.File]::Open($dbPath, "Open", "Read", "None")
    $fs.Close()
    return $false
  } catch {
    return $true
  }
}

$dbPath  = Join-Path $env:USERPROFILE ".local\share\opencode\opencode.db"
$dbLocked = Test-DbLock $dbPath
if ($dbLocked) { Log "opencode.db is LOCKED by a live process" }

$lockedProjects = @()
$killed = 0

foreach ($proc in $mcpProcs) {
  $pid     = $proc.ProcessId
  $ppid    = $proc.ParentProcessId
  $cmdLine = $proc.CommandLine
  $ageH    = [math]::Round(((Get-Date) - $proc.CreationDate).TotalHours, 1)
  $project = Get-ProjectName $cmdLine
  $parentAlive = $procById.ContainsKey($ppid)

  $reason = $null
  if (-not $parentAlive) {
    $reason = "orphan (parent " + $ppid + " dead)"
  } elseif ($ageH -gt $orphanAgeH) {
    $reason = "age " + $ageH + "h > " + $orphanAgeH + "h threshold"
  } else {
    $projCfg = $cfg.projects.$project
    if ($projCfg -and -not $projCfg.enabled) {
      $reason = "project " + $project + " disabled in config"
    }
  }

  if ($reason) {
    $killAction = if ($WhatIf) { "WOULD-KILL" } else { "KILLING" }
    Log ($killAction + " pid=" + $pid + " ppid=" + $ppid + " age=" + $ageH + "h project=" + $project + " reason=" + $reason)
    Log ("  cmd: " + $cmdLine.Substring(0, [Math]::Min(200, $cmdLine.Length)))

    if (-not $WhatIf) {
      # pre-kill: check if this process holds the db lock
      if ($dbLocked) {
        $handleMatch = $false
        try {
          $handleInfo = & handle.exe -p $pid 2>&1
          if ($handleInfo -match "opencode\.db") { $handleMatch = $true }
        } catch {}
        if ($handleMatch) {
          Log ("  WARNING: pid=" + $pid + " HOLDS opencode.db lock")
          $lockedProjects += $project
        }
      }
      try {
        Stop-Process -Id $pid -Force -ErrorAction Stop
        $killed++
        Log ("  Killed pid=" + $pid + " successfully")
      } catch {
        Log ("  Failed to kill pid=" + $pid + ": " + $_)
      }
    } else {
      $killed++
    }

    # per-project jsonl log
    $pDir = Get-ProjectDir $project
    if ($pDir) {
      $swarmRel = Join-Path $pDir ".swarm\reliability"
      if (-not (Test-Path $swarmRel)) { New-Item -ItemType Directory -Path $swarmRel -Force | Out-Null }
      $action = if ($WhatIf) { "would-kill" } else { "killed" }
      $jsonlEntry = @{ ts = $ts; action = $action; pid = $pid; ppid = $ppid; ageH = $ageH; project = $project; reason = $reason } | ConvertTo-Json -Compress
      Add-Content -Path (Join-Path $swarmRel "mcp.jsonl") -Value $jsonlEntry -Encoding UTF8
    }
  } else {
    Log ("KEEP pid=" + $pid + " ppid=" + $ppid + " age=" + $ageH + "h project=" + $project + " (alive, young, enabled)")
  }
}

# --- post-kill: SQLite WAL checkpoint (best-effort) ---
if ($killed -gt 0 -and -not $WhatIf -and $dbLocked) {
  $sqlite = $null
  foreach ($c in @("sqlite3", "sqlite3.exe")) {
    $found = Get-Command $c -ErrorAction SilentlyContinue
    if ($found) { $sqlite = $found.Source; break }
  }
  if ($sqlite) {
    Log "Attempting post-kill WAL checkpoint..."
    try {
      & $sqlite $dbPath "PRAGMA wal_checkpoint(TRUNCATE);" 2>&1 | Out-Null
      Log "WAL checkpoint completed"
    } catch {
      Log ("WAL checkpoint failed (best-effort): " + $_)
    }
  } else {
    Log "sqlite3 not found -- skipping WAL checkpoint"
  }
}

# --- summary ---
$lockHeld = $lockedProjects.Count -gt 0
Log ("=== Reaper done: killed=" + $killed + " lock-held=" + $lockHeld + " ===")

if ($killed -gt 0 -or $lockHeld) {
  $alertMsg = "REAPER-ALERT: killed=" + $killed + " lock-held=" + $lockHeld
  if ($lockHeld) { $alertMsg = $alertMsg + " projects=" + ($lockedProjects -join ",") }
  Write-Host $alertMsg -ForegroundColor Red
} else {
  Write-Host "REAPER-ALERT: killed=0 lock-held=false" -ForegroundColor Green
}
