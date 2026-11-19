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

# 3) Dependencies
echo "Installing Python dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 4) Run
echo "Starting Viral Clipper on http://127.0.0.1:8000"
python -m app.main
