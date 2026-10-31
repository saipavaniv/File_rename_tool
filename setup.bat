@echo off
REM One-time setup on Windows (needs Python 3.11+ from python.org, "Add to PATH" ticked)
cd /d "%~dp0"
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
if not exist .env copy .env.example .env
python scripts\make_cert.py %COMPUTERNAME%
python -m app.cli create-admin --username admin
echo.
echo Done. Edit .env if needed, then run start.bat
goto :eof
:err
echo Setup failed. See the messages above.
