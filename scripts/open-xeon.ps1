# XEON - Open desktop app window

$WorkspacePath = Resolve-Path (Join-Path $PSScriptRoot "..")
$ConfigPath = Join-Path $WorkspacePath "config.json"
$Config = Get-Content $ConfigPath | ConvertFrom-Json

$LocalPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$PythonExe = if (Test-Path $LocalPython) { $LocalPython } else { "python" }
$ServerLog = Join-Path $WorkspacePath "xeon-server.log"
$ServerErrLog = Join-Path $WorkspacePath "xeon-server.err.log"
$ChromeProfile = Join-Path $WorkspacePath "chrome-xeon-profile"

$server = Get-NetTCPConnection -LocalPort 8340 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $server) {
    Start-Process -FilePath $PythonExe `
        -ArgumentList "`"$WorkspacePath\server.py`"" `
        -WorkingDirectory $WorkspacePath `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ServerLog `
        -RedirectStandardError $ServerErrLog
    Start-Sleep -Seconds 4
}

$chromeArgs = "--new-window --app=http://localhost:8340 --user-data-dir=`"$ChromeProfile`" --autoplay-policy=no-user-gesture-required"
Start-Process "chrome" -ArgumentList $chromeArgs
