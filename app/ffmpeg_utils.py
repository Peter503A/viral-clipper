"""Thin wrappers around ffmpeg / ffprobe, plus availability checks."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


class FFmpegNotFound(RuntimeError):
    pass


def ensure_ffmpeg() -> None:
    """Raise a clear error if ffmpeg/ffprobe are not installed on PATH."""
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise FFmpegNotFound(
            "Missing required tool(s): "
            + ", ".join(missing)
            + ". Install FFmpeg and make sure it is on your PATH "
            "(macOS: `brew install ffmpeg`, Ubuntu: `sudo apt install ffmpeg`)."
        )


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def probe(path: str) -> VideoInfo:
    """Return basic stream info for a media file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)

    width = height = 0
    fps = 0.0
    has_audio = False
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and width == 0:
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
            fps = _parse_fps(rate)
        elif codec_type == "audio":
            has_audio = True

    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    return VideoInfo(duration=duration, width=width, height=height, fps=fps, has_audio=has_audio)


def _parse_fps(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def run(cmd: list[str]) -> None:
    """Run an ffmpeg command, raising with stderr on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-15:]
        raise RuntimeError("ffmpeg failed:\n" + "\n".join(tail))
