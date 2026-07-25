@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo Failed to install Python requirements.
    pause
    exit /b 1
)

if not exist ".venv\.playwright-chromium-ready" (
    echo Installing the browser used to scan all story parts...
    python -m playwright install chromium
    if not errorlevel 1 (
        type nul > ".venv\.playwright-chromium-ready"
    ) else (
        echo.
        echo Warning: Chromium installation failed.
        echo The app can still try single-item extraction, but scanning all story parts may fail.
    )
)

start "" http://127.0.0.1:5000
python app.py
pause
