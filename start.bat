@echo off
setlocal enabledelayedexpansion
title TOTLI HOLVA Business System

:: ========== IP VA PORT ==========
set BIND_HOST=10.243.165.156
set PORT=8080
:: ========== TELEGRAM BOT ==========
:: BotFather dan olingan token (@BotFather -> /newbot)
:: Token ni .env faylida yoki quyida kiriting:
if "%TELEGRAM_BOT_TOKEN%"=="" set TELEGRAM_BOT_TOKEN=
:: ==============================================

set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%
set PID_FILE=%WORK_DIR%\server.pid
set LOG_FILE=%WORK_DIR%\server.log

cd /d "%~dp0"

echo ========================================
echo   TOTLI HOLVA Biznes Tizimi
echo ========================================
echo.

:: Python qidirish
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if not "%PYTHON%"=="" goto :found
where py >nul 2>&1 && set PYTHON=py -3
if not "%PYTHON%"=="" goto :found
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe
if not "%PYTHON%"=="" goto :found
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe
if not "%PYTHON%"=="" goto :found
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe
if not "%PYTHON%"=="" goto :found
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set PYTHON=%LocalAppData%\Programs\Python\Python310\python.exe
if not "%PYTHON%"=="" goto :found
if exist "C:\Program Files\Python313\python.exe" set PYTHON=C:\Program Files\Python313\python.exe
if not "%PYTHON%"=="" goto :found
if exist "C:\Program Files\Python312\python.exe" set PYTHON=C:\Program Files\Python312\python.exe
if not "%PYTHON%"=="" goto :found
if exist "C:\Program Files\Python311\python.exe" set PYTHON=C:\Program Files\Python311\python.exe
if not "%PYTHON%"=="" goto :found
if exist "C:\Python313\python.exe" set PYTHON=C:\Python313\python.exe
if not "%PYTHON%"=="" goto :found
if exist "C:\Python312\python.exe" set PYTHON=C:\Python312\python.exe
:found
if "%PYTHON%"=="" (
    echo [X] Python topilmadi! O'rnating va "Add to PATH" belgilang.
    pause
    exit /b 1
)
echo %PYTHON% | findstr "\\" >nul && set PYTHON_CMD="%PYTHON%" || set PYTHON_CMD=%PYTHON%
echo [OK] Python topildi

:: Kutubxonalar
echo [1/3] Kutubxonalar tekshirilmoqda...
%PYTHON_CMD% -m pip install -r requirements.txt -q
if errorlevel 1 %PYTHON_CMD% -m pip install -r requirements.txt

echo [2/3] Ma'lumotlar bazasi tayyor.

:: Port bandmi tekshirish (server ishlayaptimi?)
set SERVER_RUNNING=0
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set SERVER_RUNNING=1
    goto :check_done
)
:check_done

if "%SERVER_RUNNING%"=="1" goto :server_running

:: ====== BIRINCHI MARTA: Server orqa fonda ishga tushirish ======
echo [3/3] Server orqa fonda ishga tushirilmoqda...
call :start_server
timeout /t 3 /nobreak >nul

:: Tekshirish — server ishga tushdimi?
set STARTED=0
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set STARTED=1
    goto :start_check_done
)
:start_check_done

if "%STARTED%"=="1" (
    echo.
    echo ========================================
    echo   [OK] Server ishga tushdi (orqa fonda)
    echo   Brauzer: http://%BIND_HOST%:%PORT%
    echo   Loglar:  %LOG_FILE%
    echo ========================================
    echo.
    pause
    exit /b 0
) else (
    echo.
    echo [X] Server ishga tushmadi! Loglarni tekshiring:
    echo     %LOG_FILE%
    echo.
    pause
    exit /b 1
)

:: ====== SERVER ISHLAYAPTI — TANLOV MENYU ======
:server_running
echo.
echo ========================================
echo   [!] Server allaqachon ishlayapti
echo       http://%BIND_HOST%:%PORT%
echo ========================================
echo.
echo   [Q] Qayta ishga tushirish
echo   [T] To'xtatish
echo   [L] Loglarni ko'rish (jonli)
echo   [D] Davom etish (hech narsa qilmaslik)
echo.
choice /C QTLD /M "Tanlang"
if errorlevel 4 goto :do_nothing
if errorlevel 3 goto :do_logs
if errorlevel 2 goto :do_stop
if errorlevel 1 goto :do_restart

:do_restart
echo.
echo Server qayta ishga tushirilmoqda...
call :kill_server
timeout /t 2 /nobreak >nul
echo Yangi server ishga tushirilmoqda...
call :start_server
timeout /t 3 /nobreak >nul
echo [OK] Server qayta ishga tushdi.
echo     Loglar: %LOG_FILE%
echo.
pause
exit /b 0

:do_stop
echo.
echo Server to'xtatilmoqda...
call :kill_server
echo [OK] Server to'xtatildi.
echo.
pause
exit /b 0

:do_logs
echo.
echo ========================================
echo   Server loglari (jonli ko'rish)
echo   Chiqish uchun: Ctrl+C
echo ========================================
echo.
if not exist "%LOG_FILE%" (
    echo [!] Log fayl topilmadi: %LOG_FILE%
    echo     Server hali log yozmagan bo'lishi mumkin.
    pause
    exit /b 0
)
:: PowerShell Get-Content -Wait = Linux tail -f
powershell -Command "Get-Content '%LOG_FILE%' -Tail 50 -Wait"
exit /b 0

:do_nothing
echo Server ishlashda davom etadi.
timeout /t 2 /nobreak >nul
exit /b 0

:: ====== YORDAMCHI: Serverni orqa fonda ishga tushirish (log faylga yoziladi) ======
:start_server
:: Wrapper bat fayl yaratish — server shu orqali ishlaydi
> "%WORK_DIR%\_server_runner.bat" (
    echo @echo off
    echo cd /d "%WORK_DIR%"
    echo set TELEGRAM_BOT_TOKEN=%TELEGRAM_BOT_TOKEN%
    echo %PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --reload ^> "%LOG_FILE%" 2^>^&1
)
:: VBS orqali yashirin oynada ishga tushirish
> "%TEMP%\totli_start_server.vbs" (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run """%WORK_DIR%\_server_runner.bat""", 0, False
)
cscript //nologo "%TEMP%\totli_start_server.vbs"
del "%TEMP%\totli_start_server.vbs" 2>nul
goto :eof

:: ====== YORDAMCHI: Barcha server jarayonlarini o'chirish ======
:kill_server
:: 1) PID faylidan o'chirish (butun jarayon daraxti)
if exist "%PID_FILE%" (
    set /p SAVED_PID=<"%PID_FILE%"
    if not "!SAVED_PID!"=="" (
        taskkill /PID !SAVED_PID! /F /T >nul 2>&1
    )
    del "%PID_FILE%" 2>nul
)

:: 2) Portni tinglayotgan BARCHA jarayonlarni o'chirish (zahira)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)

:: 3) WMIC orqali uvicorn command line bilan jarayonlarni topish
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%uvicorn%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto :eof
