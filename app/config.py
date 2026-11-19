"""Central configuration and filesystem paths."""
from __future__ import annotations

import os
from pathlib import Path

# Root of the project (the `clipper/` directory).
BASE_DIR = Path(__file__).resolve().parent.parent

# Where web assets live.
WEB_DIR = BASE_DIR / "web"

# Working directory for downloads, intermediate files and rendered clips.
# Override with CLIPPER_DATA_DIR if you want it somewhere else.
DATA_DIR = Path(os.environ.get("CLIPPER_DATA_DIR", BASE_DIR / "data"))
DOWNLOAD_DIR = DATA_DIR / "downloads"
CLIPS_DIR = DATA_DIR / "clips"
# Commentary mode: uploaded gameplay background videos + rendered outputs.
LIBRARY_DIR = DATA_DIR / "library"
COMMENTARY_DIR = DATA_DIR / "commentary"

# Whisper model size. tiny/base/small run on CPU; medium/large need more RAM
# (and ideally a GPU). Override with CLIPPER_WHISPER_MODEL.
WHISPER_MODEL = os.environ.get("CLIPPER_WHISPER_MODEL", "small")

# Target output format: vertical 9:16 for Reels / Shorts / TikTok.
OUT_WIDTH = 1080
OUT_HEIGHT = 1920

# Default clip length bounds (seconds).
MIN_CLIP_SECONDS = 15
MAX_CLIP_SECONDS = 60

# ---- Text-to-speech (Commentary mode) --------------------------------------
# Which TTS backend to use: "openai", "elevenlabs", or "piper" (local/free).
TTS_PROVIDER = os.environ.get("CLIPPER_TTS_PROVIDER", "openai")

# OpenAI TTS
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TTS_MODEL = os.environ.get("CLIPPER_OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.environ.get("CLIPPER_OPENAI_TTS_VOICE", "onyx")

# ElevenLabs
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("CLIPPER_ELEVENLABS_VOICE_ID", "")

# Piper (local, free). Point this at a downloaded .onnx voice model.
PIPER_MODEL_PATH = os.environ.get("CLIPPER_PIPER_MODEL", "")

# Host / port for the local server.
HOST = os.environ.get("CLIPPER_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLIPPER_PORT", "8000"))


def ensure_dirs() -> None:
    """Create all working directories if they do not exist."""
    for d in (DATA_DIR, DOWNLOAD_DIR, CLIPS_DIR, LIBRARY_DIR, COMMENTARY_DIR):
        d.mkdir(parents=True, exist_ok=True)
