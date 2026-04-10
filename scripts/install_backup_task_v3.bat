@echo off
REM TOTLI BI jonli backup — Task Scheduler o'rnatuvchi (v3)
REM Current user nomidan ishga tushadi (foydalanuvchi PATH + Python topiladi).
REM Admin Command Prompt yoki Admin cmd dan ishga tushiring.

echo.
echo === TOTLI BI Live Backup — Task Scheduler (v3, user context) ===
echo.
echo Joriy foydalanuvchi:
whoami
echo.

REM Eski task bor bo'lsa o'chirish
schtasks /query /tn "TOTLI_BI_Live_Backup" >nul 2>&1
if %errorlevel% == 0 (
    echo Eski task topildi, o'chirilmoqda...
    schtasks /delete /tn "TOTLI_BI_Live_Backup" /f
    echo.
)

echo Yangi task ro'yxatga olinmoqda (joriy user nomidan, interaktiv rejimda)...
echo.

REM /IT = interactive-only (user logged in bo'lganda ishlaydi, parol kerak emas)
REM /RL HIGHEST = yuqori huquqlar (admin)
REM User nomi %USERDOMAIN%\%USERNAME% orqali olinadi
schtasks /create ^
  /tn "TOTLI_BI_Live_Backup" ^
  /tr "\"D:\TOTLI BI\scripts\backup_live_run.bat\"" ^
  /sc minute ^
  /mo 5 ^
  /ru "%USERDOMAIN%\%USERNAME%" ^
  /it ^
  /rl HIGHEST ^
  /f

if %errorlevel% neq 0 (
    echo.
    echo XATO: task yaratib bo'lmadi.
    pause
    exit /b 1
)

echo.
echo Birinchi ishga tushirish...
schtasks /run /tn "TOTLI_BI_Live_Backup"

timeout /t 8 /nobreak >nul

echo.
echo === Task holati ===
schtasks /query /tn "TOTLI_BI_Live_Backup" /fo LIST

echo.
echo === Log oxiri ===
if exist "D:\TOTLI_BI_BACKUPS\backup_live.log" (
    powershell -Command "Get-Content 'D:\TOTLI_BI_BACKUPS\backup_live.log' -Tail 5"
) else (
    echo Log fayl hali yo'q.
)

echo.
echo ✓ Tugadi!
echo.
echo Backup fayllar: D:\TOTLI_BI_BACKUPS\live\
echo Log fayli:      D:\TOTLI_BI_BACKUPS\backup_live.log
echo.
echo Task ni ko'rish:   taskschd.msc
echo Task ni o'chirish: schtasks /delete /tn "TOTLI_BI_Live_Backup" /f
echo.
pause
