@echo off
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
set SERVER_PID=
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set SERVER_PID=%%a
    goto :check_done
)
:check_done

if not "%SERVER_PID%"=="" goto :server_running

:: Server ishlamayapti — orqa fonda ishga tushirish
echo [3/3] Server orqa fonda ishga tushirilmoqda...
set RUN_CMD=%PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --reload
set WORK_DIR=%~dp0
if "%WORK_DIR:~-1%"=="\" set WORK_DIR=%WORK_DIR:~0,-1%

:: VBS orqali yashirin ishga tushirish (oyna yopilsa ham server davom etadi)
echo Set WshShell = CreateObject("WScript.Shell") > "%TEMP%\totli_start_server.vbs"
echo WshShell.Run "cmd /c cd /d ""%WORK_DIR%"" && %PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --reload", 0, False >> "%TEMP%\totli_start_server.vbs"
cscript //nologo "%TEMP%\totli_start_server.vbs"
del "%TEMP%\totli_start_server.vbs" 2>nul

timeout /t 2 /nobreak >nul
echo.
echo ========================================
echo   Server ishga tushdi (orqa fonda)
echo   Brauzer: http://localhost:%PORT%
echo ========================================
echo   Oynani yoping — server ishlashda davom etadi.
echo   To'xtatish: start.bat ni qayta ishga tushiring va "Ha" tanlang.
echo ========================================
echo.
pause
exit /b 0

:server_running
echo.
echo [!] Server allaqachon ishlayapti (port %PORT%).
echo.
choice /C HY /M "To'xtatmoqchimisiz? H=Ha (server to'xtaydi), Y=Yo'q (davom etadi)"
if errorlevel 2 goto :no_stop
if errorlevel 1 goto :do_stop

:do_stop
echo.
echo Server to'xtatilmoqda...
taskkill /PID %SERVER_PID% /F >nul 2>&1
timeout /t 1 /nobreak >nul
:: Agar bir nechta jarayon bo'lsa (uvicorn + python), barcha portni ishlatayotganlarni to'xtatish
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
echo [OK] Server to'xtatildi.
echo.
pause
exit /b 0

:no_stop
echo Server ishlashda davom etadi.
timeout /t 2 /nobreak >nul
exit /b 0
