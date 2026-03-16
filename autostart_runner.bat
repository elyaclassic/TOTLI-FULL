@echo off
cd /d "%~dp0"

set BIND_HOST=0.0.0.0
set PORT=8080

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
if exist "C:\Program Files\Python312\python.exe" set PYTHON=C:\Program Files\Python312\python.exe
if not "%PYTHON%"=="" goto :found
if exist "C:\Program Files\Python311\python.exe" set PYTHON=C:\Program Files\Python311\python.exe
:found
if "%PYTHON%"=="" exit /b 1
echo %PYTHON% | findstr "\\" >nul && set PYTHON_CMD="%PYTHON%" || set PYTHON_CMD=%PYTHON%

:: launch_server.vbs ni chaqirish (oynasiz)
wscript.exe "%~dp0launch_server.vbs"
