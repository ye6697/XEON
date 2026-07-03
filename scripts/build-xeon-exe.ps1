# Build slim XEON.exe native desktop launcher

$WorkspacePath = Resolve-Path (Join-Path $PSScriptRoot "..")
$LocalPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$PythonExe = if (Test-Path $LocalPython) { $LocalPython } else { "python" }

Push-Location $WorkspacePath
try {
    & $PythonExe -m pip install --upgrade pywebview pyinstaller
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --name XEON `
        --onefile `
        --windowed `
        --icon "assets\xeon.ico" `
        xeon_launcher.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Copy-Item -Path "dist\XEON.exe" -Destination "XEON.exe" -Force

    Write-Host "Built: $WorkspacePath\XEON.exe"
    Write-Host "XEON.exe must stay next to server.py, frontend, config.json, and .env so all backend tools remain available."
}
finally {
    Pop-Location
}