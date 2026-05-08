# TOTLI Stale Cleanup Task Scheduler installer
# Ishlatish (admin):  & "D:\TOTLI BI\scripts\install_stale_cleanup.ps1"

$ErrorActionPreference = "Stop"
$taskName = "TOTLI Stale Cleanup"
$runner = "D:\TOTLI BI\scripts\_stale_cleanup_runner.ps1"

Write-Host "[1/4] Runner script yaratilmoqda..." -ForegroundColor Cyan
$runnerContent = @'
$ErrorActionPreference = "Continue"
$root = "D:\TOTLI BI"
Set-Location $root

$candidates = @(
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python314\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe"
)
$python = $null
foreach ($p in $candidates) { if (Test-Path $p) { $python = $p; break } }
if (-not $python) {
    Add-Content -Path "$root\stale_cleanup.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  ERROR: Python topilmadi"
    exit 1
}

& $python "$root\scripts\cleanup_stale_drafts.py" 2>&1 | ForEach-Object {
    if ($_) { Add-Content -Path "$root\stale_cleanup.log" -Value $_ }
}
exit $LASTEXITCODE
'@
Set-Content -Path $runner -Value $runnerContent -Encoding UTF8 -Force

Write-Host "[2/4] Eski task o'chirilmoqda..." -ForegroundColor Cyan
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "[3/4] Yangi task — har kuni 04:00..." -ForegroundColor Cyan
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At "04:00"
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -RunLevel Highest `
    -LogonType ServiceAccount
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
    -Description "Stale draftlarni tozalash — har kuni 04:00 (>7 kun -> cancelled)" | Out-Null

Write-Host "[4/4] Birinchi sinov (DRY-RUN)..." -ForegroundColor Cyan
$python = $null
$candidates = @(
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python314\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python312\python.exe"
)
foreach ($p in $candidates) { if (Test-Path $p) { $python = $p; break } }
if ($python) {
    Write-Host ""
    & $python "D:\TOTLI BI\scripts\cleanup_stale_drafts.py" --dry-run
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  [OK] Task: $taskName" -ForegroundColor Green
Write-Host "  Har kuni 04:00 da avtomat" -ForegroundColor Green
Write-Host "  Log: D:\TOTLI BI\stale_cleanup.log" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Hozir DRY-RUN bajarildi (yuqorida) — qancha draft tozalanardi ko'rsatildi." -ForegroundColor Yellow
Write-Host "Real ishga tushirish uchun ertaga 04:00 da avtomat ishlaydi yoki:" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
