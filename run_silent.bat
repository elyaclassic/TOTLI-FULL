@echo off
cd /d "%~dp0"
:: start.bat dan o'tkazilgan o'zgaruvchilar
if "%BIND_HOST%"=="" set BIND_HOST=0.0.0.0
if "%PORT%"=="" set PORT=8080
if "%PYTHON_CMD%"=="" set PYTHON_CMD=python

start /b "" %PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --reload
exit
