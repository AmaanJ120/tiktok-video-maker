@echo off
title TikTok Video Maker

echo ============================================
echo  TikTok Video Maker - Setup ^& Launch
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] FFmpeg not found on PATH.
    echo Download from: https://www.gyan.dev/ffmpeg/builds/
    echo Extract and add the bin\ folder to your system PATH.
    echo.
    echo The app will start but video generation will fail until FFmpeg is installed.
    pause
)

:: Check font
if not exist "fonts\Roboto-Bold.ttf" (
    echo [WARNING] fonts\Roboto-Bold.ttf not found.
    echo Download Roboto Bold from https://fonts.google.com/specimen/Roboto
    echo and place Roboto-Bold.ttf in the fonts\ folder.
    pause
)

:: Create venv if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Install dependencies
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt -q

:: Launch
echo.
echo Starting server at http://localhost:5000
echo Press Ctrl+C to stop.
echo.
start "" "http://localhost:5000"
python app.py
