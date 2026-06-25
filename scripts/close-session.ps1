# XEON - Close Session

$portProcess = Get-NetTCPConnection -LocalPort 8340 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty OwningProcess

if ($portProcess) {
    Stop-Process -Id $portProcess -Force -ErrorAction SilentlyContinue
}

Get-Process -Name "chrome" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like "*XEON*" -or $_.MainWindowTitle -like "*Globe*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
