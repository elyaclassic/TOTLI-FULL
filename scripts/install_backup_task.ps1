# Windows Task Scheduler — TOTLI BI jonli backup har 5 daqiqada
# Foydalanish: Admin PowerShell da ishga tushiring:
#   powershell -ExecutionPolicy Bypass -File "D:\TOTLI BI\scripts\install_backup_task.ps1"

$ErrorActionPreference = 'Stop'

$TaskName = "TOTLI_BI_Live_Backup"
$BatPath  = "D:\TOTLI BI\scripts\backup_live_run.bat"
$WorkDir  = "D:\TOTLI BI"

Write-Host "=== TOTLI BI Live Backup — Task Scheduler o'rnatish ==="
Write-Host ""

if (-not (Test-Path $BatPath)) {
    Write-Host "XATO: $BatPath topilmadi" -ForegroundColor Red
    exit 1
}

# Eski task bor bo'lsa o'chirish
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Eski task topildi, o'chirilmoqda..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action — .bat chaqiradi
$action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $WorkDir

# Trigger — har 5 daqiqada, cheksiz
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)

# Settings — 2 daqiqadan oshsa to'xtatish, parallel ishlamasin, restart da tiklansin
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Principal — SYSTEM nomidan (user logout bo'lsa ham ishlaydi)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "TOTLI BI SQLite jonli backup (har 5 daqiqada, 2 soatlik retention)"

Write-Host ""
Write-Host "✓ Task muvaffaqiyatli ro'yxatga olindi: $TaskName" -ForegroundColor Green
Write-Host ""
Write-Host "Birinchi ishga tushirish..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ""
Write-Host "Holat:"
Write-Host "  LastRunTime:   $($info.LastRunTime)"
Write-Host "  LastTaskResult: $($info.LastTaskResult)  (0 = muvaffaqiyatli)"
Write-Host "  NextRunTime:   $($info.NextRunTime)"
Write-Host ""
Write-Host "Backup fayllar: D:\TOTLI_BI_BACKUPS\live\"
Write-Host "Log fayli:      D:\TOTLI_BI_BACKUPS\backup_live.log"
Write-Host ""
Write-Host "Task ni ko'rish: taskschd.msc (Task Scheduler Library)"
Write-Host "Task ni o'chirish: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
