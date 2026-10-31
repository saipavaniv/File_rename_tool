@echo off
REM Creates (or resets) the admin account. Run while the server window is closed or open - both work.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m app.cli create-admin --username admin --password "Smart-Rename-2026!"
if not exist samples python scripts\make_samples.py samples
python -m app.cli import-parties samples\parties.csv
echo.
echo  Sign in at http://localhost:8000  with  admin  /  Smart-Rename-2026!
echo.
pause
