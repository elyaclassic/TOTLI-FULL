@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === TOTLI BI — Git va GitHub sozlash ===
echo.

REM Git qidirish
set "GIT_PATH="
for %%P in (
    "C:\Program Files\Git\cmd\git.exe"
    "%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
    "%ProgramFiles%\Git\cmd\git.exe"
) do if exist %%P set "GIT_PATH=%%~P" & goto :found
:found

if "%GIT_PATH%"=="" (
    echo [XATO] Git topilmadi.
    echo.
    echo GitHub Desktop o'rnatilgan bo'lsa, uni oching va:
    echo   File -^> Add Local Repository -^> d:\TOTLI BI tanlang
    echo   Agar .git yo'q deyilsa: File -^> Create New Repository
    echo     Local path: d:\
    echo     Name: TOTLI BI
    echo.
    echo Yoki Git o'rnating: https://git-scm.com/download/win
    pause
    exit /b 1
)

echo Git topildi: %GIT_PATH%
echo.

if not exist ".git" (
    echo git init...
    "%GIT_PATH%" init
    echo.
)

echo git add .
"%GIT_PATH%" add .
echo.

echo git commit...
"%GIT_PATH%" commit -m "TOTLI BI: Backend + Flutter mobil ilova" 2>nul
if errorlevel 1 (
    echo Commit mavjud yoki o'zgarish yo'q.
)

"%GIT_PATH%" branch -M main 2>nul

echo.
echo === Tayyor ===
echo.
echo Endi GitHub Desktop da:
echo   1. File -^> Add Local Repository
echo   2. d:\TOTLI BI tanlang
echo   3. Publish repository yoki Push
echo.
echo Baza (totli_holva.db) Git ga KIRMAYDI - ma'lumotlar xavfsiz.
echo.
pause
