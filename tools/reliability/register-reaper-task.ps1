<#
.SYNOPSIS
  Registers (or unregisters) the OpenCode-MCP-Reaper scheduled task.
.DESCRIPTION
  Creates a scheduled task that runs mcp-reaper.ps1 every 15 minutes.
  Use -Unregister to remove the task.
.EXAMPLE
  .\register-reaper-task.ps1
  .\register-reaper-task.ps1 -Unregister
#>

param(
  [string]$ScriptPath = (Join-Path $PSScriptRoot "mcp-reaper.ps1"),
  [string]$TaskName = "OpenCode-MCP-Reaper",
  [switch]$Unregister
)

$ErrorActionPreference = "Stop"

if ($Unregister) {
  $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered scheduled task: $TaskName" -ForegroundColor Green
  } else {
    Write-Host "No scheduled task named $TaskName found." -ForegroundColor Yellow
  }
  return
}

if (-not (Test-Path $ScriptPath)) {
  Write-Error "Script not found: $ScriptPath"
  exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Scheduled task $TaskName already exists - unregistering first..." -ForegroundColor Yellow
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Reap orphaned opencode MCP node.exe processes every 15 min" | Out-Null

Write-Host "Registered scheduled task: $TaskName" -ForegroundColor Green
Write-Host "  Script:  $ScriptPath"
Write-Host "  Trigger: every 15 minutes"

# proof
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, TaskPath | Format-List