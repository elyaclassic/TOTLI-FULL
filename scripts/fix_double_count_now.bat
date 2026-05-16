@echo off
REM TOTLI — double-count 2 victim tuzatish: stop -> --apply -> restart
REM server2220'da: D:\TOTLI BI\scripts\fix_double_count_now.bat
cd /d "D:\TOTLI BI"
echo === [1/3] Server to'xtatilmoqda (python.exe) ===
taskkill /IM python.exe /F
echo.
echo === [2/3] Double-count tuzatish --apply (9 sale_revert, +80 dona) ===
python "scripts\fix_double_count_20260516.py" "D:\TOTLI BI\totli_holva.db" --apply > "fix_double_count.log" 2>&1
type "fix_double_count.log"
echo.
echo === [3/3] Server qayta ishga tushirilmoqda ===
call "start.bat"
