# XEON - Close Session

Get-Process -Name "XEON" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

Start-Sleep -Milliseconds 250

$remaining = Get-Process -Name "XEON" -ErrorAction SilentlyContinue
if ($remaining) {
    & taskkill.exe /IM XEON.exe /T /F 2>$null | Out-Null
}

$WorkspacePath = Resolve-Path (Join-Path $PSScriptRoot "..")
$ChromeProfile = Join-Path $WorkspacePath "chrome-xeon-profile"

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.CommandLine -like "*xeon_launcher.py*") -or
        ($_.CommandLine -like "*$ChromeProfile*") -or
        ($_.CommandLine -like "*localhost:8340*" -and $_.Name -match "chrome|msedge")
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
