"""Text-to-speech with swappable backends.

One function, `synthesize(text, out_path, voice)`, writes spoken audio for the
given script. The backend is chosen by config.TTS_PROVIDER:

  - "openai"     : OpenAI TTS API         (needs OPENAI_API_KEY)
  - "elevenlabs" : ElevenLabs API         (needs ELEVENLABS_API_KEY + voice id)
  - "piper"      : Piper, local & free    (needs a downloaded .onnx voice)

Each backend is isolated so a missing key for one does not break the others.
The output is an audio file (mp3 or wav) that the renderer mixes over gameplay.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import config


class TTSError(RuntimeError):
    pass


def synthesize(text: str, out_path: Path, voice: str = "") -> Path:
    """Generate speech audio for `text`. Returns the written file path."""
    text = text.strip()
    if not text:
        raise TTSError("Script is empty.")

    provider = config.TTS_PROVIDER.lower()
    if provider == "openai":
        return _openai(text, out_path, voice)
    if provider == "elevenlabs":
        return _elevenlabs(text, out_path, voice)
    if provider == "piper":
        return _piper(text, out_path)
    raise TTSError(f"Unknown TTS provider: {provider!r}")


# --- OpenAI -----------------------------------------------------------------
def _openai(text: str, out_path: Path, voice: str) -> Path:
    if not config.OPENAI_API_KEY:
        raise TTSError(
            "OPENAI_API_KEY is not set. Export it, or switch "
            "CLIPPER_TTS_PROVIDER to 'piper' for free local voices."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise TTSError("Install the OpenAI SDK: pip install openai") from exc

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    chosen = voice or config.OPENAI_TTS_VOICE
    mp3 = out_path.with_suffix(".mp3")
    try:
        with client.audio.speech.with_streaming_response.create(
            model=config.OPENAI_TTS_MODEL,
            voice=chosen,
            input=text,
        ) as response:
            response.stream_to_file(str(mp3))
    except Exception as exc:  # noqa: BLE001
        raise TTSError(f"OpenAI TTS failed: {exc}") from exc
    return mp3


# --- ElevenLabs -------------------------------------------------------------
def _elevenlabs(text: str, out_path: Path, voice: str) -> Path:
    if not config.ELEVENLABS_API_KEY:
        raise TTSError("ELEVENLABS_API_KEY is not set.")
    voice_id = voice or config.ELEVENLABS_VOICE_ID
    if not voice_id:
        raise TTSError(
            "No ElevenLabs voice id. Set CLIPPER_ELEVENLABS_VOICE_ID."
        )

    import json
    import urllib.request

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = json.dumps(
        {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "xi-api-key": config.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    mp3 = out_path.with_suffix(".mp3")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            mp3.write_bytes(resp.read())
    except Exception as exc:  # noqa: BLE001
        raise TTSError(f"ElevenLabs TTS failed: {exc}") from exc
    return mp3


# --- Piper (local, free) ----------------------------------------------------
def _piper(text: str, out_path: Path) -> Path:
    model = config.PIPER_MODEL_PATH
    if not model or not Path(model).exists():
        raise TTSError(
            "Piper voice model not found. Download a .onnx voice from "
            "https://github.com/rhasspy/piper and set CLIPPER_PIPER_MODEL."
        )
    import shutil
    import subprocess

    if shutil.which("piper") is None:
        raise TTSError("The `piper` binary is not on PATH. Install Piper.")

    wav = out_path.with_suffix(".wav")
    try:
        proc = subprocess.run(
            ["piper", "--model", model, "--output_file", str(wav)],
            input=text,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise TTSError(proc.stderr.strip() or "piper failed")
    except TTSError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TTSError(f"Piper TTS failed: {exc}") from exc
    return wav
