@echo off
chcp 65001 >nul
REM ============================================================
REM  TOTLI BI — Server AUTOSTART (svet o'chgach avtomatik) — v2 TUZATILGAN
REM  server2220 KONSOLIDA Administrator sifatida 1 MARTA ishga tushiring.
REM
REM  v1 xatosi: _server_runner.bat'ni inline-PowerShell bilan qayta yozgan
REM  edi -> '>' cmd redirektsiyasi + ASCII kirill yo'lni buzdi.
REM  v2: _server_runner.bat'ga TEGMAYDI (bare 'python' Администратор
REM  PATH'da ishlaydi). Faqat 'At startup' Task'ni Администратор
REM  kontekstida yaratadi (SYSTEM emas — per-user python'ni ko'rmaydi).
REM ============================================================
cd /d "D:\TOTLI BI"

echo.
echo === [1/3] Eski (buzilgan) TOTLI_BI_Autostart o'chirilmoqda ===
schtasks /delete /tn "TOTLI_BI_Autostart" /f >nul 2>&1
echo Tozalandi.

echo.
echo === [2/3] Yangi Task: At startup, %USERNAME% kontekstida ===
echo ----------------------------------------------------------------
echo  DIQQAT: quyida "%USERNAME%" hisobining PAROLINI so'raydi.
echo  Bu parol Windows'da xavfsiz saqlanadi va boot'da login'siz
echo  server'ni ko'tarish uchun ishlatiladi.
echo ----------------------------------------------------------------
schtasks /create /tn "TOTLI_BI_Autostart" /tr "cmd /c \"D:\TOTLI BI\_server_runner.bat\"" /sc ONSTART /ru "%USERNAME%" /rl HIGHEST /f
if errorlevel 1 (
    echo.
    echo XATO: Task yaratilmadi. Bu oyna Administrator sifatida ochilganini
    echo va parol to'g'ri kiritilganini tekshiring.
    pause
    exit /b 1
)

echo.
echo === [3/3] Tekshiruv ===
schtasks /query /tn "TOTLI_BI_Autostart" /v /fo LIST | findstr /I "TaskName Status Logon Schedule Next Run"

echo.
echo ============================================================
echo  TAYYOR. Svet o'chib yonganda Windows boot'da server
echo  AVTOMATIK ko'tariladi (login shart emas). Watchdog har 2 daq
echo  zaxira bo'lib qoladi.
echo.
echo  Sinov (server o'chmasdan turib xavfsiz):
echo    schtasks /run /tn "TOTLI_BI_Autostart"
echo  -- bu yana bitta uvicorn ochishga urinadi; port band bo'lgani
echo  uchun ikkinchisi darrov o'ladi, lekin task "Last Result 0x0"
echo  bo'lsa konfiguratsiya to'g'ri. ASL sinov: keyingi haqiqiy
echo  reboot'da server.log yangilanishi.
echo ============================================================
pause
