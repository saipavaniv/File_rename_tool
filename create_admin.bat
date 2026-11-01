@echo off
REM Creates (or resets) the admin account.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m app.cli create-admin --username admin --password "Smart-Rename-2026!"
if not exist samples python scripts\make_samples.py samples
echo.
echo  Sign in at http://localhost:8000  with  admin  /  Smart-Rename-2026!
echo.
pause
