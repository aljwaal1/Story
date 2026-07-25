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

echo.
echo Checking Playwright browser installation...
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo Chromium download failed. The app will try Microsoft Edge or Google Chrome.
)

python browser_check.py
if errorlevel 1 (
    echo.
    echo No compatible browser could be started.
    echo Run repair_browser.bat, then start.bat again.
    pause
    exit /b 1
)

start "" http://127.0.0.1:5000
python app.py
pause
