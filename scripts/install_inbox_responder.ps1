# TOTLI Inbox Responder Task Scheduler installer
# Ishlatish (admin):  & "D:\TOTLI BI\scripts\install_inbox_responder.ps1"
#
# Task Administrator hisobida ishlaydi (claude.cmd shu profilda mavjud,
# uvicorn bot ham shu user'da ishlayapti).

$ErrorActionPreference = "Stop"
$taskName = "TOTLI Inbox Responder"
$runner = "D:\TOTLI BI\scripts\_inbox_responder_runner.ps1"

Write-Host "[1/4] PS runner script yaratilmoqda..." -ForegroundColor Cyan
$runnerContent = @'
# TOTLI Inbox Responder runner — har 1 daqiqada Task Scheduler chaqiradi
$ErrorActionPreference = "Continue"
$root = "D:\TOTLI BI"
Set-Location $root

$candidates = @(
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python314\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Users\Администратор\AppData\Local\Programs\Python\Python311\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Python313\python.exe",
    "C:\Python312\python.exe"
)
$python = $null
foreach ($p in $candidates) { if (Test-Path $p) { $python = $p; break } }
if (-not $python) {
    Add-Content -Path "$root\watchdog.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [responder] ERROR: Python topilmadi"
    exit 1
}

& $python "$root\scripts\claude_inbox_responder.py" 2>&1 | ForEach-Object {
    if ($_) { Add-Content -Path "$root\watchdog.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [responder-out] $_" }
}
exit $LASTEXITCODE
'@
Set-Content -Path $runner -Value $runnerContent -Encoding UTF8 -Force

Write-Host "[2/4] Eski task o'chirilmoqda..." -ForegroundColor Cyan
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "[3/4] Yangi task yaratilmoqda..." -ForegroundColor Cyan
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddSeconds(30) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
# Administrator hisobida (claude.cmd shu yerda)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -RunLevel Limited `
    -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -AllowStartIfOnBatteries
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Yordamchim bot xabarlariga avtomatik javob (har 1 daq)" | Out-Null
} catch {
    Write-Host "[!] ServiceAccount muvaffaqiyatsiz, Interactive bilan urinaman..." -ForegroundColor Yellow
    $principal = New-ScheduledTaskPrincipal `
        -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -RunLevel Limited `
        -LogonType InteractiveOrPassword
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Yordamchim bot xabarlariga avtomatik javob (har 1 daq)" | Out-Null
}

Write-Host "[4/4] Birinchi sinov..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 60

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  [OK] Task: $taskName" -ForegroundColor Green
Write-Host "  Har 1 daqiqada avtomatik" -ForegroundColor Green
Write-Host "  Log: D:\TOTLI BI\watchdog.log" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Oxirgi log
$logPath = "D:\TOTLI BI\watchdog.log"
if (Test-Path $logPath) {
    Write-Host "Oxirgi 5 ta [responder] log qatori:" -ForegroundColor Yellow
    Get-Content $logPath -Tail 30 | Select-String "responder" | Select-Object -Last 5
}
