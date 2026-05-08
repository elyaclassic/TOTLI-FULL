# TOTLI Hikvision Monitor Task Scheduler installer (O11 audit fix)
# Ishlatish (admin):  & "D:\TOTLI BI\scripts\install_hikvision_monitor.ps1"

$ErrorActionPreference = "Stop"
$taskName = "TOTLI Hikvision Monitor"
$runner = "D:\TOTLI BI\scripts\_hikvision_monitor_runner.ps1"

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
    Add-Content -Path "$root\hikvision_monitor.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  ERROR: Python topilmadi"
    exit 1
}

& $python "$root\scripts\hikvision_monitor.py" 2>&1 | ForEach-Object {
    if ($_) { Add-Content -Path "$root\hikvision_monitor.log" -Value $_ }
}
exit $LASTEXITCODE
'@
Set-Content -Path $runner -Value $runnerContent -Encoding UTF8 -Force

Write-Host "[2/4] Eski task o'chirilmoqda..." -ForegroundColor Cyan
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "[3/4] Yangi task — har 10 daqiqada..." -ForegroundColor Cyan
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -RunLevel Highest `
    -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -AllowStartIfOnBatteries
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Hikvision health monitor — har 10 daq, 20 daq DOWN bo'lsa Telegram alert" | Out-Null

Write-Host "[4/4] Birinchi sinov..." -ForegroundColor Cyan
$python = $null
$candidates = @(
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python314\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python312\python.exe"
)
foreach ($p in $candidates) { if (Test-Path $p) { $python = $p; break } }
if ($python) {
    Write-Host ""
    & $python "D:\TOTLI BI\scripts\hikvision_monitor.py"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  [OK] Task: $taskName" -ForegroundColor Green
Write-Host "  Har 10 daq avtomat tekshiradi" -ForegroundColor Green
Write-Host "  20+ daq DOWN bo'lsa Telegram alert" -ForegroundColor Green
Write-Host "  Log: D:\TOTLI BI\hikvision_monitor.log" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Manual test:" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Yellow
