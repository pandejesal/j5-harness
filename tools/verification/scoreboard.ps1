<#
.SYNOPSIS
    Renders a quality scoreboard from .swarm/evidence/quality-scoreboard.jsonl.

.DESCRIPTION
    Reads a JSONL file where each line is a JSON object with quality metrics,
    then outputs a formatted markdown table. Works on any project that has
    the scoreboard JSONL file.

.PARAMETER JsonlPath
    Path to the quality-scoreboard.jsonl file. Defaults to .swarm\evidence\quality-scoreboard.jsonl
    in the current directory.

.PARAMETER Top
    Number of recent entries to show. Defaults to 5.

.EXAMPLE
    .\scoreboard.ps1
    .\scoreboard.ps1 -JsonlPath "C:\my-project\.swarm\evidence\quality-scoreboard.jsonl"
    .\scoreboard.ps1 -Top 10
#>

param(
    [string]$JsonlPath = ".swarm\evidence\quality-scoreboard.jsonl",
    [int]$Top = 5
)

if (-not (Test-Path $JsonlPath)) {
    Write-Error "Scoreboard file not found: $JsonlPath"
    Write-Host "No data to render. Run quality gates first to generate the JSONL file."
    exit 1
}

$lines = Get-Content $JsonlPath | Where-Object { $_.Trim() -ne "" }
if ($lines.Count -eq 0) {
    Write-Warning "Scoreboard file is empty: $JsonlPath"
    exit 0
}

# Parse JSONL entries
$entries = @()
foreach ($line in $lines) {
    try {
        $obj = $line | ConvertFrom-Json
        $entries += $obj
    } catch {
        Write-Warning "Skipping malformed JSONL line: $($line.Substring(0, [Math]::Min(80, $line.Length)))"
    }
}

if ($entries.Count -eq 0) {
    Write-Warning "No valid entries found in $JsonlPath"
    exit 0
}

# Take the most recent N entries
$recent = $entries | Select-Object -Last $Top

# Compute aggregate stats
$totalTests = ($recent | Measure-Object -Property test_pass_rate -Average).Average
$totalFindings = ($recent | Measure-Object -Property finding_density -Average).Average
$totalRework = ($recent | Measure-Object -Property rework_count -Average).Average
$totalFalseDone = ($recent | Measure-Object -Property false_done_count -Sum).Sum

# Output markdown table
Write-Host ""
Write-Host "# Quality Scoreboard"
Write-Host ""
Write-Host "| Task | Test Pass Rate | Finding Density | Rework Count | False DONE | Verdict |"
Write-Host "|------|---------------|-----------------|--------------|------------|---------|"

foreach ($e in $recent) {
    $task = if ($e.task_id) { $e.task_id } else { "N/A" }
    $tpr = if ($null -ne $e.test_pass_rate) { "$($e.test_pass_rate)%" } else { "N/A" }
    $fd = if ($null -ne $e.finding_density) { $e.finding_density } else { "N/A" }
    $rw = if ($null -ne $e.rework_count) { $e.rework_count } else { "N/A" }
    $fd_done = if ($null -ne $e.false_done_count) { $e.false_done_count } else { 0 }
    $verdict = if ($e.verdict) { $e.verdict } else { "N/A" }
    Write-Host "| $task | $tpr | $fd | $rw | $fd_done | $verdict |"
}

Write-Host ""
Write-Host "---"
Write-Host "**Aggregate (last $Top):** Avg test pass rate: $([Math]::Round($totalTests, 1))% | Avg finding density: $([Math]::Round($totalFindings, 2)) | Avg rework: $([Math]::Round($totalRework, 1)) | Total false DONE: $totalFalseDone"
Write-Host ""
