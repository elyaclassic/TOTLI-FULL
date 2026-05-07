@echo off
echo %DATE% %TIME% wrapper boshlandi user=%USERNAME% >> "D:\TOTLI BI\watchdog.log"
powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "D:\TOTLI BI\watchdog.ps1" 1>> "D:\TOTLI BI\watchdog.log" 2>&1
echo %DATE% %TIME% wrapper tugadi exitcode=%ERRORLEVEL% >> "D:\TOTLI BI\watchdog.log"
