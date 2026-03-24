@echo off
:: TOTLI POS — Avtomatik chop etish rejimi
:: Alohida Chrome profil — boshqa Chrome oynalariga ta'sir qilmaydi
:: Print dialog chiqmaydi, default printerga avtomatik chop etadi

set URL=http://10.243.165.156:8080/sales/pos
set POS_PROFILE=%USERPROFILE%\TotliPOS_Chrome

:: Chrome yo'lini topish
set CHROME=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe

if "%CHROME%"=="" (
    echo Chrome topilmadi!
    pause
    exit /b 1
)

echo ========================================
echo   TOTLI POS - Avtomatik chop etish
echo   Printer: Default (X Printer 80mm)
echo ========================================
echo.

start "" "%CHROME%" --user-data-dir="%POS_PROFILE%" --kiosk-printing --disable-print-preview --app="%URL%"
