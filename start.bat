@echo off
REM Start Hop on Windows. First time: run setup.bat
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run.py
