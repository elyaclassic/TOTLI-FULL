# TOTLI BI Watchdog
# Har 2 daqiqada Task Scheduler chaqiradi.
# Tekshiradi: uvicorn server (port 8080) va telegram_sheets_bot (Python jarayoni).
# Yoq bolsa qayta ishga tushiradi va Yordamchim botga xabar yuboradi.

$ErrorActionPreference = "SilentlyContinue"
$ROOT = "D:\TOTLI BI"
$LOG = "$ROOT\watchdog.log"
$SERVER_RUNNER = "$ROOT\_server_runner.bat"
$BOT_RUNNER = "$ROOT\external\telegram_sheets_bot\_bot_runner.bat"
$ENV_FILE = "$ROOT\.env"

function Write-WLog($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $LOG -Value $line -Encoding UTF8
}

function Get-ClaudeBotToken {
    if (-not (Test-Path $ENV_FILE)) { return "" }
    foreach ($l in (Get-Content $ENV_FILE)) {
        if ($l -match '^CLAUDE_BOT_TOKEN=(.+)$') {
            return $matches[1].Trim().Trim("'").Trim('"')
        }
    }
    return ""
}

function Send-Notify($text) {
    $tk = Get-ClaudeBotToken
    if (-not $tk) { return }
    try {
        $body = @{ chat_id = "1340383182"; text = "[Watchdog] $text" }
        Invoke-RestMethod "https://api.telegram.org/bot$tk/sendMessage" -Method POST -Body $body -TimeoutSec 10 | Out-Null
    } catch {}
}

function Start-Hidden($batPath, $label) {
    if (-not (Test-Path $batPath)) {
        Write-WLog "[$label] runner not found: $batPath"
        return $false
    }
    $vbs = "$env:TEMP\watchdog_$($label)_$(Get-Random).vbs"
    $vbsContent = "Set WshShell = CreateObject(`"WScript.Shell`")`r`nWshShell.Run `"`"`"$batPath`"`"`", 0, False"
    Set-Content -Path $vbs -Value $vbsContent -Encoding ASCII
    cscript //nologo $vbs | Out-Null
    Remove-Item $vbs -Force -ErrorAction SilentlyContinue
    return $true
}

# Heartbeat (har 30 daqiqada bitta yozuv)
$last = Get-Item $LOG -ErrorAction SilentlyContinue
if (-not $last -or ((Get-Date) - $last.LastWriteTime).TotalMinutes -ge 30) {
    Write-WLog "heartbeat -- watchdog alive"
}

# 1. Server (uvicorn) tekshirish
$server_ok = $false
try {
    $r = Invoke-WebRequest "http://10.243.165.156:8080/login" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) { $server_ok = $true }
} catch {}

if (-not $server_ok) {
    Write-WLog "SERVER OFF -- restarting"
    if (Start-Hidden $SERVER_RUNNER "server") {
        Start-Sleep -Seconds 15
        try {
            $r = Invoke-WebRequest "http://10.243.165.156:8080/login" -TimeoutSec 5 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                Write-WLog "SERVER UP after restart"
                Send-Notify "Server (uvicorn) ochib qolgan edi - qayta ishga tushirildi (HTTP 200)"
            } else {
                Write-WLog "SERVER not up yet (status=$($r.StatusCode))"
                Send-Notify "Server qayta ishga tushirilmadi! Qolda tekshiring."
            }
        } catch {
            Write-WLog "SERVER restart failed: $_"
            Send-Notify "Server qayta ishga tushirilmadi! Xato: $_"
        }
    }
}

# 2. telegram_sheets_bot tekshirish
$bot_ok = $false
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -match 'telegram_sheets_bot|src\.main' }
    if ($procs) { $bot_ok = $true }
} catch {}

if (-not $bot_ok) {
    Write-WLog "BOT (telegram_sheets) OFF -- restarting"
    if (Start-Hidden $BOT_RUNNER "bot") {
        Start-Sleep -Seconds 10
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'telegram_sheets_bot|src\.main' }
        if ($procs) {
            Write-WLog "BOT UP after restart"
            Send-Notify "Telegram Sheets Bot ochib qolgan edi - qayta ishga tushirildi"
        } else {
            Write-WLog "BOT restart failed"
            Send-Notify "Telegram Sheets Bot qayta ishga tushirilmadi! Qolda tekshiring."
        }
    }
}

# 3. Log rotation (1 MB)
if (Test-Path $LOG) {
    $size = (Get-Item $LOG).Length
    if ($size -gt 1048576) {
        Move-Item $LOG "$LOG.old" -Force
        Write-WLog "Log rotated"
    }
}
