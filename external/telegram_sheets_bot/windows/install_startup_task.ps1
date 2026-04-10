# Run once as Administrator if possible.
# Starts the bot automatically when the user logs in.

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
# Run both at Windows startup and when the current user logs in.
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($startupTrigger, $logonTrigger) -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Done: task '$TaskName' will start the bot at Windows startup and user logon."
Write-Host "Check in Task Scheduler: $TaskName"
