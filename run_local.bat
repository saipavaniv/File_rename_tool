@echo off
REM ============================================================
REM  Smart Renamer - run on THIS computer only (demo / testing)
REM  Double-click this file. First run takes a few minutes.
REM ============================================================
cd /d "%~dp0"
title Smart Renamer

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python is not installed.
  echo  1. Download it from https://www.python.org/downloads/
  echo  2. During install, TICK "Add python.exe to PATH"
  echo  3. Then double-click run_local.bat again.
  echo.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating Python environment...
  python -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat
echo Installing / checking components (first time: 2-5 minutes)...
python -m pip install -q --disable-pip-version-check -r requirements.txt || goto :err

if not exist .env (
  > .env echo # Local demo: only reachable from this computer
  >> .env echo HOST=127.0.0.1
  >> .env echo PORT=8000
  >> .env echo ALLOWED_HOSTS=localhost,127.0.0.1
  >> .env echo COOKIE_SECURE=false
)

if not exist data\renamer.db (
  echo Creating the admin account and loading sample data...
  python -m app.cli create-admin --username admin --password "Smart-Rename-2026!" || goto :err
  python scripts\make_samples.py samples || goto :err
  python -m app.cli import-parties samples\parties.csv || goto :err
  echo.
  echo  ==========================================
  echo   Sign in with:  admin  /  Smart-Rename-2026!
  echo   (change it under Account after signing in)
  echo  ==========================================
  echo.
)

echo Starting... the browser will open at http://localhost:8000
echo Keep this window open while you use Smart Renamer. Close it to stop.
start "" cmd /c "timeout /t 6 >nul & start http://localhost:8000"
python run.py
goto :eof

:err
echo.
echo Something went wrong - see the messages above.
pause
