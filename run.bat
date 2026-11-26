@echo off
rem Starts the GA4 + GTM audit tool. First run installs what it needs (about 2 minutes).
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.10 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)
if not exist .venv (
  echo Setting up for the first time...
  python -m venv .venv
  call .venv\Scripts\python -m pip install --quiet --upgrade pip
  call .venv\Scripts\python -m pip install --quiet -r requirements.txt
)
echo Opening the audit tool in your browser. Close this window to stop it.
call .venv\Scripts\python -m streamlit run app.py --browser.gatherUsageStats false
pause
