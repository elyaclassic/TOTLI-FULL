@echo off
chcp 65001 >nul
title TOTLI HOLVA — Serverni to'xtatish

set PORT=8080
cd /d "%~dp0"

echo.
echo ========================================
echo   TOTLI HOLVA — Serverni to'xtatish
echo ========================================
echo.
echo Port %PORT% tekshirilmoqda...
echo.

:: 1) PowerShell: 8080 portni band qilgan jarayonni to'xtatish
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-NetTCPConnection -LocalPort %PORT% -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }; if ($c) { $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }"
timeout /t 2 /nobreak >nul

:: 2) netstat dan PID olish va taskkill /F /PID
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo PID %%a to'xtatilmoqda...
    taskkill /F /PID %%a 2>nul
    timeout /t 1 /nobreak >nul
)
timeout /t 1 /nobreak >nul

:: 3) Asosiy ishlaydigan usul: python.exe ni to'xtatish (port odatda shunda bo'shaydi)
netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo python.exe to'xtatilmoqda...
    taskkill /F /IM python.exe 2>nul
    if errorlevel 1 (
        echo [!] Ruxsat yetishmadi. stop_server.bat ni o'ng tugma - "Administrator sifatida ishga tushirish" bilan ochib qayta urinib ko'ring.
    ) else (
        echo [OK] python.exe to'xtatildi.
    )
    timeout /t 2 /nobreak >nul
)

:: Natija
echo.
netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [OK] Server to'xtatildi. Port %PORT% bo'sh.
) else (
    echo [X] Server to'xtatilmadi. Port %PORT% hali band.
    echo.
    echo Quyidagilardan birini qiling:
    echo   1. stop_server.bat ustida o'ng tugma - "Administrator sifatida ishga tushirish"
    echo   2. CMD yoki PowerShell ni Administrator sifatida oching, keyin: taskkill /F /IM python.exe
    echo   3. Task Manager ^(Ctrl+Shift+Esc^) - python.exe - End task
    echo.
)

echo.
pause
