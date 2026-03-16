@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: TOTLI HOLVA - Avtomatik backup (Task Scheduler uchun)
:: Har kuni ishlatish: schtasks /create /tn "TOTLI Backup" /tr "d:\TOTLI BI\backup_avtomatik.bat" /sc daily /st 02:00

set DB=totli_holva.db
if not exist "%DB%" (
  echo [X] totli_holva.db topilmadi.
  exit /b 1
)

:: Backup papkasi (yil-oy)
for /f "tokens=*" %%a in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM'"') do set YM=%%a
if not exist "backups" mkdir backups
if not exist "backups\%YM%" mkdir "backups\%YM%"

:: Sana va vaqt
for /f "tokens=*" %%a in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd_HH-mm'"') do set D=%%a
set NUSXA=backups\%YM%\totli_holva_%D%.db

copy /Y "%DB%" "%NUSXA%" >nul
if errorlevel 1 (
  echo [X] Nusxa yaratishda xato
  exit /b 1
)

echo [OK] Backup: %NUSXA%

:: Eski nusxalarni saqlash (oxirgi 30 kun)
:: Eski backuplarni o'chirish ixtiyoriy - quyidagi qatorni yoqish uchun :: ni olib tashlang
:: forfiles /p "backups" /s /d -30 /c "cmd /c del @path" 2>nul

exit /b 0
