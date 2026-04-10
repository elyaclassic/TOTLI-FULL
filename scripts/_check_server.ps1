Write-Host "=== Python jarayonlari ===" -ForegroundColor Cyan
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, StartTime, @{N='RAM_MB';E={[math]::Round($_.WorkingSet64/1MB,0)}} | Format-Table -AutoSize

Write-Host "=== DEV_MODE env o'zgaruvchi ===" -ForegroundColor Cyan
$m = [Environment]::GetEnvironmentVariable('DEV_MODE', 'Machine')
$u = [Environment]::GetEnvironmentVariable('DEV_MODE', 'User')
Write-Host "Machine: $m"
Write-Host "User:    $u"

Write-Host ""
Write-Host "=== Server qaysi portda eshitayapti (8080) ===" -ForegroundColor Cyan
$conn = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $procId = $conn.OwningProcess | Select-Object -First 1
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    Write-Host "Port 8080 tinglayapti, PID: $procId"
    if ($proc) {
        Write-Host "Jarayon: $($proc.ProcessName), ishga tushgan: $($proc.StartTime)"
    }
} else {
    Write-Host "Port 8080 da hech kim yo'q"
}

Write-Host ""
Write-Host "=== /ping endpoint test ===" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8080/ping" -UseBasicParsing -TimeoutSec 3
    Write-Host "Status: $($r.StatusCode)"
    Write-Host "Body: $($r.Content)"
} catch {
    Write-Host "XATO: $_"
}
