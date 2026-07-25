@echo off
setlocal
cd /d "%~dp0"

echo Repairing the Story Downloader browser environment...

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv 2>nul || python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements.txt

if errorlevel 1 (
    echo Failed to update Python requirements.
    pause
    exit /b 1
)

python -m playwright install chromium
python -m playwright install --list
python browser_check.py

if errorlevel 1 (
    echo.
    echo Repair did not find a working browser.
    echo Make sure Microsoft Edge or Google Chrome is installed, then run this file again.
    pause
    exit /b 1
)

echo.
echo Browser repair completed successfully.
pause
