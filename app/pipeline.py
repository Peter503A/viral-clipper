"""Orchestrates the full clip pipeline for one job.

Stages & progress budget (0..1):
  download   0.00 -> 0.25
  analyze    0.25 -> 0.40
  per clip   0.40 -> 1.00  (transcribe + trim + render for each clip)
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config, library
from .analyze import find_moments
from .download import download
from .ffmpeg_utils import ensure_ffmpeg, probe
from .jobs import JobStore
from .models import ClipInfo, Job, JobKind, JobState
from .render import render_clip, render_commentary
from .transcribe import parse_marked_script, transcribe_clip, transcribe_file
from .trim import trim_silence
from .tts import synthesize


def run_job(store: JobStore, job: Job) -> None:
    """Dispatch to the correct pipeline based on job kind."""
    ensure_ffmpeg()
    config.ensure_dirs()
    if job.kind == JobKind.COMMENTARY:
        _run_commentary(store, job)
    else:
        _run_clip(store, job)


def _safe_name(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")
    return (text[:40] or "clip").lower()


def _run_clip(store: JobStore, job: Job) -> None:
    req = job.request

    # ---- Get the source: uploaded file or download -----------------------
    if req.upload_id.strip():
        store.update(job, state=JobState.DOWNLOADING, progress=0.10,
                     message="Using uploaded file…")
        source = str(config.DOWNLOAD_DIR / Path(req.upload_id).name)
        if not Path(source).exists():
            raise RuntimeError("Uploaded source file is missing.")
        title = Path(req.upload_id).stem
    else:
        store.update(job, state=JobState.DOWNLOADING, progress=0.0,
                     message="Starting download…")

        def dl_progress(frac: float, msg: str) -> None:
            store.update(job, progress=0.25 * frac, message=msg)

        source, title = download(req.url, on_progress=dl_progress)
    job.source_path = source
    job.video_title = title

    info = probe(source)
    job.duration = info.duration
    job.width = info.width
    job.height = info.height
    if info.width == 0 or info.height == 0:
        raise RuntimeError("Could not read video dimensions from the download.")

    store.update(job, progress=0.25, message=f"Downloaded: {title}")

    # ---- Analyze ----------------------------------------------------------
    store.update(job, state=JobState.ANALYZING, message="Finding viral moments…")
    moments = find_moments(
        source,
        duration=info.duration,
        num_clips=req.num_clips,
        min_seconds=req.min_seconds,
        max_seconds=req.max_seconds,
    )
    if not moments:
        raise RuntimeError("No usable moments found in this video.")
    store.update(job, progress=0.40, message=f"Found {len(moments)} candidate moments.")

    # ---- Per-clip: trim -> transcribe -> render --------------------------
    out_dir = config.CLIPS_DIR / job.id
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_dir / "_tmp"
    tmp_dir.mkdir(exist_ok=True)

    total = len(moments)
    base_name = _safe_name(title)

    for i, moment in enumerate(moments):
        frac_start = 0.40 + (i / total) * 0.60
        frac_end = 0.40 + ((i + 1) / total) * 0.60

        store.update(
            job,
            state=JobState.RENDERING,
            progress=frac_start,
            message=f"Clip {i + 1}/{total}: cutting…",
        )

        # 1) Cut the raw moment to a temp file (fast copy of the segment).
        raw_clip = tmp_dir / f"raw_{i:02d}.mp4"
        _cut_segment(source, moment.start, moment.end, raw_clip)

        work_clip = str(raw_clip)

        # 2) Optional silence trim (lively editing).
        if req.trim_silence:
            store.update(job, message=f"Clip {i + 1}/{total}: trimming dead air…")
            trimmed = tmp_dir / f"trim_{i:02d}.mp4"
            work_clip = trim_silence(work_clip, trimmed)

        # 3) Transcribe -> English captions.
        cues = []
        if req.subtitles:
            store.update(
                job,
                state=JobState.TRANSCRIBING,
                message=f"Clip {i + 1}/{total}: generating subtitles…",
            )
            try:
                cues = transcribe_clip(work_clip)
            except Exception as exc:  # noqa: BLE001 - captions are best-effort
                store.update(job, message=f"Clip {i + 1}: subtitles skipped ({exc})")
                cues = []

        # 4) Render the split-screen + burned captions.
        store.update(
            job,
            state=JobState.RENDERING,
            progress=(frac_start + frac_end) / 2,
            message=f"Clip {i + 1}/{total}: rendering…",
        )
        clip_info = probe(work_clip)
        out_name = f"{i + 1:02d}_{base_name}.mp4"
        out_path = out_dir / out_name
        render_clip(
            req,
            work_clip,
            src_w=clip_info.width or info.width,
            src_h=clip_info.height or info.height,
            start=0.0,
            end=clip_info.duration,
            cues=cues,
            out_path=out_path,
        )

        job.clips.append(
            ClipInfo(
                index=i + 1,
                filename=out_name,
                title=f"Clip {i + 1} — {moment.reason}",
                start=round(moment.start, 2),
                end=round(moment.end, 2),
                score=round(moment.score, 3),
                duration=round(clip_info.duration, 2),
            )
        )
        store.update(job, progress=frac_end)

    # Clean up temp working files.
    for f in tmp_dir.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    store.update(
        job,
        state=JobState.DONE,
        progress=1.0,
        message=f"Done. {len(job.clips)} clips ready.",
    )


def _cut_segment(source: str, start: float, end: float, out_path: Path) -> None:
    """Fast, accurate cut of [start, end] re-encoding for frame accuracy."""
    from .ffmpeg_utils import run

    duration = max(0.1, end - start)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        source,
        "-t",
        f"{duration:.3f}",
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
    run(cmd)


def _run_commentary(store: JobStore, job: Job) -> None:
    """Commentary mode: AI voiceover + random gameplay background + subtitles.

    Progress budget:
      pick background   0.00 -> 0.10
      TTS voiceover     0.10 -> 0.45
      transcribe        0.45 -> 0.75
      render            0.75 -> 1.00
    """
    req = job.commentary

    # ---- Pick a background from the library -------------------------------
    store.update(job, state=JobState.ANALYZING, progress=0.02,
                 message="Picking gameplay background…")
    item = library.pick(req.background_id)
    if item is None:
        raise RuntimeError(
            "Your media library is empty. Upload at least one gameplay video first."
        )
    bg_path = library.path_for(item.id)
    if bg_path is None:
        raise RuntimeError("The selected background video file is missing.")
    job.video_title = f"Commentary · bg: {item.name}"
    store.update(job, progress=0.10, message=f"Background: {item.name}")

    out_dir = config.COMMENTARY_DIR / job.id
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Parse highlight marks: *yellow* / **red** -----------------------
    clean_script, red_words, yellow_words = parse_marked_script(req.script)

    # ---- Text-to-speech ---------------------------------------------------
    store.update(job, state=JobState.SYNTHESIZING, progress=0.15,
                 message="Generating AI voiceover…")
    voice_path = synthesize(clean_script, out_dir / "voice", voice=req.voice)
    vinfo = probe(str(voice_path))
    voice_duration = vinfo.duration
    if voice_duration <= 0:
        raise RuntimeError("Voiceover audio has zero duration.")
    store.update(job, progress=0.45,
                 message=f"Voiceover ready ({voice_duration:.1f}s).")

    # ---- Subtitles synced to the voiceover --------------------------------
    cues = []
    if req.subtitles:
        store.update(job, state=JobState.TRANSCRIBING, progress=0.55,
                     message="Syncing subtitles to the voiceover…")
        try:
            cues = transcribe_file(
                str(voice_path),
                translate=False,
                red_keywords=red_words,
                yellow_keywords=yellow_words,
            )
        except Exception as exc:  # noqa: BLE001 - captions are best-effort
            store.update(job, message=f"Subtitles skipped ({exc})")
            cues = []
    store.update(job, progress=0.75)

    # ---- Render -----------------------------------------------------------
    store.update(job, state=JobState.RENDERING, progress=0.80,
                 message="Rendering commentary reel…")
    base = _safe_name(req.script.split("\n", 1)[0] or "commentary")
    out_name = f"commentary_{base}.mp4"
    out_path = out_dir / out_name
    render_commentary(
        background=str(bg_path),
        voiceover=str(voice_path),
        voice_duration=voice_duration,
        cues=cues,
        out_path=out_path,
        subtitle_position=req.subtitle_position,
        subtitles=req.subtitles,
    )

    final = probe(str(out_path))
    job.clips.append(
        ClipInfo(
            index=1,
            filename=out_name,
            title=f"Commentary over {item.name}",
            start=0.0,
            end=round(final.duration, 2),
            score=0.0,
            duration=round(final.duration, 2),
        )
    )

    # Clean up the intermediate voice file.
    try:
        voice_path.unlink()
    except OSError:
        pass

    store.update(job, state=JobState.DONE, progress=1.0,
                 message="Done. Commentary reel ready.")
