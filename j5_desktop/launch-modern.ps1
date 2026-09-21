#Requires -Version 5.1
<#
.SYNOPSIS
    Launch the J5 Harness Modern Desktop (PyQt5 command center).
.DESCRIPTION
    Starts modern_app.py with pythonw.exe so no console window flashes.
    All stdout/stderr goes to log files next to this script, and any fatal
    preflight failure is shown in a message box instead of dying silently
    (the old "opens then instantly closes" problem).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File j5_desktop\launch-modern.ps1
#>

$ErrorActionPreference = 'Stop'

function Show-Fatal([string] $message) {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show(
        $message, 'J5 Harness — launch failed',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

try {
    $app = Join-Path $PSScriptRoot 'modern_app.py'
    if (-not (Test-Path -LiteralPath $app)) {
        throw "modern_app.py not found at $app"
    }
    $workdir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $outLog = Join-Path $PSScriptRoot 'modern-app.out.log'
    $errLog = Join-Path $PSScriptRoot 'modern-app.err.log'

    $pythonCmd = Get-Command python -ErrorAction Stop
    $pythonDir = Split-Path -Parent $pythonCmd.Source
    $pythonw = Join-Path $pythonDir 'pythonw.exe'
    $launcher = $pythonw
    if (-not (Test-Path -LiteralPath $pythonw)) {
        $launcher = $pythonCmd.Source  # fallback: console python
    }

    # Preflight: PyQt5 must import (Qt6 is broken in this Anaconda env).
    & $pythonCmd.Source -c "import PyQt5.QtWidgets; print('preflight ok')" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PyQt5 failed to import. Run: pip install PyQt5`nSee $errLog for details."
    }

    # Avoid stacking duplicate windows.
    $already = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*modern_app.py*' }
    if ($already) {
        Write-Host "J5 Modern Desktop is already running (PID $($already.ProcessId -join ', '))."
        return
    }

    Start-Process -FilePath $launcher -ArgumentList "`"$app`"" `
        -WorkingDirectory $workdir `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
        -WindowStyle Hidden

    Write-Host "J5 Modern Desktop launching…"
    Write-Host "  stdout: $outLog"
    Write-Host "  stderr: $errLog"
}
catch {
    $msg = $_.Exception.Message
    Write-Error $msg
    try { Show-Fatal $msg } catch { }
    exit 1
}
