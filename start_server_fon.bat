@echo off
:: TOTLI HOLVA — orqa fonda server (avtostart uchun, oyna ochilmaydi)
cd /d "%~dp0"

:: ========== start.bat bilan bir xil (kerak bo'lsa shu yerdan o'zgartiring)
set BIND_HOST=10.243.165.156
set PORT=8080
:: ==========================================

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
if exist "C:\Program Files\Python312\python.exe" set PYTHON=C:\Program Files\Python312\python.exe
if not "%PYTHON%"=="" goto :found
if exist "C:\Program Files\Python311\python.exe" set PYTHON=C:\Program Files\Python311\python.exe
if not "%PYTHON%"=="" goto :found
:found
if "%PYTHON%"=="" exit /b 1
echo %PYTHON% | findstr "\\" >nul && set PYTHON_CMD="%PYTHON%" || set PYTHON_CMD=%PYTHON%

%PYTHON_CMD% -m pip install -r requirements.txt -q >nul 2>&1
if not exist "logs" mkdir logs
echo [%date% %time%] Server ishga tushmoqda... >> logs\server_fon.log
%PYTHON_CMD% -m uvicorn main:app --host %BIND_HOST% --port %PORT% --reload >> logs\server_fon.log 2>&1
