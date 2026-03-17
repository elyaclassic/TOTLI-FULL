@echo off
setlocal enabledelayedexpansion
title TOTLI HOLVA Business System

:: ========== IP VA PORT ==========
set BIND_HOST=10.243.165.156
set PORT=8080
:: ==============================================

echo ========================================
echo   TOTLI HOLVA Biznes Tizimi
echo ========================================
echo.

cd /d "%~dp0"

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

:: Server ishlamayapti — orqa fonda ishga tushirish
echo [3/3] Server orqa fonda ishga tushirilmoqda...
set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%
set PID_FILE=%WORK_DIR%\server.pid

:: VBS orqali yashirin ishga tushirish — PID ni faylga saqlash
echo Set WshShell = CreateObject("WScript.Shell") > "%TEMP%\totli_start_server.vbs"
echo Dim oExec >> "%TEMP%\totli_start_server.vbs"
echo Set oExec = WshShell.Exec("cmd /c cd /d ""%WORK_DIR%"" && %PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT%") >> "%TEMP%\totli_start_server.vbs"
echo Open "%PID_FILE%" For Output As #1 >> "%TEMP%\totli_start_server.vbs"
echo Print #1, oExec.ProcessID >> "%TEMP%\totli_start_server.vbs"
echo Close #1 >> "%TEMP%\totli_start_server.vbs"
cscript //nologo "%TEMP%\totli_start_server.vbs"
del "%TEMP%\totli_start_server.vbs" 2>nul

timeout /t 3 /nobreak >nul
echo.
echo ========================================
echo   Server ishga tushdi (orqa fonda)
echo   Brauzer: http://%BIND_HOST%:%PORT%
echo ========================================
echo   Oynani yoping — server ishlashda davom etadi.
echo   To'xtatish: start.bat ni qayta ishga tushiring.
echo ========================================
echo.
pause
exit /b 0

:server_running
echo.
echo [!] Server allaqachon ishlayapti (port %PORT%).
echo.
choice /C HTY /M "H=To'xtatish  T=Qayta ishga tushirish  Y=Davom etish"
if errorlevel 3 goto :no_stop
if errorlevel 2 goto :do_restart
if errorlevel 1 goto :do_stop

:do_stop
echo.
echo Server to'xtatilmoqda...
call :kill_server
echo [OK] Server to'xtatildi.
echo.
pause
exit /b 0

:do_restart
echo.
echo Server qayta ishga tushirilmoqda...
call :kill_server
timeout /t 2 /nobreak >nul
echo Yangi server ishga tushirilmoqda...
set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%
set PID_FILE=%WORK_DIR%\server.pid
echo Set WshShell = CreateObject("WScript.Shell") > "%TEMP%\totli_start_server.vbs"
echo Dim oExec >> "%TEMP%\totli_start_server.vbs"
echo Set oExec = WshShell.Exec("cmd /c cd /d ""%WORK_DIR%"" && %PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT%") >> "%TEMP%\totli_start_server.vbs"
echo Open "%PID_FILE%" For Output As #1 >> "%TEMP%\totli_start_server.vbs"
echo Print #1, oExec.ProcessID >> "%TEMP%\totli_start_server.vbs"
echo Close #1 >> "%TEMP%\totli_start_server.vbs"
cscript //nologo "%TEMP%\totli_start_server.vbs"
del "%TEMP%\totli_start_server.vbs" 2>nul
timeout /t 3 /nobreak >nul
echo [OK] Server qayta ishga tushdi.
echo.
pause
exit /b 0

:no_stop
echo Server ishlashda davom etadi.
timeout /t 2 /nobreak >nul
exit /b 0

:: ===== YORDAMCHI: barcha server jarayonlarini o'chirish =====
:kill_server
set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%
set PID_FILE=%WORK_DIR%\server.pid

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

:: 3) Uvicorn nomi bilan ishlaydigan python jarayonlarni o'chirish
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH 2^>nul') do (
    set CHECK_PID=%%~a
)
:: WMIC orqali uvicorn command line bilan jarayonlarni topish
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%uvicorn%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)
timeout /t 1 /nobreak >nul
goto :eof
