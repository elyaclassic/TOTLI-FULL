@echo off
cd /d "D:\TOTLI BI"
set TELEGRAM_BOT_TOKEN=8436785441:AAF1N5nmh-_Ey5tOUbTUvapPD3fJHNFmjjE
python -m uvicorn main:app --host 10.243.165.156 --port 8080 --reload > "D:\TOTLI BI\server.log" 2>&1
