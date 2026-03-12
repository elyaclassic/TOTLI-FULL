@echo off
:: Bu faylni ikki marta bosing — CMD oynasi ochiladi va menyu chiqadi.
:: Agar server_boshqaruv.bat to'g'ridan-to'g'ri ochilmasa, shu fayldan foydalaning.
cd /d "%~dp0"
start "TOTLI Server boshqaruv" cmd /k "cd /d ""%~dp0"" & server_boshqaruv.bat"
