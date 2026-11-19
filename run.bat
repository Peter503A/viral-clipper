@echo off
REM One-shot setup + run for Windows. Usage: run.bat
cd /d "%~dp0"

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo ERROR: ffmpeg is not installed or not on PATH.
  echo   Install with: winget install Gyan.FFmpeg
  echo   Then open a NEW terminal and run this again.
  exit /b 1
)

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Installing Python dependencies...
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo Starting Viral Clipper on http://127.0.0.1:8000
python -m app.main
