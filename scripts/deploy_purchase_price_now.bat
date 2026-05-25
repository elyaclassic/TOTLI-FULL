@echo off
REM TOTLI — purchase_price deploy: stop -> backfill --apply -> restart
REM server2220'da ishga tushiring: D:\TOTLI BI\scripts\deploy_purchase_price_now.bat
cd /d "D:\TOTLI BI"
echo === [1/3] Server to'xtatilmoqda (python.exe) ===
taskkill /IM python.exe /F
echo.
echo === [2/3] Backfill --apply (faqat toza 154, SUSPECT/SKIP yozilmaydi) ===
python "scripts\backfill_produced_purchase_price.py" "D:\TOTLI BI\totli_holva.db" --apply > "backfill_apply.log" 2>&1
type "backfill_apply.log"
echo.
echo === [3/3] Server qayta ishga tushirilmoqda ===
call "start.bat"
