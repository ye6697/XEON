# XEON - Intro Launch Session (Windows)

$LOCAL_PYTHON = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$PYTHON_EXE = if (Test-Path $LOCAL_PYTHON) { $LOCAL_PYTHON } else { "python" }
$WORKSPACE_PATH = Resolve-Path (Join-Path $PSScriptRoot "..")
$XEON_LAUNCHER = Join-Path $WORKSPACE_PATH "xeon_launcher.py"

$previousStartPath = $env:XEON_START_PATH
$env:XEON_START_PATH = "/intro"
try {
    Start-Process -FilePath $PYTHON_EXE `
        -ArgumentList "`"$XEON_LAUNCHER`"" `
        -WorkingDirectory $WORKSPACE_PATH `
        -WindowStyle Hidden
} finally {
    if ($null -eq $previousStartPath) {
        Remove-Item Env:\XEON_START_PATH -ErrorAction SilentlyContinue
    } else {
        $env:XEON_START_PATH = $previousStartPath
    }
}
