@echo off
REM TOTLI BI Integrity Check runner — Task Scheduler chaqiradi
REM SYSTEM hisobida PATH'da python yo'q — to'g'ridan-to'g'ri qidiramiz

cd /d "D:\TOTLI BI"

REM Python interpretatorini topish (start.bat patterniga o'xshash)
set PYTHON=
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set PYTHON="%LocalAppData%\Programs\Python\Python313\python.exe"
if "%PYTHON%"=="" if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PYTHON="%LocalAppData%\Programs\Python\Python312\python.exe"
if "%PYTHON%"=="" if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set PYTHON="%LocalAppData%\Programs\Python\Python311\python.exe"
if "%PYTHON%"=="" if exist "C:\Users\elya_\AppData\Local\Programs\Python\Python313\python.exe" set PYTHON="C:\Users\elya_\AppData\Local\Programs\Python\Python313\python.exe"
if "%PYTHON%"=="" if exist "C:\Users\elya_\AppData\Local\Programs\Python\Python312\python.exe" set PYTHON="C:\Users\elya_\AppData\Local\Programs\Python\Python312\python.exe"
if "%PYTHON%"=="" if exist "C:\Users\elya_\AppData\Local\Programs\Python\Python311\python.exe" set PYTHON="C:\Users\elya_\AppData\Local\Programs\Python\Python311\python.exe"
if "%PYTHON%"=="" if exist "C:\Program Files\Python313\python.exe" set PYTHON="C:\Program Files\Python313\python.exe"
if "%PYTHON%"=="" if exist "C:\Program Files\Python312\python.exe" set PYTHON="C:\Program Files\Python312\python.exe"
if "%PYTHON%"=="" if exist "C:\Program Files\Python311\python.exe" set PYTHON="C:\Program Files\Python311\python.exe"
if "%PYTHON%"=="" if exist "C:\Python313\python.exe" set PYTHON="C:\Python313\python.exe"
if "%PYTHON%"=="" if exist "C:\Python312\python.exe" set PYTHON="C:\Python312\python.exe"
if "%PYTHON%"=="" set PYTHON=py

%PYTHON% scripts\integrity_check.py --quiet >> "D:\TOTLI BI\integrity_check.log" 2>&1
