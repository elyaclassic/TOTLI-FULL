@echo off
chcp 65001 >nul
title TOTLI HOLVA - Tezkor restart
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PORT=8080
set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%
set LOG_FILE=%WORK_DIR%\server.log

echo.
echo ========================================
echo   TOTLI HOLVA - Tezkor restart
echo ========================================
echo.

REM ====== 1) Eski server (uvicorn main:app) ni o'chirish ======
echo [1/4] Eski server o'chirilmoqda...
set KILLED=0

REM Port 8080 ni tinglayotgan PID
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a /T >nul 2>&1
    set KILLED=1
)

REM PID fayldan
if exist "%WORK_DIR%\server.pid" (
    set /p SAVED_PID=<"%WORK_DIR%\server.pid"
    if not "!SAVED_PID!"=="" (
        taskkill /F /PID !SAVED_PID! /T >nul 2>&1
        set KILLED=1
    )
    del "%WORK_DIR%\server.pid" 2>nul
)

REM WMIC orqali uvicorn main:app ishlatayotgan python.exe (botlar tegmaydi)
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%uvicorn%%main:app%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do (
    taskkill /F /PID %%a /T >nul 2>&1
    set KILLED=1
)

if "!KILLED!"=="0" (
    echo     [!] Server allaqachon o'chiq edi
) else (
    echo     [OK] Server o'chirildi
)

REM ====== 2) Port bo'shashi kutish ======
echo [2/4] Port bo'shashi kutilmoqda (2 sek)...
timeout /t 2 /nobreak >nul

REM ====== 3) Port tekshirish ======
echo [3/4] Port tekshirilmoqda...
set PORT_BUSY=0
netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 set PORT_BUSY=1

if "!PORT_BUSY!"=="1" (
    echo     [!] Port hali band - yana 3 sek kutamiz...
    timeout /t 3 /nobreak >nul
    netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
    if not errorlevel 1 (
        echo     [X] Port hali band! start.bat ichidagi menu bilan to'xtating
        echo.
        pause
        exit /b 1
    )
)
echo     [OK] Port bo'sh

REM ====== 4) Yangi server ishga tushirish ======
echo [4/4] Yangi server ishga tushirilmoqda...
echo.

REM start.bat ni chaqiramiz - menyusiz darhol ishga tushadi (server o'chiq edi).
REM Botlar (Telegram + Senior/Expert) avtomatik tekshiriladi va kerak bo'lsa qayta yoqiladi.
call "%WORK_DIR%\start.bat"

REM start.bat ichida pause bor - foydalanuvchi ko'radi va Enter bosib yopadi.
REM Bu skript shu erda tugaydi.
endlocal
exit /b 0
