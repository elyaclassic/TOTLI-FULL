@echo off
title TOTLI HOLVA - DB nusxasidan ishga tushirish
cd /d "%~dp0"

echo ========================================
echo   DB nusxasini qayta tiklash va ishga tushirish
echo ========================================
echo   Backup faylni argument qilib bering yoki papkada backups\ qoldiring.
echo.

:: Agar backup fayl yo'li argument sifatida berilsa
if not "%~1"=="" (
    set "BACKUP=%~1"
    if not exist "%BACKUP%" (
        echo [X] Nusxa topilmadi: %BACKUP%
        pause
        exit /b 1
    )
    echo Nusxadan tiklanmoqda: %BACKUP%
    copy /Y "%BACKUP%" "totli_holva.db" >nul
    echo [OK] totli_holva.db yangilandi.
    echo.
    goto :run
)

:: backups\daily yoki backups da eng yangi totli_holva_*.db ni qidirish
set "BACKUP="
if exist "backups\daily\totli_holva_*.db" (
    for /f "delims=" %%F in ('dir /b /o-d "backups\daily\totli_holva_*.db" 2^>nul') do (
        set "BACKUP=%~dp0backups\daily\%%F"
        goto :do_restore
    )
)
if exist "backups\totli_holva_*.db" (
    for /f "delims=" %%F in ('dir /b /o-d "backups\totli_holva_*.db" 2^>nul') do (
        set "BACKUP=%~dp0backups\%%F"
        goto :do_restore
    )
)
:do_restore
if defined BACKUP (
    echo Eng yangi nusxa: %BACKUP%
    copy /Y "%BACKUP%" "totli_holva.db" >nul
    echo [OK] totli_holva.db yangilandi.
) else (
    if exist totli_holva.db (
        echo Nusxa topilmadi. Mavjud totli_holva.db ishlatiladi.
    ) else (
        echo Ogoh: totli_holva.db yo'q. create_admin.py yoki backup faylni qo'lda nusxalang.
    )
)
echo.

:run
echo Serverni ishga tushirish...
call "%~dp0start.bat"
