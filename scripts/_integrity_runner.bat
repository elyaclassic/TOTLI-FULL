@echo off
REM TOTLI BI Integrity Check runner — har soatda Task Scheduler chaqiradi
cd /d "D:\TOTLI BI"
python scripts\integrity_check.py --quiet >> integrity_check.log 2>&1
