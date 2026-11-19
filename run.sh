#!/usr/bin/env bash
# One-shot setup + run for macOS / Linux.
# Usage: ./run.sh
set -e

cd "$(dirname "$0")"

# 1) Check ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg is not installed or not on PATH."
  echo "  macOS:  brew install ffmpeg"
  echo "  Ubuntu: sudo apt install ffmpeg"
  exit 1
fi

# 2) Virtual env
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3) Dependencies (stop on failure instead of launching a broken server)
echo "Installing Python dependencies (first run can take a few minutes)…"
pip install --upgrade pip
pip install -r requirements.txt

# 4) Run
echo "Starting Viral Clipper on http://127.0.0.1:8000"
echo "Open that address in your browser. Press Ctrl+C here to stop."
python -m app.main
