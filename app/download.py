"""Download a source video with yt-dlp (works for YouTube videos & VODs)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from . import config


class DownloadError(RuntimeError):
    pass


def download(
    url: str,
    on_progress: Optional[Callable[[float, str], None]] = None,
) -> tuple[str, str]:
    """Download the best <=1080p MP4 for `url`.

    Returns (file_path, video_title). Calls on_progress(fraction, message)
    while downloading if a callback is given.
    """
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise DownloadError(
            "yt-dlp is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    config.ensure_dirs()
    out_tmpl = str(config.DOWNLOAD_DIR / "%(id)s.%(ext)s")

    def hook(d: dict) -> None:
        if on_progress is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            on_progress(frac, "Downloading video…")
        elif d.get("status") == "finished":
            on_progress(1.0, "Download finished, preparing…")

    ydl_opts = {
        # Prefer a single progressive mp4 up to 1080p; fall back to best.
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001
        raise DownloadError(f"Could not download video: {exc}") from exc

    # Resolve the actual output path (extension may have changed on merge).
    video_id = info.get("id", "")
    title = info.get("title", "video")
    candidates = sorted(config.DOWNLOAD_DIR.glob(f"{video_id}.*"))
    path: Optional[Path] = None
    for c in candidates:
        if c.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            path = c
            break
    if path is None and candidates:
        path = candidates[0]
    if path is None or not path.exists():
        raise DownloadError("Download reported success but no file was found.")

    return str(path), title
