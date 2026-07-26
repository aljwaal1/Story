@echo off
setlocal
cd /d "%~dp0"
title Universal Downloader Pro

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

python -c "import flask, requests, yt_dlp"
if errorlevel 1 (
    echo.
    echo The downloader requirements are not available.
    pause
    exit /b 1
)

echo.
echo Starting Universal Downloader Pro...
echo Public links only. No account login is required.
start "" http://127.0.0.1:5000
python app.py
pause
