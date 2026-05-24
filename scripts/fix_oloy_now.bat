@echo off
REM server2220 konsolida: D:\TOTLI BI\scripts\fix_oloy_now.bat
REM OLOY yo'l-kira tuzatish (--apply) + server restart (sales.py merge fix ham jonli bo'ladi)
cd /d "D:\TOTLI BI"
echo === [1/3] Server to'xtatilmoqda (python.exe) ===
taskkill /IM python.exe /F
echo.
echo === [2/3] OLOY yo'l-kira tuzatish --apply (OLOY +600000 -> 0, naqd chiqim 600000) ===
python "scripts\fix_oloy_yolkira_20260517.py" "D:\TOTLI BI\totli_holva.db" --apply > "fix_oloy.log" 2>&1
type "fix_oloy.log"
echo.
echo === [3/3] Server qayta ishga tushirilmoqda (sales.py merge + oldingi deploy) ===
call "start.bat"
