@echo off
REM ============================================================
REM  TOTLI BI — Server AUTOSTART setup (svet o'chgach avtomatik)
REM  Bir martalik. server2220 KONSOLIDA Administrator sifatida ishga tushiring.
REM  (SMB'dan Claude qila olmaydi — schtasks lokal mashinaga ta'sir qiladi.)
REM
REM  Nima qiladi:
REM   1. python.exe TO'LIQ yo'lini aniqlaydi (bare 'python' boot'da topilmaydi)
REM   2. _server_runner.bat'ni to'liq yo'l bilan qayta yozadi (eski nusxa .bak)
REM   3. 'At system startup' (login EMAS) Task: TOTLI_BI_Autostart, SYSTEM
REM   4. Tekshiradi va python yo'li bo'yicha ogohlantiradi
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "D:\TOTLI BI"

echo.
echo === [1/4] python.exe yo'lini aniqlash ===
set "PYEXE="
for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if not defined PYEXE (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PYEXE set "PYEXE=%%i"
    )
)
if not defined PYEXE (
    echo XATO: python topilmadi. python o'rnatilganini yoki PATH'ni tekshiring.
    echo Qo'lda: python -c "import sys;print(sys.executable)"
    pause
    exit /b 1
)
echo Topildi: "!PYEXE!"

echo.
echo === [2/4] _server_runner.bat qayta yozish ===
if exist "_server_runner.bat" copy /y "_server_runner.bat" "_server_runner.bat.bak.autostart" >nul
powershell -NoProfile -Command ^
  "$py='!PYEXE!';" ^
  "$lines=@('@echo off','cd /d \"D:\TOTLI BI\"','set TELEGRAM_BOT_TOKEN=','\"'+$py+'\" -m uvicorn main:app --host 0.0.0.0 --port 8080 --workers 1 > \"D:\TOTLI BI\server.log\" 2>&1');" ^
  "Set-Content -Path 'D:\TOTLI BI\_server_runner.bat' -Value $lines -Encoding ASCII"
echo Yangi _server_runner.bat:
type "_server_runner.bat"

echo.
echo === [3/4] Task Scheduler: TOTLI_BI_Autostart (At startup, SYSTEM) ===
schtasks /delete /tn "TOTLI_BI_Autostart" /f >nul 2>&1
schtasks /create /tn "TOTLI_BI_Autostart" /tr "cmd /c \"D:\TOTLI BI\_server_runner.bat\"" /sc ONSTART /ru SYSTEM /rl HIGHEST /f
if errorlevel 1 (
    echo XATO: Task yaratilmadi. Bu oynani Administrator sifatida ochganingizni tekshiring.
    pause
    exit /b 1
)

echo.
echo === [4/4] Tekshiruv ===
schtasks /query /tn "TOTLI_BI_Autostart" /v /fo LIST | findstr /I "TaskName Status Next Last Run-As Schedule Trigger"

echo.
echo ============================================================
echo  TAYYOR. Endi svet o'chib yonganda Windows boot'da server
echo  avtomatik ko'tariladi (login shart emas). Watchdog 2-daq
echo  zaxira sifatida qoladi.
echo.
echo  python yo'li: "!PYEXE!"
echo !PYEXE! | findstr /I "\\Users\\" >nul
if not errorlevel 1 (
    echo.
    echo  *** OGOHLANTIRISH ***
    echo  python C:\Users\ ostida (per-user o'rnatilgan). SYSTEM hisobi
    echo  per-user paketlarni KO'RMASLIGI mumkin -> ImportError.
    echo  Agar boot'da server ko'tarilmasa, taskni Administrator
    echo  paroli bilan qayta yarating:
    echo.
    echo  schtasks /create /tn "TOTLI_BI_Autostart" /tr "cmd /c \"D:\TOTLI BI\_server_runner.bat\"" /sc ONSTART /ru "%USERNAME%" /rp PAROL /rl HIGHEST /f
    echo.
    echo  (PAROL o'rniga shu hisob parolini yozing)
)
echo ============================================================
echo  Sinov: konsolda --  schtasks /run /tn "TOTLI_BI_Autostart"
echo  keyin server.log yangilanganini tekshiring.
echo ============================================================
pause
endlocal
