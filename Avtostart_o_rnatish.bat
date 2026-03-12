@echo off
chcp 65001 >nul
title TOTLI HOLVA — Avtostart o'rnatish
cd /d "%~dp0"

echo ========================================
echo   TOTLI HOLVA — Avtostart
echo ========================================
echo.
echo Kompyuter har safar yonganida (yoki siz tizimga kirganingizda)
echo server orqa fonda avtomatik ishga tushadi. Oyna ochilmaydi.
echo.

set TASK_NAME=TOTLI_BI_Server

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if errorlevel 1 (
    echo Vazifa yaratilmoqda...
    schtasks /create /tn "%TASK_NAME%" /tr "wscript.exe \"%~dp0totli_avtostart.vbs\"" /sc onlogon /rl highest /f
    if errorlevel 1 (
        echo [X] Vazifa yaratishda xato. Administrator sifatida urinib ko'ring.
        pause
        exit /b 1
    )
    echo [OK] Avtostart o'rnatildi.
) else (
    echo [OK] Avtostart allaqachon o'rnatilgan.
)

echo.
echo Endi kompyuterni qayta ishga tushirsangiz, server o'zi ishga tushadi.
echo Brauzerda: http://localhost:8080 (yoki http://10.243.165.156:8080)
echo.
echo O'chirish: Vazifalar rejasi — "%TASK_NAME%" ni o'chiring.
echo.
pause
