# XEON - Launch Session (Windows)

param(
    [string]$Mode = ""
)

$LOCAL_PYTHON = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$PYTHON_EXE = if (Test-Path $LOCAL_PYTHON) { $LOCAL_PYTHON } else { "python" }
$WORKSPACE_PATH = Resolve-Path (Join-Path $PSScriptRoot "..")
$XEON_EXE = Join-Path $WORKSPACE_PATH "XEON.exe"
$XEON_LAUNCHER = Join-Path $WORKSPACE_PATH "xeon_launcher.py"

if ($Mode -eq "focus_guard") {
    $env:XEON_START_PATH = "/?focus_guard=1&v=focus-guard-1"
} elseif (-not $env:XEON_START_PATH) {
    $env:XEON_START_PATH = "/"
}

if ($Mode -eq "focus_guard" -and (Test-Path $XEON_LAUNCHER)) {
    Start-Process -FilePath $PYTHON_EXE `
        -ArgumentList "`"$XEON_LAUNCHER`"" `
        -WorkingDirectory $WORKSPACE_PATH `
        -WindowStyle Hidden
} elseif (Test-Path $XEON_EXE) {
    Start-Process -FilePath $XEON_EXE -WorkingDirectory $WORKSPACE_PATH
} elseif (Test-Path $XEON_LAUNCHER) {
    Start-Process -FilePath $PYTHON_EXE `
        -ArgumentList "`"$XEON_LAUNCHER`"" `
        -WorkingDirectory $WORKSPACE_PATH `
        -WindowStyle Hidden
} else {
    Start-Process -FilePath $PYTHON_EXE `
        -ArgumentList "`"$WORKSPACE_PATH\server.py`"" `
        -WorkingDirectory $WORKSPACE_PATH `
        -WindowStyle Hidden
}
