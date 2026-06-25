# XEON - Start local reminder monitor hidden

$WorkspacePath = Resolve-Path (Join-Path $PSScriptRoot "..")
$LocalPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$PythonExe = if (Test-Path $LocalPython) { $LocalPython } else { "python" }
$LogPath = Join-Path $WorkspacePath "xeon-reminder-monitor.log"
$ErrPath = Join-Path $WorkspacePath "xeon-reminder-monitor.err.log"
$ScriptPath = Join-Path $WorkspacePath "scripts\reminder-monitor.py"

$existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*reminder-monitor.py*" }

if (-not $existing) {
    Start-Process -FilePath $PythonExe `
        -ArgumentList "`"$ScriptPath`"" `
        -WorkingDirectory $WorkspacePath `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogPath `
        -RedirectStandardError $ErrPath
}
