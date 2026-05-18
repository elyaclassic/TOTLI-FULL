@echo off
cd /d "D:\TOTLI BI"
set TELEGRAM_BOT_TOKEN=
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --workers 1 > "D:\TOTLI BI\server.log" 2>&1
