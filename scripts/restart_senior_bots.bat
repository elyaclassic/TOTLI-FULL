@echo off
REM ============================================================
REM  Senior/Expert standalone botlarni TOZA restart.
REM  Muammo: socket-lock (47892) - eski jarayon tirik bo'lsa
REM  yangi nusxa exit(1) qiladi. Shuning uchun: AVVAL O'CHIR,
REM  keyin ishga tushir. server2220'da RDP, Administrator.
REM  ASCII-only (cmd parser tuzog'i).
REM ============================================================
setlocal
set ROOT=D:\TOTLI BI
set SBOT_PORT=47892
cd /d "%ROOT%"

echo === Senior botlar TOZA restart ===
echo.
echo [1/3] Eski standalone jarayon o'chirilmoqda...
REM Lock port bo'yicha (listen fix'li yangi nusxa uchun)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%SBOT_PORT% " ^| findstr "LISTENING"') do taskkill /PID %%a /F /T >nul 2>&1
REM PowerShell CommandLine bo'yicha (wmic Server 2022'da YO'Q; listen'siz eski nusxa ham topiladi)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ? { $_.CommandLine -match 'senior_bots_standalone' } | % { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 3 /nobreak >nul
echo     ... o'chirildi

echo [2/3] Yangi standalone (14 ekspert) ishga tushirilmoqda...
> "%TEMP%\restart_sb.vbs" echo Set W=CreateObject("WScript.Shell")
>> "%TEMP%\restart_sb.vbs" echo W.Run """%ROOT%\scripts\_senior_bots_runner.bat""",0,False
cscript //nologo "%TEMP%\restart_sb.vbs" >nul
del "%TEMP%\restart_sb.vbs" 2>nul
echo     ... ko'tarilmoqda (12 sek kutish)
timeout /t 12 /nobreak >nul

echo [3/3] Tekshiruv...
set SB_OK=0
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%SBOT_PORT% " ^| findstr "LISTENING"') do set SB_OK=1
echo.
if "%SB_OK%"=="1" (
    echo   [OK] Standalone botlar 47892 LISTENING
) else (
    echo   [?] Port ko'rinmadi - senior_bots.log tekshiring
    echo       (1-2 daq ichida 14 bot Connection established bo'lsa OK)
)
echo.
echo   Log: %ROOT%\senior_bots.log
echo   Gruxda @Sardor_Mobile_Flutter_bot ga savol berib sinang.
echo.
pause
endlocal
