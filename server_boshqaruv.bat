@echo off
title TOTLI HOLVA - Server boshqaruv
cd /d "%~dp0"
set PORT=8080
set "choice="

:menu
cls
echo ========================================
echo   TOTLI HOLVA — Server boshqaruv (barchasi shu yerdan)
echo ========================================
echo.
echo   1. Holatni tekshirish   — server ishlayaptimi?
echo   2. To'xtatish           — serverni to'xtatish
echo   3. Qayta ishga tushirish — to'xtatib, keyin yana ishga tushirish
echo   4. Chiqish
echo.
set /p choice="Tanlang (1-4): "

if "%choice%"=="1" goto holat
if "%choice%"=="2" goto toxtat
if "%choice%"=="3" goto qayta
if "%choice%"=="4" exit
goto menu

:holat
echo.
echo --- Holat ---
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [Holat] Server ISHLAMAYAPTI — port %PORT% band emas.
    echo Ishga tushirish: 3 ni tanlang yoki start.bat / start_server_fon.bat
) else (
    echo [Holat] Server ISHLAYAPTI — port %PORT% band.
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
        echo Protsess ID (PID): %%a
        goto :holat_done
    )
    :holat_done
    echo Brauzer: http://10.243.165.156:%PORT%  yoki  http://localhost:%PORT%
    echo Log: logs\server_fon.log
)
echo.
pause
goto menu

:toxtat
echo.
echo --- To'xtatish ---
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo Port %PORT% da hech narsa yo'q. Server allaqachon to'xtagan.
) else (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
        echo Port %PORT% band qilgan protsess (PID %%a) to'xtatilmoqda...
        taskkill /PID %%a /F
        if errorlevel 1 (
            echo Xato: to'xtatish muvaffaqiyatsiz. CMD ni Administrator sifatida ochib qayta urinib ko'ring.
        ) else (
            echo Serverni to'xtatdim.
        )
        goto :toxtat_done
    )
    echo Port topildi, lekin PID aniqlanmadi.
    :toxtat_done
)
echo.
pause
goto menu

:qayta
echo.
echo --- Qayta ishga tushirish ---
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo Eski protsessni to'xtatish (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
    timeout /t 2 /nobreak >nul
    goto :qayta_start
)
:qayta_start
echo Yangi server yangi oynada ishga tushiryapman...
start "TOTLI Server" "%~dp0start_server_fon.bat"
timeout /t 3 /nobreak >nul
echo Tayyor. Brauzerda: http://10.243.165.156:%PORT%
echo Boshqaruv oynasini yopmasangiz, yana 1-4 ni tanlashingiz mumkin.
echo.
pause
goto menu
