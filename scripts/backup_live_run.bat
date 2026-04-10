@echo off
REM Windows Task Scheduler wrapper — har 5 daqiqada chaqiriladi
cd /d "D:\TOTLI BI"
python "D:\TOTLI BI\scripts\backup_live.py" >> "D:\TOTLI_BI_BACKUPS\backup_live.log" 2>&1
exit /b %ERRORLEVEL%
