@echo off
setlocal
set PORT=8081

echo Dev server (port %PORT%) o'chirilmoqda...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
    set FOUND=1
)
if "!FOUND!"=="1" (
    echo [OK] Dev server o'chirildi
) else (
    echo [!] Dev server ishlamayotgan edi
)
pause
