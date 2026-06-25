# XEON - Install Windows logon task for persistent double-clap listener

$TaskName = "XEON Clap Listener"
$StartScript = Resolve-Path (Join-Path $PSScriptRoot "start-clap-listener.ps1")
$ActivityScript = Resolve-Path (Join-Path $PSScriptRoot "start-activity-monitor.ps1")
$ReminderScript = Resolve-Path (Join-Path $PSScriptRoot "start-reminder-monitor.ps1")
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Settings $Settings `
        -Force `
        -ErrorAction Stop | Out-Null

    Write-Host "Installed scheduled task: $TaskName"
} catch {
    $StartupDir = [Environment]::GetFolderPath("Startup")
    $CmdPath = Join-Path $StartupDir "XEON Clap Listener.cmd"
    $Cmd = "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`"`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ActivityScript`"`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ReminderScript`"`r`n"
    Set-Content -Path $CmdPath -Value $Cmd -Encoding ASCII
    Write-Host "Scheduled task failed, installed startup shortcut instead: $CmdPath"
}
