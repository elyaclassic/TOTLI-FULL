@echo off
REM Task Scheduler tomonidan har 1 daqiqada chaqiriladi (elya_ user da).
REM Inbox dan o'qilmagan xabarlarni Claude CLI ga uzatadi va Telegramga javob yuboradi.
cd /d "D:\TOTLI BI"
python "D:\TOTLI BI\scripts\claude_inbox_responder.py" >> "D:\TOTLI BI\watchdog.log" 2>&1
