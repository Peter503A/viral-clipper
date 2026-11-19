@echo off
REM One-shot setup + run for Windows. Usage: run.bat
setlocal
cd /d "%~dp0"

REM --- Find ffmpeg ---
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo ERROR: ffmpeg is not installed or not on PATH.
  echo   Install with: winget install Gyan.FFmpeg
  echo   Then open a NEW terminal and run this again.
  exit /b 1
)

REM --- Find a Python launcher: prefer "py", fall back to "python" ---
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo ERROR: Python was not found. Install it with: winget install Python.Python.3.12
  echo   Then open a NEW terminal and run this again.
  exit /b 1
)
echo Using Python launcher: %PYEXE%

REM --- Virtual environment ---
if not exist ".venv" (
  echo Creating virtual environment...
  %PYEXE% -m venv .venv
  if errorlevel 1 (
    echo ERROR: Could not create the virtual environment.
    exit /b 1
  )
)
call .venv\Scripts\activate.bat

REM --- Dependencies (stop if this fails, do not start a broken server) ---
echo Installing Python dependencies (first run can take a few minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: Installing dependencies failed. See the messages above.
  exit /b 1
)

echo.
echo Starting Viral Clipper on http://127.0.0.1:8000
echo Open that address in your browser. Press Ctrl+C here to stop.
python -m app.main
