@echo off
REM ============================================================
REM  Standalone botlar deploy - server2220'da RDP orqali
REM  ADMINISTRATOR sifatida ishga tushiring (Run as administrator).
REM  Tartib 409 ("terminated by other getUpdates") oldini oladi:
REM    1) uvicorn'ni o'ldirish (ichki botlar ham o'ladi)
REM    2) uvicorn qayta start (YANGI main.py -> botlar ichida EMAS)
REM    3) standalone botlarni start
REM  BI ~15-20 sek uziladi (faqat shu daqiqa).
REM  ROLLBACK: .env'ga BOTS_IN_PROCESS=1 qo'shing + bu skriptni
REM            qayta yuriting (standalone o'rniga ichki rejim).
REM  ASCII-only (cmd parser).
REM ============================================================
setlocal enabledelayedexpansion
set ROOT=D:\TOTLI BI
cd /d "%ROOT%"
set PORT=8080
set SBOT_PORT=47892

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] ADMINISTRATOR kerak. O'ng tugma -^> Run as administrator.
    pause
    exit /b 1
)

echo === Standalone botlar deploy (server2220) ===
echo.
echo BI ~15-20 sek uziladi. Davom etish uchun ENTER, bekor: Ctrl+C
pause >nul

echo [1/4] uvicorn o'chirilmoqda (ichki botlar ham)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do taskkill /PID %%a /F /T >nul 2>&1
for /f "tokens=2 delims=," %%a in ('wmic process where "name='python.exe' and CommandLine like '%%uvicorn%%'" get ProcessId /format:csv 2^>nul ^| findstr /v "^$" ^| findstr /v "ProcessId"') do taskkill /PID %%a /F /T >nul 2>&1
timeout /t 3 /nobreak >nul

echo [2/4] uvicorn qayta ishga tushirilmoqda (yangi main.py)...
if not exist "%ROOT%\_server_runner.bat" (
    echo [ERROR] _server_runner.bat yo'q. Buning o'rniga start.bat ni bir marta yuriting.
    pause
    exit /b 1
)
> "%TEMP%\dep_srv.vbs" echo Set W=CreateObject("WScript.Shell")
>> "%TEMP%\dep_srv.vbs" echo W.Run """%ROOT%\_server_runner.bat""",0,False
cscript //nologo "%TEMP%\dep_srv.vbs" >nul
del "%TEMP%\dep_srv.vbs" 2>nul
echo     ... server ko'tarilmoqda (15 sek kutish)
timeout /t 15 /nobreak >nul
set SRV_OK=0
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do set SRV_OK=1
if "!SRV_OK!"=="1" (echo     [OK] uvicorn 8080 LISTENING) else (echo     [X] uvicorn ko'tarilmadi - server.log tekshiring & pause & exit /b 1)

echo [3/4] Standalone botlar ishga tushirilmoqda...
> "%TEMP%\dep_sb.vbs" echo Set W=CreateObject("WScript.Shell")
>> "%TEMP%\dep_sb.vbs" echo W.Run """%ROOT%\scripts\_senior_bots_runner.bat""",0,False
cscript //nologo "%TEMP%\dep_sb.vbs" >nul
del "%TEMP%\dep_sb.vbs" 2>nul
echo     ... botlar ko'tarilmoqda (12 sek kutish)
timeout /t 12 /nobreak >nul

echo [4/4] Tekshiruv...
set SB_OK=0
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%SBOT_PORT% " ^| findstr "LISTENING"') do set SB_OK=1
echo.
echo === NATIJA ===
if "!SRV_OK!"=="1" (echo   [OK] uvicorn / BI : 8080 LISTENING) else (echo   [X] uvicorn)
if "!SB_OK!"=="1"  (echo   [OK] Standalone botlar : %SBOT_PORT% LISTENING) else (echo   [X] Standalone botlar - senior_bots.log tekshiring)
echo.
echo   Loglar: server.log  +  senior_bots.log
echo   Gruxda /status yuborib botlarni sinang.
echo   ROLLBACK: .env'ga BOTS_IN_PROCESS=1 + bu skript qayta.
echo.
pause
endlocal
