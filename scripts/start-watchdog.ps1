# XEON - start watchdog hidden

$WorkspacePath = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogPath = Join-Path $WorkspacePath "xeon-watchdog.out.log"
$ErrPath = Join-Path $WorkspacePath "xeon-watchdog.err.log"
$ScriptPath = Join-Path $PSScriptRoot "xeon-watchdog.ps1"

$existing = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
    Where-Object { $_.CommandLine -like "*xeon-watchdog.ps1*" }

if (-not $existing) {
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`"" `
        -WorkingDirectory $WorkspacePath `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogPath `
        -RedirectStandardError $ErrPath
}
