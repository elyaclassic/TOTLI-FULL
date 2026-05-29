@echo off
:: TOTLI Mobile APK build skripti
:: Memory: GRADLE_USER_HOME C:\gradle_home (UNC va kirill harf muammosi)
:: Server2220 da bevosita ishga tushirish kerak (UNC dan ishlamaydi)

setlocal
set GRADLE_USER_HOME=C:\gradle_home

cd /d "%~dp0"
echo [1/3] Flutter dependencies tekshirilmoqda...
flutter pub get
if errorlevel 1 (
    echo [X] pub get xato
    pause
    exit /b 1
)

echo [2/3] APK build qilinmoqda (release)...
flutter build apk --release
if errorlevel 1 (
    echo [X] APK build xato — yuqoridagi xatoga qarang
    pause
    exit /b 1
)

echo [3/3] APK app/static ga ko'chirilmoqda...
copy /Y "build\app\outputs\flutter-apk\app-release.apk" "..\app\static\totli-agent.apk"
if errorlevel 1 (
    echo [!] APK ko'chirish xato — qo'lda ko'chiring:
    echo     Manba: %~dp0build\app\outputs\flutter-apk\app-release.apk
    echo     Qabul: ..\app\static\totli-agent.apk
    pause
    exit /b 1
)

echo.
echo [OK] APK muvaffaqiyatli tayyor — v2.0.14+62
echo Yo'l: app\static\totli-agent.apk
echo Foydalanuvchilar avtomatik yangilanish xabarini olishadi
echo.
pause
exit /b 0
