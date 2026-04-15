@echo off
setlocal enabledelayedexpansion
title Telegram Sheets Bot

set "WORK_DIR=%~dp0"
if "%WORK_DIR:~-1%"=="\" set "WORK_DIR=%WORK_DIR:~0,-1%"
set "LOG_FILE=%WORK_DIR%\bot.log"
set "ENV_FILE=%WORK_DIR%\.env"
set "RUNNER_FILE=%WORK_DIR%\_bot_runner.bat"
set "LOCK_PORT=47891"

cd /d "%WORK_DIR%"

echo ========================================
echo   Telegram Sheets Bot
echo ========================================
echo.

if not exist "%ENV_FILE%" (
    echo [X] .env fayl topilmadi: %ENV_FILE%
    echo     Avval env.example dan .env yarating.
    echo.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$p='%ENV_FILE%'; $port='47891'; if (Test-Path $p) { $line = Get-Content $p ^| Where-Object { $_ -match '^BOT_LOCK_PORT=' } ^| Select-Object -First 1; if ($line) { $value = ($line -split '=', 2)[1].Trim(); if ($value) { $port = $value } } }; Write-Output $port"`) do (
    set "LOCK_PORT=%%a"
)

set "PYTHON="
if exist "%WORK_DIR%\.venv\Scripts\python.exe" set "PYTHON=%WORK_DIR%\.venv\Scripts\python.exe"
if not "%PYTHON%"=="" goto :python_found

where python >nul 2>&1 && set "PYTHON=python"
if not "%PYTHON%"=="" goto :python_found

where py >nul 2>&1 && set "PYTHON=py -3"
if not "%PYTHON%"=="" goto :python_found

:python_found
if "%PYTHON%"=="" (
    echo [X] Python topilmadi.
    echo.
    pause
    exit /b 1
)

echo %PYTHON% | findstr "\\" >nul && set "PYTHON_CMD="%PYTHON%"" || set "PYTHON_CMD=%PYTHON%"

echo [OK] Python topildi
echo [1/3] Kutubxonalar tekshirilmoqda...
%PYTHON_CMD% -m pip install -r requirements.txt -q
if errorlevel 1 %PYTHON_CMD% -m pip install -r requirements.txt

echo [2/3] Bot sozlamalari tekshirildi.

set "BOT_RUNNING=0"
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%LOCK_PORT% " ^| findstr "LISTENING"') do (
    set "BOT_RUNNING=1"
    goto :status_done
)
:status_done

if "%BOT_RUNNING%"=="1" goto :bot_running

echo [3/3] Bot orqa fonda ishga tushirilmoqda...
call :start_bot
timeout /t 3 /nobreak >nul

set "STARTED=0"
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%LOCK_PORT% " ^| findstr "LISTENING"') do (
    set "STARTED=1"
    goto :start_check_done
)
:start_check_done

if "%STARTED%"=="1" (
    echo.
    echo ========================================
    echo   [OK] Bot ishga tushdi
    echo   Lock port: %LOCK_PORT%
    echo   Loglar:    %LOG_FILE%
    echo ========================================
    echo.
    pause
    exit /b 0
)

echo.
echo [X] Bot ishga tushmadi. Logni tekshiring:
echo     %LOG_FILE%
echo.
pause
exit /b 1

:bot_running
echo.
echo ========================================
echo   [!] Bot allaqachon ishlayapti
echo       Lock port: %LOCK_PORT%
echo ========================================
echo.
echo   [Q] Qayta ishga tushirish
echo   [T] To'xtatish
echo   [L] Loglarni ko'rish
echo   [D] Davom etish
echo.
choice /C QTLD /M "Tanlang"
if errorlevel 4 goto :do_nothing
if errorlevel 3 goto :do_logs
if errorlevel 2 goto :do_stop
if errorlevel 1 goto :do_restart

:do_restart
echo.
echo Bot qayta ishga tushirilmoqda...
call :kill_bot
timeout /t 2 /nobreak >nul
call :start_bot
timeout /t 3 /nobreak >nul
echo [OK] Bot qayta ishga tushdi.
echo     Loglar: %LOG_FILE%
echo.
pause
exit /b 0

:do_stop
echo.
echo Bot to'xtatilmoqda...
call :kill_bot
echo [OK] Bot to'xtatildi.
echo.
pause
exit /b 0

:do_logs
echo.
echo ========================================
echo   Bot loglari
echo   Chiqish uchun: Ctrl+C
echo ========================================
echo.
if not exist "%LOG_FILE%" (
    echo [!] Log fayl topilmadi: %LOG_FILE%
    echo.
    pause
    exit /b 0
)
powershell -NoProfile -Command "Get-Content '%LOG_FILE%' -Tail 50 -Wait"
exit /b 0

:do_nothing
echo Bot ishlashda davom etadi.
timeout /t 2 /nobreak >nul
exit /b 0

:start_bot
> "%RUNNER_FILE%" (
    echo @echo off
    echo cd /d "%WORK_DIR%"
    echo %PYTHON_CMD% -m src.main ^> "%LOG_FILE%" 2^>^&1
)
> "%TEMP%\totli_start_bot.vbs" (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run """%RUNNER_FILE%""", 0, False
)
cscript //nologo "%TEMP%\totli_start_bot.vbs"
del "%TEMP%\totli_start_bot.vbs" 2>nul
goto :eof

:kill_bot
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%LOCK_PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%telegram_sheets_bot%%src.main%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto :eof
