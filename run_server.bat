@echo off
title TOTLI HOLVA Business System
cd /d "%~dp0"

set BIND_HOST=0.0.0.0
set PORT=8080

:: Python qidirish
set PYTHON_CMD=
where python >nul 2>&1 && set PYTHON_CMD=python
if not "%PYTHON_CMD%"=="" goto :run
where py >nul 2>&1 && set PYTHON_CMD=py -3
if not "%PYTHON_CMD%"=="" goto :run
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set PYTHON_CMD=%LocalAppData%\Programs\Python\Python313\python.exe
if not "%PYTHON_CMD%"=="" goto :run
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PYTHON_CMD=%LocalAppData%\Programs\Python\Python312\python.exe
if not "%PYTHON_CMD%"=="" goto :run
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set PYTHON_CMD=%LocalAppData%\Programs\Python\Python311\python.exe
if not "%PYTHON_CMD%"=="" goto :run
if exist "C:\Program Files\Python312\python.exe" set PYTHON_CMD=C:\Program Files\Python312\python.exe
if not "%PYTHON_CMD%"=="" goto :run
if exist "C:\Program Files\Python311\python.exe" set PYTHON_CMD=C:\Program Files\Python311\python.exe
:run
if "%PYTHON_CMD%"=="" (
    echo [X] Python topilmadi!
    pause
    exit /b 1
)

echo Server ishga tushmoqda: http://%BIND_HOST%:%PORT%
echo.
%PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --reload

echo.
echo Server to'xtadi. Oynani yopish uchun biror tugmani bosing.
pause
