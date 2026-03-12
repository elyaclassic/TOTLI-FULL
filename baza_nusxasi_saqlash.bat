@echo off
chcp 65001 >nul
cd /d "%~dp0"

set DB=totli_holva.db
if not exist "%DB%" (
  echo [X] totli_holva.db topilmadi. Loyiha ildizida ishlatilayotganini tekshiring.
  pause
  exit /b 1
)

for /f "tokens=*" %%a in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'"') do set D=%%a
set NUSXA=totli_holva_backup_%D%.db
copy /Y "%DB%" "%NUSXA%" >nul
echo [OK] Nusxa yaratildi: %NUSXA%
echo.
echo Bu faylni boshqa kompyuterga olib, loyiha papkasida totli_holva.db nomi bilan saqlang.
echo.
pause
