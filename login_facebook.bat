@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Failed to install Python requirements.
    pause
    exit /b 1
)

python browser_check.py >nul 2>&1
if errorlevel 1 (
    echo Installing Chromium for Facebook login...
    python -m playwright install chromium
)

echo.
echo A Facebook browser window will open.
echo Sign in yourself. The application never asks for or stores your password.
echo.
python facebook_session.py

echo.
pause
