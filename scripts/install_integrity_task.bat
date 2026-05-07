@echo off
chcp 65001 >nul
REM TOTLI Integrity Check — Task Scheduler installer (PowerShell version)
REM 1 marta double-click qiling, UAC ruxsat bering, tugadi

setlocal

REM Admin tekshiruv — agar admin emas bo'lsa, qayta ishga tushir
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Administrator ruxsat kerak. UAC dialog ochilmoqda...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ========================================
echo   TOTLI Integrity Check Installer (PS)
echo ========================================
echo.

set TASK_NAME=TOTLI Integrity Check
set RUNNER_PS=D:\TOTLI BI\scripts\_integrity_runner.ps1

REM Eski task bo'lsa o'chirish (idempotent)
schtasks /Query /TN "%TASK_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [1/3] Eski task o'chirilmoqda...
    schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1
)

REM Yangi task — har soatda PowerShell ishga tushiradi (Unicode-safe)
echo [2/3] Yangi task yaratilmoqda (PS .ps1 runner)...
schtasks /Create ^
    /TN "%TASK_NAME%" ^
    /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%RUNNER_PS%\"" ^
    /SC HOURLY ^
    /MO 1 ^
    /RU "SYSTEM" ^
    /RL HIGHEST ^
    /F

if %errorlevel% neq 0 (
    echo.
    echo [X] Task yaratilmadi! Yuqoridagi xatoni o'qing.
    pause
    exit /b 1
)

REM Birinchi marta darhol ishga tushirish (sinov)
echo [3/3] Birinchi sinov ishga tushirilmoqda...
schtasks /Run /TN "%TASK_NAME%" >nul 2>&1
timeout /t 5 /nobreak >nul

echo.
echo ========================================
echo   [OK] Task qayta o'rnatildi (PS runner)
echo   Har 1 soatda avtomatik ishlaydi
echo   Log: D:\TOTLI BI\integrity_check.log
echo ========================================
echo.
echo Telegram'da Yordamchim botdan xabar kelishi kerak.
echo.
pause
