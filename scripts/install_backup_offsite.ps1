# TOTLI Off-site Backup Task Scheduler installer
# Ishlatish (admin):  & "D:\TOTLI BI\scripts\install_backup_offsite.ps1"

$ErrorActionPreference = "Stop"
$taskName = "TOTLI Offsite Backup"
$runner = "D:\TOTLI BI\scripts\_backup_offsite_runner.ps1"

Write-Host "[1/5] OFFSITE_BACKUP_PATH tekshiruvi..." -ForegroundColor Cyan
$envPath = "D:\TOTLI BI\.env"
$hasConfig = $false
if (Test-Path $envPath) {
    $hasConfig = (Get-Content $envPath -Raw) -match "OFFSITE_BACKUP_PATH\s*="
}
if (-not $hasConfig) {
    Write-Host "[!] DIQQAT: .env da OFFSITE_BACKUP_PATH topilmadi." -ForegroundColor Yellow
    Write-Host "    Task yaratiladi, lekin avval .env ga path qo'shing:" -ForegroundColor Yellow
    Write-Host "    OFFSITE_BACKUP_PATH=\\OFFICE-PC2\backups\totli   (SMB share)" -ForegroundColor Yellow
    Write-Host "    yoki: E:\totli_offsite                            (USB/External HDD)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "[2/5] Runner script yaratilmoqda..." -ForegroundColor Cyan
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
    Add-Content -Path "$root\backup_offsite.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  ERROR: Python topilmadi"
    exit 1
}

# backup_offsite.py O'ZI backup_offsite.log ga yozadi (log() funksiyasi faylga + print).
# stdout'ni QAYTA log'ga yozmaymiz — aks holda har qator 2 marta yozilardi (dublikat fix 2026-06-29).
& $python "$root\scripts\backup_offsite.py"
exit $LASTEXITCODE
'@
Set-Content -Path $runner -Value $runnerContent -Encoding UTF8 -Force

Write-Host "[3/5] Eski task o'chirilmoqda..." -ForegroundColor Cyan
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "[4/5] Yangi task yaratilmoqda (har soatda)..." -ForegroundColor Cyan
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -RunLevel Highest `
    -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Off-site backup — eng yangi DB.gz ni masofaga nusxalaydi (har 1 soat)" | Out-Null

Write-Host "[5/5] Birinchi sinov..." -ForegroundColor Cyan
if ($hasConfig) {
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 10
    $logPath = "D:\TOTLI BI\backup_offsite.log"
    if (Test-Path $logPath) {
        Write-Host "Log:" -ForegroundColor Yellow
        Get-Content $logPath -Tail 5
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  [OK] Task: $taskName" -ForegroundColor Green
Write-Host "  Har 1 soatda avtomatik" -ForegroundColor Green
Write-Host "  Log: D:\TOTLI BI\backup_offsite.log" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
if (-not $hasConfig) {
    Write-Host ""
    Write-Host "[!] OFFSITE_BACKUP_PATH ni .env ga qo'shing!" -ForegroundColor Yellow
    Write-Host "    Misol: OFFSITE_BACKUP_PATH=E:\totli_offsite" -ForegroundColor Yellow
}
