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

REM --- Find a Python launcher ---
REM Prefer Python 3.12 (all packages have prebuilt wheels for it). Very new
REM versions like 3.13+/3.15 often lack wheels and try to compile from source,
REM which needs a C++ toolchain and fails. We pin 3.12 when available.
set "PYEXE="
py -3.12 --version >nul 2>nul && set "PYEXE=py -3.12"
if not defined PYEXE (
  py -3.11 --version >nul 2>nul && set "PYEXE=py -3.11"
)
if not defined PYEXE (
  py -3.10 --version >nul 2>nul && set "PYEXE=py -3.10"
)
if not defined PYEXE (
  where py >nul 2>nul && set "PYEXE=py"
)
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
echo Your browser will open automatically. Keep this window open while you work.
echo Press Ctrl+C here (or close this window) to stop the app.

REM Open the browser a moment after the server starts (in the background).
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

python -m app.main
