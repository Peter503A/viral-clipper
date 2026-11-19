@echo off
REM ============================================================
REM  Double-click launcher for Viral Clipper.
REM  - First run: sets everything up (can take a few minutes).
REM  - Later runs: starts right away and opens your browser.
REM  Keep the window that appears open while you use the app.
REM ============================================================
cd /d "%~dp0"
title Viral Clipper
start "Viral Clipper" cmd /k "run.bat"
