# Bir marta Administrator sifatida ishga tushiring (o'ng tugma -> Run with PowerShell).
# Kompyuter qayta yuklanganda bot avtomatik ishga tushadi (foydalanuvchi kirganda).

$ErrorActionPreference = "Stop"
$BotRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $BotRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Xato: $PythonExe topilmadi. Avval venv yarating: python -m venv .venv"
    exit 1
}

$TaskName = "TelegramHisobotBot_RD"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m src.main" -WorkingDirectory $BotRoot
# Foydalanuvchi Windows ga kirganda
# Hozirgi foydalanuvchi tizimga kirganda
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Tayyor: vazifa '$TaskName' — har safar tizimga kirganda bot ishga tushadi."
Write-Host "Tekshirish: taskschd.msc -> $TaskName"
