@echo off
setlocal enabledelayedexpansion
title TOTLI HOLVA Business System

:: ========== IP VA PORT ==========
:: BIND_HOST=0.0.0.0 — barcha tarmoq interfeyslarida listening (127.0.0.1 ham, tarmoq IP ham)
:: DISPLAY_HOST — foydalanuvchiga ko'rsatiladigan asosiy URL
set BIND_HOST=0.0.0.0
set DISPLAY_HOST=10.243.165.156
set PORT=8080
set SSL_CERT=%~dp0cert.pem
set SSL_KEY=%~dp0key.pem
:: ========== TELEGRAM BOT ==========
:: BotFather dan olingan token (@BotFather -> /newbot)
:: Token ni .env faylida yoki quyida kiriting:
if "%TELEGRAM_BOT_TOKEN%"=="" set TELEGRAM_BOT_TOKEN=
:: ==============================================

set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%
set PID_FILE=%WORK_DIR%\server.pid
set LOG_FILE=%WORK_DIR%\server.log

:: ========== TELEGRAM SHEETS BOT (external) ==========
set BOT_DIR=%WORK_DIR%\external\telegram_sheets_bot
set BOT_LOG_FILE=%BOT_DIR%\bot.log
set BOT_RUNNER_FILE=%BOT_DIR%\_bot_runner.bat
set BOT_LOCK_PORT=47891
:: ====================================================

:: ========== SENIOR/EXPERT BOTLAR (standalone) ==========
set SENIOR_BOTS_RUNNER=%WORK_DIR%\scripts\_senior_bots_runner.bat
set SENIOR_BOTS_LOG=%WORK_DIR%\senior_bots.log
set SENIOR_BOTS_LOCK_PORT=47892
:: =======================================================

:: ========== CUSTOMER BOT (standalone) ==========
set CUSTOMER_BOT_RUNNER=%WORK_DIR%\scripts\_customer_bot_runner.bat
set CUSTOMER_BOT_LOG=%WORK_DIR%\customer_bot.log
set CUSTOMER_BOT_LOCK_PORT=47893
:: ================================================

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
:: SINGLE-INSTANCE GUARD: port bo'sh ko'rinsa ham osilgan/zombi uvicorn jarayoni
:: qolib ketgan bo'lishi mumkin (HTTP o'lgan, port bo'shagan, lekin process+scheduler tirik,
:: RAM yeydi va dublikat yaratadi). Yangi server'dan OLDIN ularni tozalaymiz.
call :kill_server
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
    call :start_bot_if_needed
    call :start_senior_bots_if_needed
    call :start_customer_bot_if_needed
    echo.
    echo ========================================
    echo   [OK] Server ishga tushdi (orqa fonda)
    echo   Brauzer: https://%DISPLAY_HOST%:%PORT%
    echo   Loglar:  %LOG_FILE%
    if "!BOT_STARTED_NOW!"=="1" echo   [OK] Telegram Sheets Bot ham ishga tushdi
    if "!BOT_ALREADY!"=="1"     echo   [!] Telegram Sheets Bot allaqachon ishlayapti
    if "!BOT_FAILED!"=="1"      echo   [X] Telegram Sheets Bot ishga tushmadi: %BOT_LOG_FILE%
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
:: Server ishlayapti — bot ham ishlayaptimi tekshirib, kerak bo'lsa boshlash
call :start_bot_if_needed
call :start_senior_bots_if_needed
call :start_customer_bot_if_needed
echo.
echo ========================================
echo   [!] Server allaqachon ishlayapti
echo       http://%DISPLAY_HOST%:%PORT%
if "!BOT_STARTED_NOW!"=="1" echo   [OK] Telegram Sheets Bot endi ishga tushdi
if "!BOT_ALREADY!"=="1"     echo   [OK] Telegram Sheets Bot ham ishlayapti
if "!BOT_FAILED!"=="1"      echo   [X] Telegram Sheets Bot ishga tushmadi
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
echo Server va bot qayta ishga tushirilmoqda...
call :kill_server
call :kill_bot
call :kill_senior_bots
call :kill_customer_bot
timeout /t 2 /nobreak >nul
echo Yangi server ishga tushirilmoqda...
call :start_server
timeout /t 3 /nobreak >nul
call :start_bot_if_needed
call :start_senior_bots_if_needed
call :start_customer_bot_if_needed
echo [OK] Server qayta ishga tushdi.
if "!BOT_STARTED_NOW!"=="1" echo [OK] Telegram Sheets Bot ham qayta ishga tushdi.
if "!BOT_FAILED!"=="1"      echo [X] Bot ishga tushmadi: %BOT_LOG_FILE%
echo     Server loglari: %LOG_FILE%
echo     Bot loglari:    %BOT_LOG_FILE%
echo.
pause
exit /b 0

:do_stop
echo.
echo Server va bot to'xtatilmoqda...
call :kill_server
call :kill_bot
call :kill_senior_bots
call :kill_customer_bot
echo [OK] Server va bot to'xtatildi.
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
    echo %PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --workers 1 ^> "%LOG_FILE%" 2^>^&1
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

:: ====== YORDAMCHI: Telegram Sheets Botni tekshirib, kerak bo'lsa ishga tushirish ======
:start_bot_if_needed
set BOT_STARTED_NOW=0
set BOT_ALREADY=0
set BOT_FAILED=0
if not exist "%BOT_DIR%\src\main.py" (
    set BOT_FAILED=1
    goto :eof
)
:: Allaqachon ishlayaptimi?
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%BOT_LOCK_PORT% " ^| findstr "LISTENING"') do (
    set BOT_ALREADY=1
    goto :eof
)
:: Bot Python interpretatorini topish (.venv ustun, fallback — system python)
set BOT_PYTHON=
if exist "%BOT_DIR%\.venv\Scripts\python.exe" set BOT_PYTHON="%BOT_DIR%\.venv\Scripts\python.exe"
if "%BOT_PYTHON%"=="" set BOT_PYTHON=%PYTHON_CMD%
if "%BOT_PYTHON%"=="" (
    set BOT_FAILED=1
    goto :eof
)
:: Runner faylini har gal tozalab yozish (yo'l noto'g'ri bo'lishi mumkin — Z:\ vs D:\)
> "%BOT_RUNNER_FILE%" (
    echo @echo off
    echo cd /d "%BOT_DIR%"
    echo %BOT_PYTHON% -m src.main ^> "%BOT_LOG_FILE%" 2^>^&1
)
:: VBS orqali yashirin oynada ishga tushirish
> "%TEMP%\totli_start_bot.vbs" (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run """%BOT_RUNNER_FILE%""", 0, False
)
cscript //nologo "%TEMP%\totli_start_bot.vbs"
del "%TEMP%\totli_start_bot.vbs" 2>nul
:: 3 sekund kutib ishga tushganini tekshirish
timeout /t 3 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%BOT_LOCK_PORT% " ^| findstr "LISTENING"') do (
    set BOT_STARTED_NOW=1
    goto :eof
)
set BOT_FAILED=1
goto :eof

:: ====== YORDAMCHI: Telegram Sheets Botni o'chirish ======
:kill_bot
:: 1) Lock port (47891) ni tinglayotgan jarayonni o'chirish
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%BOT_LOCK_PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
:: 2) Zahira: WMIC orqali telegram_sheets_bot src.main ishlatayotgan python jarayonlarini topish
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%telegram_sheets_bot%%src.main%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto :eof

:: ====== YORDAMCHI: Senior/Expert botlar (standalone) ishga tushirish ======
:start_senior_bots_if_needed
:: Allaqachon ishlayaptimi? (lock port 47892 - listen bo'lsa)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%SENIOR_BOTS_LOCK_PORT% " ^| findstr "LISTENING"') do goto :eof
:: Zahira: jarayon CommandLine bo'yicha (eski nusxa listen qilmagan bo'lishi mumkin)
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%senior_bots_standalone%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do goto :eof
:: Statik runner - VBS yashirin oyna
> "%TEMP%\totli_start_senior.vbs" (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run """%SENIOR_BOTS_RUNNER%""", 0, False
)
cscript //nologo "%TEMP%\totli_start_senior.vbs"
del "%TEMP%\totli_start_senior.vbs" 2>nul
goto :eof

:: ====== YORDAMCHI: Senior/Expert botlarni o'chirish ======
:kill_senior_bots
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%SENIOR_BOTS_LOCK_PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%senior_bots_standalone%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto :eof

:: ====== YORDAMCHI: Customer bot (standalone) ishga tushirish ======
:start_customer_bot_if_needed
:: Already running? (lock port 47893)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%CUSTOMER_BOT_LOCK_PORT% " ^| findstr "LISTENING"') do goto :eof
:: Fallback: check by CommandLine
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%customer_bot_standalone%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do goto :eof
:: Write runner bat (ASCII only, no Cyrillic)
> "%CUSTOMER_BOT_RUNNER%" (
    echo @echo off
    echo setlocal
    echo set ROOT=D:\TOTLI BI
    echo cd /d "%%ROOT%%"
    echo set PY=
    echo where python >nul 2>&1 ^&^& set PY=python
    echo if not "%%PY%%"=="" goto run
    echo where py >nul 2>&1 ^&^& set PY=py -3
    echo if not "%%PY%%"=="" goto run
    echo if exist "%%LocalAppData%%\Programs\Python\Python313\python.exe" set PY="%%LocalAppData%%\Programs\Python\Python313\python.exe"
    echo if not "%%PY%%"=="" goto run
    echo if exist "C:\Program Files\Python313\python.exe" set PY="C:\Program Files\Python313\python.exe"
    echo :run
    echo if "%%PY%%"=="" ^( echo [%%date%% %%time%%] PYTHON NOT FOUND ^>^> "%%ROOT%%\customer_bot.log" ^& exit /b 1 ^)
    echo %%PY%% scripts\customer_bot_standalone.py ^>^> "%%ROOT%%\customer_bot.log" 2^>^&1
    echo endlocal
)
:: Launch hidden via VBS
> "%TEMP%\totli_start_customer.vbs" (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run """%CUSTOMER_BOT_RUNNER%""", 0, False
)
cscript //nologo "%TEMP%\totli_start_customer.vbs"
del "%TEMP%\totli_start_customer.vbs" 2>nul
goto :eof

:: ====== YORDAMCHI: Customer bot o'chirish ======
:kill_customer_bot
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%CUSTOMER_BOT_LOCK_PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%customer_bot_standalone%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto :eof
