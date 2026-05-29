@echo off
REM Mijoz (customer) bot standalone runner (watchdog + manual).
REM ASCII-only (cmd parser). Yashirin oynada VBS orqali chaqiriladi.
setlocal
set ROOT=D:\TOTLI BI
cd /d "%ROOT%"

set PY=
where python >nul 2>&1 && set PY=python
if not "%PY%"=="" goto run
where py >nul 2>&1 && set PY=py -3
if not "%PY%"=="" goto run
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set PY="%LocalAppData%\Programs\Python\Python313\python.exe"
if not "%PY%"=="" goto run
if exist "C:\Program Files\Python313\python.exe" set PY="C:\Program Files\Python313\python.exe"
if not "%PY%"=="" goto run
if exist "C:\Python313\python.exe" set PY="C:\Python313\python.exe"

:run
if "%PY%"=="" (
    echo [%date% %time%] PYTHON TOPILMADI >> "%ROOT%\customer_bot.log"
    exit /b 1
)
%PY% scripts\customer_bot_standalone.py >> "%ROOT%\customer_bot.log" 2>&1
endlocal
