# TOTLI Integrity Check installer (PowerShell native cmdlet)
# Ishlatish (admin):  & "D:\TOTLI BI\scripts\install_integrity.ps1"

$ErrorActionPreference = "Stop"
$taskName = "TOTLI Integrity Check"
$runner = "D:\TOTLI BI\scripts\_integrity_runner.ps1"

if (-not (Test-Path $runner)) {
    Write-Host "[X] Runner topilmadi: $runner" -ForegroundColor Red
    exit 1
}

Write-Host "[1/3] Eski task o'chirilmoqda (agar bor bo'lsa)..." -ForegroundColor Cyan
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "[2/3] Yangi task yaratilmoqda..." -ForegroundColor Cyan
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" -RunLevel Highest -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "TOTLI BI DB invariantlarini har soatda tekshiradi" | Out-Null

Write-Host "[3/3] Birinchi sinov ishga tushirilmoqda..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 6

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  [OK] Task o'rnatildi: $taskName" -ForegroundColor Green
Write-Host "  Har 1 soatda avtomatik ishlaydi" -ForegroundColor Green
Write-Host "  Log: D:\TOTLI BI\integrity_check.log" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Oxirgi log qatorlari
$logPath = "D:\TOTLI BI\integrity_check.log"
if (Test-Path $logPath) {
    Write-Host "Oxirgi log qatorlari:" -ForegroundColor Yellow
    Get-Content $logPath -Tail 5
}
