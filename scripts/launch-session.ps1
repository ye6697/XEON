# XEON - Launch Session (Windows)

# Load config
$configPath = Join-Path $PSScriptRoot "..\config.json"
$config = Get-Content $configPath | ConvertFrom-Json

$WORKSPACE_PATH = $config.workspace_path
$SPOTIFY_URI = $config.spotify_track
$BROWSER_URL = $config.browser_url
$LOCAL_PYTHON = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$PYTHON_EXE = if (Test-Path $LOCAL_PYTHON) { $LOCAL_PYTHON } else { "python" }
$SERVER_LOG = Join-Path $WORKSPACE_PATH "xeon-server.log"
$SERVER_ERR_LOG = Join-Path $WORKSPACE_PATH "xeon-server.err.log"
$XEON_CHROME_PROFILE = Join-Path $WORKSPACE_PATH "chrome-xeon-profile"

# Load assemblies
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinPos {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int W, int H, bool repaint);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

function Snap-Window($proc, $x, $y, $w, $h) {
    if ($proc) {
        [WinPos]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
        Start-Sleep -Milliseconds 200
        [WinPos]::MoveWindow($proc.MainWindowHandle, $x, $y, $w, $h, $true) | Out-Null
    }
}

$screenW = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Width
$screenH = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Height
$halfW = [math]::Floor($screenW / 2)
$halfH = [math]::Floor($screenH / 2)

# 1. Start server + Spotify + apps
$server = Get-NetTCPConnection -LocalPort 8340 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $server) {
    Start-Process -FilePath $PYTHON_EXE -ArgumentList "`"$WORKSPACE_PATH\server.py`"" -WorkingDirectory $WORKSPACE_PATH -WindowStyle Hidden -RedirectStandardOutput $SERVER_LOG -RedirectStandardError $SERVER_ERR_LOG
    Start-Sleep -Seconds 4
}

if ($SPOTIFY_URI -and $SPOTIFY_URI -notlike "*YOUR_TRACK_ID*") {
    Start-Process $SPOTIFY_URI
}

if (Get-Command code -ErrorAction SilentlyContinue) {
    code $WORKSPACE_PATH
}

foreach ($app in $config.apps) {
    if ($app) { Start-Process $app }
}

# 2. Chrome with XEON + configured website
$chromeArgs = "--new-window --user-data-dir=`"$XEON_CHROME_PROFILE`" --autoplay-policy=no-user-gesture-required http://localhost:8340"
if ($BROWSER_URL -and $BROWSER_URL -notlike "*your-website.com*") {
    $chromeArgs = "$chromeArgs $BROWSER_URL"
}
Start-Process "chrome" -ArgumentList $chromeArgs

# 3. Snap all windows into quadrants
Start-Sleep -Seconds 3

$vscode = Get-Process -Name "Code" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $vscode 0 0 $halfW $halfH

$obsidian = Get-Process -Name "Obsidian" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $obsidian $halfW 0 $halfW $halfH

$chrome = Get-Process -Name "chrome" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $chrome 0 $halfH $halfW $halfH

$spotify = Get-Process -Name "Spotify" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
Snap-Window $spotify $halfW $halfH $halfW $halfH
