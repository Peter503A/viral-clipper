"""Trim long silences / dead air from a clip to make it feel lively.

Approach: detect silent spans with ffmpeg's `silencedetect`, then keep the
non-silent spans (plus a small padding) and concatenate them. Short pauses are
kept so speech stays natural; only gaps longer than `min_silence` are cut.
This also removes most "ähm"-style dead air surrounded by pauses.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .ffmpeg_utils import run, probe


def _detect_silences(path: str, noise_db: float = -32.0, min_silence: float = 0.6):
    cmd = [
        "ffmpeg",
        "-i",
        path,
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([0-9.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end: ([0-9.]+)", text)]
    spans = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        spans.append((s, e))
    return spans


def _keep_segments(duration: float, silences, pad: float = 0.12):
    """Invert silence spans into the segments we keep."""
    keep = []
    cursor = 0.0
    for s, e in silences:
        seg_end = max(cursor, s + pad)
        if seg_end - cursor > 0.25:
            keep.append((cursor, min(seg_end, duration)))
        cursor = (e - pad) if e is not None else duration
        cursor = max(0.0, cursor)
    if cursor < duration - 0.1:
        keep.append((cursor, duration))
    # Merge touching/near segments.
    merged = []
    for seg in keep:
        if merged and seg[0] - merged[-1][1] < 0.15:
            merged[-1] = (merged[-1][0], seg[1])
        else:
            merged.append(list(seg))
    return [(a, b) for a, b in merged if b - a > 0.2]


def trim_silence(path: str, out_path: Path) -> str:
    """Produce a silence-trimmed copy. Returns the path to use downstream.

    If trimming would remove almost nothing (or fails), returns the original
    path unchanged.
    """
    info = probe(path)
    if not info.has_audio or info.duration <= 0:
        return path

    silences = _detect_silences(path)
    if not silences:
        return path

    segments = _keep_segments(info.duration, silences)
    if not segments:
        return path

    kept = sum(b - a for a, b in segments)
    # If we'd only shave <10%, not worth re-encoding.
    if kept >= info.duration * 0.9:
        return path

    # Build a filter_complex that trims + concats video and audio.
    parts = []
    v_labels = []
    a_labels = []
    for i, (a, b) in enumerate(segments):
        parts.append(
            f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        parts.append(
            f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
        v_labels.append(f"[v{i}]")
        a_labels.append(f"[a{i}]")
    n = len(segments)
    parts.append("".join(v_labels) + f"concat=n={n}:v=1:a=0[vout]")
    parts.append("".join(a_labels) + f"concat=n={n}:v=0:a=1[aout]")
    filtergraph = ";".join(parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        path,
        "-filter_complex",
        filtergraph,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        str(out_path),
    ]
    try:
        run(cmd)
    except RuntimeError:
        return path
    return str(out_path)
