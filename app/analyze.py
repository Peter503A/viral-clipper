"""Heuristic "viral moment" detection.

This is deliberately simple and explainable. It is NOT an ML hype-detector.
The idea: moments that perform well as shorts tend to be the LOUD, DENSE,
HIGH-ACTION parts of a stream — a hype reaction, a clutch play, a burst of
laughter, a sudden scene change. We approximate "interesting" from signals we
can cheaply extract with ffmpeg:

  1. Audio loudness envelope  -> excitement / reactions / hype
  2. Scene-change density     -> visual action (fast cuts, movement)

We slide a window over the video, score each window by a weighted blend of
those signals, then greedily pick the top N non-overlapping windows.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from .models import Moment


@dataclass
class _Signals:
    # Per-second loudness (0..1 normalized) and scene-change timestamps.
    loudness: list[float]
    scene_times: list[float]
    step: float  # seconds per loudness sample


def _extract_loudness(path: str, step: float = 1.0) -> list[float]:
    """Return a normalized loudness value per `step` seconds.

    Uses ffmpeg's `astats` per-frame RMS level. We bucket frames into `step`
    windows and take the max RMS in each bucket, then normalize to 0..1.
    """
    cmd = [
        "ffmpeg",
        "-i",
        path,
        "-map",
        "0:a:0?",
        "-af",
        "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stderr + "\n" + proc.stdout

    # Lines look like: "frame:12  pts:... pts_time:3.456" and later
    # "lavfi.astats.Overall.RMS_level=-23.456"
    time_re = re.compile(r"pts_time:([0-9.]+)")
    rms_re = re.compile(r"RMS_level=(-?[0-9.]+|-?inf)")

    samples: list[tuple[float, float]] = []  # (time, rms_db)
    cur_time = 0.0
    for line in text.splitlines():
        m = time_re.search(line)
        if m:
            cur_time = float(m.group(1))
            continue
        r = rms_re.search(line)
        if r:
            val = r.group(1)
            db = -120.0 if val == "-inf" else float(val)
            samples.append((cur_time, db))

    if not samples:
        return []

    end = samples[-1][0]
    n_buckets = int(end / step) + 1
    buckets = [-120.0] * n_buckets
    for t, db in samples:
        idx = min(int(t / step), n_buckets - 1)
        if db > buckets[idx]:
            buckets[idx] = db

    # Normalize: map typical speech/quiet (-60 dB) .. loud (-5 dB) to 0..1.
    lo, hi = -60.0, -5.0
    norm = []
    for db in buckets:
        v = (db - lo) / (hi - lo)
        norm.append(max(0.0, min(1.0, v)))
    return norm


def _extract_scene_changes(path: str, threshold: float = 0.4) -> list[float]:
    """Return timestamps where the video content changes sharply."""
    cmd = [
        "ffmpeg",
        "-i",
        path,
        "-filter_complex",
        f"select='gt(scene,{threshold})',metadata=print",
        "-an",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stderr + "\n" + proc.stdout
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", text)]
    return times


def _gather(path: str, step: float = 1.0) -> _Signals:
    loudness = _extract_loudness(path, step=step)
    scenes = _extract_scene_changes(path)
    return _Signals(loudness=loudness, scene_times=scenes, step=step)


def find_moments(
    path: str,
    duration: float,
    num_clips: int,
    min_seconds: int,
    max_seconds: int,
) -> list[Moment]:
    """Find up to `num_clips` high-scoring non-overlapping moments."""
    sig = _gather(path)
    step = sig.step
    loud = sig.loudness

    # Fallback: no audio / analysis failed -> evenly spaced clips.
    if not loud:
        return _even_moments(duration, num_clips, min_seconds, max_seconds)

    total = len(loud)
    win = max(min_seconds, min(max_seconds, (min_seconds + max_seconds) // 2))
    win_samples = max(1, int(win / step))

    # Precompute scene-change count per second bucket for fast window sums.
    scene_per_bucket = [0.0] * (total + 1)
    for t in sig.scene_times:
        idx = min(int(t / step), total - 1)
        if 0 <= idx < len(scene_per_bucket):
            scene_per_bucket[idx] += 1.0

    def window_score(start_i: int) -> tuple[float, float]:
        end_i = min(total, start_i + win_samples)
        seg_loud = loud[start_i:end_i]
        if not seg_loud:
            return 0.0, 0.0
        avg_loud = sum(seg_loud) / len(seg_loud)
        peak_loud = max(seg_loud)
        scene_hits = sum(scene_per_bucket[start_i:end_i])
        scene_density = min(1.0, scene_hits / max(1.0, (end_i - start_i) / 5.0))
        # Weighted blend: sustained energy + a strong peak + visual action.
        score = 0.45 * avg_loud + 0.30 * peak_loud + 0.25 * scene_density
        return score, scene_density

    scored: list[Moment] = []
    for i in range(0, max(1, total - 1)):
        s, scene_density = window_score(i)
        start_t = i * step
        end_t = min(duration, start_t + win)
        if end_t - start_t < min_seconds:
            continue
        reason = _reason(s, scene_density)
        scored.append(Moment(start=start_t, end=end_t, score=s, reason=reason))

    # Greedy non-overlapping selection by score.
    scored.sort(key=lambda m: m.score, reverse=True)
    chosen: list[Moment] = []
    for m in scored:
        if all(_no_overlap(m, c) for c in chosen):
            chosen.append(m)
        if len(chosen) >= num_clips:
            break

    if not chosen:
        return _even_moments(duration, num_clips, min_seconds, max_seconds)

    chosen.sort(key=lambda m: m.start)
    return chosen


def _reason(score: float, scene_density: float) -> str:
    if scene_density > 0.5:
        return "High action / fast scene changes"
    if score > 0.6:
        return "Loud hype moment"
    if score > 0.4:
        return "Energetic segment"
    return "Notable moment"


def _no_overlap(a: Moment, b: Moment, gap: float = 2.0) -> bool:
    return a.end + gap <= b.start or b.end + gap <= a.start


def _even_moments(
    duration: float, num_clips: int, min_seconds: int, max_seconds: int
) -> list[Moment]:
    """Evenly spaced clips when we have no usable audio/video signal."""
    if duration <= 0:
        return []
    win = max(min_seconds, min(max_seconds, 30))
    n = max(1, min(num_clips, int(duration // win)))
    gap = duration / n
    out: list[Moment] = []
    for i in range(n):
        start = i * gap
        end = min(duration, start + win)
        if end - start >= min_seconds:
            out.append(Moment(start=start, end=end, score=0.0, reason="Evenly sampled"))
    return out
