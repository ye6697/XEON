# XEON - background watchdog for local helper processes

$WorkspacePath = Resolve-Path (Join-Path $PSScriptRoot "..")
$StartClap = Join-Path $PSScriptRoot "start-clap-listener.ps1"
$StartActivity = Join-Path $PSScriptRoot "start-activity-monitor.ps1"
$StartReminder = Join-Path $PSScriptRoot "start-reminder-monitor.ps1"
$LogPath = Join-Path $WorkspacePath "xeon-watchdog.log"

function Write-WatchdogLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "$stamp $Message" -Encoding ASCII
}

function Has-ProcessCommand {
    param([string]$Needle)
    $found = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Needle*" } |
        Select-Object -First 1
    return [bool]$found
}

Write-WatchdogLog "started"

while ($true) {
    try {
        if (-not (Has-ProcessCommand "clap-trigger.py")) {
            Write-WatchdogLog "starting clap listener"
            & $StartClap
        }
        if (-not (Has-ProcessCommand "activity-monitor.py")) {
            Write-WatchdogLog "starting activity monitor"
            & $StartActivity
        }
        if (-not (Has-ProcessCommand "reminder-monitor.py")) {
            Write-WatchdogLog "starting reminder monitor"
            & $StartReminder
        }
    } catch {
        Write-WatchdogLog "error: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 10
}
