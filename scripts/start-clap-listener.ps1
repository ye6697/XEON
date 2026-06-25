# XEON - Start persistent clap listener hidden

$WorkspacePath = Resolve-Path (Join-Path $PSScriptRoot "..")
$LocalPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$PythonExe = if (Test-Path $LocalPython) { $LocalPython } else { "python" }
$LogPath = Join-Path $WorkspacePath "xeon-clap-listener.log"
$ErrPath = Join-Path $WorkspacePath "xeon-clap-listener.err.log"
$ScriptPath = Join-Path $WorkspacePath "scripts\clap-trigger.py"

$existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*clap-trigger.py*" }

if (-not $existing) {
    Start-Process -FilePath $PythonExe `
        -ArgumentList "`"$ScriptPath`"" `
        -WorkingDirectory $WorkspacePath `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogPath `
        -RedirectStandardError $ErrPath
}

& (Join-Path $PSScriptRoot "start-activity-monitor.ps1")
& (Join-Path $PSScriptRoot "start-reminder-monitor.ps1")
