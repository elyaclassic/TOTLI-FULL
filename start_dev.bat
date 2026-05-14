@echo off
setlocal enabledelayedexpansion
title TOTLI HOLVA DEV (Sandbox)

:: ========== DEV ENVIRONMENT ==========
:: Sandbox: totli_holva_dev.db, port 8081
:: Prod tizimga TEGMAYDI — bemalol sinab ko'rish mumkin

set BIND_HOST=0.0.0.0
set DISPLAY_HOST=127.0.0.1
set PORT=8081
set TOTLI_DB_FILE=totli_holva_dev.db
set TOTLI_ENV=dev

:: Telegram bot tokenni o'chirish — dev'da Telegram xabar yubormasin
set CLAUDE_BOT_TOKEN=
set TELEGRAM_BOT_TOKEN=

set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%
set PID_FILE=%WORK_DIR%\server_dev.pid
set LOG_FILE=%WORK_DIR%\server_dev.log

cd /d "%~dp0"

echo ========================================
echo   TOTLI HOLVA DEV Sandbox
echo ========================================
echo   DB:   %TOTLI_DB_FILE%
echo   Port: %PORT%
echo   URL:  http://%DISPLAY_HOST%:%PORT%
echo ========================================
echo.

:: Python qidirish (start.bat dan nusxa)
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if not "%PYTHON%"=="" goto :found
where py >nul 2>&1 && set PYTHON=py -3
if not "%PYTHON%"=="" goto :found
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe
if not "%PYTHON%"=="" goto :found
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe
:found
if "%PYTHON%"=="" (
    echo [X] Python topilmadi
    pause
    exit /b 1
)
echo %PYTHON% | findstr "\\" >nul && set PYTHON_CMD="%PYTHON%" || set PYTHON_CMD=%PYTHON%

:: Dev DB mavjudligini tekshirish
if not exist "%WORK_DIR%\%TOTLI_DB_FILE%" (
    echo [!] %TOTLI_DB_FILE% topilmadi
    echo     Nusxa olish: copy totli_holva.db %TOTLI_DB_FILE%
    pause
    exit /b 1
)

:: Port bandmi tekshirish
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo [!] Port %PORT% allaqachon band - dev server ishlayapti
    echo     URL: http://%DISPLAY_HOST%:%PORT%
    pause
    exit /b 0
)

echo Server ishga tushirilmoqda...
echo Log: %LOG_FILE%
echo.

:: Foreground rejim (Ctrl+C bilan to'xtatish)
%PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --workers 1

pause
