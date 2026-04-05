@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo venv yoq — avval: python -m venv .venv
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m src.main
