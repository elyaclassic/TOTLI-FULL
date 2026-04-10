@echo off
REM TOTLI BI jonli backup — Windows Task Scheduler o'rnatuvchi (v2, schtasks.exe)
REM Admin Command Prompt yoki Admin PowerShell dan ishga tushiring:
REM   "D:\TOTLI BI\scripts\install_backup_task_v2.bat"

echo.
echo === TOTLI BI Live Backup — Task Scheduler (v2) ===
echo.

REM Eski task bor bo'lsa o'chirish
schtasks /query /tn "TOTLI_BI_Live_Backup" >nul 2>&1
if %errorlevel% == 0 (
    echo Eski task topildi, o'chirilmoqda...
    schtasks /delete /tn "TOTLI_BI_Live_Backup" /f
)

echo.
echo Yangi task ro'yxatga olinmoqda...
echo.

schtasks /create ^
  /tn "TOTLI_BI_Live_Backup" ^
  /tr "\"D:\TOTLI BI\scripts\backup_live_run.bat\"" ^
  /sc minute ^
  /mo 5 ^
  /ru "SYSTEM" ^
  /rl HIGHEST ^
  /f

if %errorlevel% neq 0 (
    echo.
    echo XATO: task yaratib bo'lmadi. Admin sifatida ishga tushirdingizmi?
    pause
    exit /b 1
)

echo.
echo Birinchi ishga tushirish...
schtasks /run /tn "TOTLI_BI_Live_Backup"

timeout /t 5 /nobreak >nul

echo.
echo === Task holati ===
schtasks /query /tn "TOTLI_BI_Live_Backup" /v /fo LIST | findstr /i "TaskName Status Last Next Result"

echo.
echo.
echo ✓ O'rnatildi!
echo.
echo Backup fayllar: D:\TOTLI_BI_BACKUPS\live\
echo Log fayli:      D:\TOTLI_BI_BACKUPS\backup_live.log
echo.
echo Task ni ko'rish:  taskschd.msc
echo Task ni o'chirish: schtasks /delete /tn "TOTLI_BI_Live_Backup" /f
echo.
pause
