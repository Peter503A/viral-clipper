"""Render a 9:16 split-screen clip with burned-in subtitles.

Layout (matches the reference short):

    +-----------------------+   <- OUT_WIDTH x OUT_HEIGHT (1080x1920)
    |      CAM (top)        |   streamer webcam, cropped from source
    |                       |
    +-----------------------+
    |    *SUBTITLES* here   |   centered caption band
    +-----------------------+
    |                       |
    |    GAMEPLAY (bottom)  |   gameplay, cropped from source
    |                       |
    +-----------------------+

Subtitles are written to an ASS file (styled like a viral short: bold white
text, black outline + translucent box, centered) and burned in with ffmpeg.
No watermark is ever added.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .ffmpeg_utils import run
from .models import CamRegion, GameRegion, ClipRequest
from .transcribe import Cue, Word

# ASS colors are &HAABBGGRR (alpha, blue, green, red). Alpha 00 = opaque.
_WHITE = "&H00FFFFFF"
_YELLOW = "&H0000D7FF"  # bright yellow/gold
_RED = "&H003B30FF"     # punchy red
_ACTIVE = "&H0000FFFF"  # the word being spoken right now (yellow pop)

_HILITE_COLOR = {"yellow": _YELLOW, "red": _RED}


def _crop_expr(region, src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """Convert a fractional region to integer crop (w, h, x, y) in pixels."""
    w = max(2, int(round(region.w * src_w)))
    h = max(2, int(round(region.h * src_h)))
    x = max(0, min(src_w - w, int(round(region.x * src_w))))
    y = max(0, min(src_h - h, int(round(region.y * src_h))))
    # ffmpeg likes even dimensions for yuv420p.
    w -= w % 2
    h -= h % 2
    return w, h, x, y


def build_filter(
    req: ClipRequest, src_w: int, src_h: int
) -> str:
    """Build the ffmpeg filter_complex for the split-screen composition."""
    out_w, out_h = config.OUT_WIDTH, config.OUT_HEIGHT
    cam_h = int(round(out_h * req.cam_height_fraction))
    cam_h -= cam_h % 2
    game_h = out_h - cam_h

    cw, ch, cx, cy = _crop_expr(req.cam_region, src_w, src_h)
    gw, gh, gx, gy = _crop_expr(req.game_region, src_w, src_h)

    # Cam: crop the cam region, scale to fill the top band (cover + center-crop).
    cam = (
        f"[0:v]crop={cw}:{ch}:{cx}:{cy},"
        f"scale={out_w}:{cam_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{cam_h}[cam]"
    )
    # Gameplay: same treatment for the bottom band.
    game = (
        f"[0:v]crop={gw}:{gh}:{gx}:{gy},"
        f"scale={out_w}:{game_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{game_h}[game]"
    )
    # Stack cam over gameplay.
    stack = "[cam][game]vstack=inputs=2[v]"
    return ";".join([cam, game, stack])


def _ass_time(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        cs = 99
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def write_ass(cues: list[Cue], path: Path, cam_fraction: float, style: str = "karaoke") -> None:
    """Write viral-style captions sitting just below the cam/gameplay seam."""
    out_h = config.OUT_HEIGHT
    seam_y = int(out_h * cam_fraction)
    margin_v = max(40, out_h - seam_y - 90)
    _write_ass(cues, path, margin_v, style)


def write_ass_at(
    cues: list[Cue], path: Path, position_fraction: float, style: str = "karaoke"
) -> None:
    """Write captions centered at `position_fraction` of the height (0..1)."""
    out_h = config.OUT_HEIGHT
    # Alignment 2 = bottom-centered, so margin_v is distance from the bottom.
    margin_v = max(40, int(out_h * (1.0 - position_fraction)) - 50)
    _write_ass(cues, path, margin_v, style)


def _color_for(word: Word, active: bool) -> str:
    """Pick the display color for a word in a given karaoke frame."""
    if active:
        # The word being spoken right now pops. If it is a keyword, keep its
        # red; otherwise flash the active-yellow.
        return _RED if word.highlight == "red" else _ACTIVE
    return _HILITE_COLOR.get(word.highlight, _WHITE)


def _render_cue_text(words: list[Word], active_index: int, style: str) -> str:
    """Build one ASS line for a word window, honoring the chosen style.

    - "word_cut":  only the active word is shown (one word at a time).
    - "highlight": full line, active word sits in a filled highlight box.
    - "karaoke":   full line, active word colored + scaled (default).
    """
    if style == "word_cut":
        w = words[active_index]
        color = _RED if w.highlight == "red" else _ACTIVE
        return f"{{\\c{color}\\fscx120\\fscy120}}{_escape_ass(w.text)}{{\\r}}"

    parts = []
    for i, w in enumerate(words):
        active = i == active_index
        color = _color_for(w, active)
        token = _escape_ass(w.text)
        if active and style == "highlight":
            # Filled box behind the spoken word (BorderStyle 3 via override).
            parts.append(
                f"{{\\c&H00000000&\\4c{color}\\bord0\\shad0\\3c{color}"
                f"\\fscx112\\fscy112}}{token}{{\\r}}"
            )
        elif active:
            parts.append(f"{{\\c{color}\\fscx118\\fscy118}}{token}{{\\r}}")
        else:
            parts.append(f"{{\\c{color}}}{token}{{\\r}}")
    return " ".join(parts)


def _karaoke_lines(cue: Cue, style: str = "karaoke") -> list[tuple[float, float, str]]:
    """Split a cue into per-word time windows, each a fully styled line.

    Returns (start, end, ass_text) tuples. During each window exactly one word
    is the "active" (spoken-now) word, so captions track speech in real time.
    """
    words = cue.words
    if not words:
        return [(cue.start, cue.end, _escape_ass(cue.text))]

    lines: list[tuple[float, float, str]] = []
    n = len(words)
    for i, w in enumerate(words):
        seg_start = w.start
        # Hold until the next word starts so there is no flicker gap.
        seg_end = words[i + 1].start if i + 1 < n else cue.end
        if seg_end <= seg_start:
            seg_end = seg_start + 0.05
        lines.append((seg_start, seg_end, _render_cue_text(words, i, style)))
    return lines


def _write_ass(cues: list[Cue], path: Path, margin_v: int, style: str = "karaoke") -> None:
    """Write a word-synced ASS caption file in the requested style."""
    out_w, out_h = config.OUT_WIDTH, config.OUT_HEIGHT
    font_size = int(out_w * 0.078)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {out_w}
PlayResY: {out_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Viral,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,1,5,2,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for cue in cues:
        for seg_start, seg_end, text in _karaoke_lines(cue, style):
            lines.append(
                f"Dialogue: 0,{_ass_time(seg_start)},{_ass_time(seg_end)},"
                f"Viral,,0,0,0,,{text}\n"
            )
    path.write_text("".join(lines), encoding="utf-8")


def render_clip(
    req: ClipRequest,
    source: str,
    src_w: int,
    src_h: int,
    start: float,
    end: float,
    cues: list[Cue],
    out_path: Path,
) -> None:
    """Cut [start, end], compose the split-screen, burn subtitles, write mp4."""
    duration = max(0.1, end - start)
    vf = build_filter(req, src_w, src_h)
    label = "[v]"

    # Optional one-tap color grade: lift saturation/contrast a touch.
    if getattr(req, "color_correction", False):
        vf += f";{label}eq=contrast=1.08:saturation=1.22:brightness=0.02[vcc]"
        label = "[vcc]"

    ass_path = out_path.with_suffix(".ass")
    hook_path = out_path.with_suffix(".hook.ass")
    style = getattr(req, "subtitle_style", None)
    style = style.value if hasattr(style, "value") else (style or "karaoke")

    if req.subtitles and cues:
        write_ass(cues, ass_path, req.cam_height_fraction, style)
        ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:")
        vf += f";{label}subtitles='{ass_arg}'[vsub]"
        label = "[vsub]"

    # Optional Auto-Hook: a big headline over the first ~2.5s of the clip.
    if getattr(req, "hook", False):
        text = (req.hook_text or _auto_hook_text(cues)).strip()
        if text:
            write_hook_ass(text, hook_path, end - start)
            hook_arg = str(hook_path).replace("\\", "/").replace(":", "\\:")
            vf += f";{label}subtitles='{hook_arg}'[vhook]"
            label = "[vhook]"

    final_label = label

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        source,
        "-filter_complex",
        vf,
        "-map",
        final_label,
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    run(cmd)

    for p in (ass_path, hook_path):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def _auto_hook_text(cues: list[Cue], max_words: int = 6) -> str:
    """Build a short headline from the clip's first spoken words."""
    words: list[str] = []
    for cue in cues:
        for w in cue.words:
            words.append(w.text)
            if len(words) >= max_words:
                break
        if len(words) >= max_words:
            break
    return " ".join(words)


def write_hook_ass(text: str, path: Path, clip_duration: float, seconds: float = 2.5) -> None:
    """Write a big centered headline shown over the first `seconds` of a clip."""
    out_w, out_h = config.OUT_WIDTH, config.OUT_HEIGHT
    font_size = int(out_w * 0.11)
    # Place it in the upper third so it does not clash with captions.
    margin_v = int(out_h * 0.62)
    end = _ass_time(min(seconds, max(0.5, clip_duration)))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {out_w}
PlayResY: {out_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Arial,{font_size},&H0000D7FF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,7,3,8,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,{end},Hook,,0,0,0,,{_escape_ass(text.upper())}
"""
    path.write_text(header, encoding="utf-8")


def render_commentary(
    background: str,
    voiceover: str,
    voice_duration: float,
    cues: list[Cue],
    out_path: Path,
    subtitle_position: float = 0.5,
    subtitles: bool = True,
) -> None:
    """Render a commentary reel.

    The gameplay `background` fills a 9:16 frame (scaled to cover + center
    crop). Its own audio is dropped; the `voiceover` becomes the audio track.
    The output length matches the voiceover. If the background is shorter than
    the voiceover it loops. Captions (from the voiceover transcript) are burned
    in near `subtitle_position`.
    """
    out_w, out_h = config.OUT_WIDTH, config.OUT_HEIGHT
    duration = max(0.5, voice_duration)

    # Cover-fit the gameplay into vertical frame, then trim to voice length.
    vf = (
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},setsar=1,"
        f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v]"
    )

    ass_path = out_path.with_suffix(".ass")
    final_label = "[v]"
    if subtitles and cues:
        write_ass_at(cues, ass_path, subtitle_position)
        ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:")
        vf = vf + f";[v]subtitles='{ass_arg}'[vout]"
        final_label = "[vout]"

    cmd = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",  # loop the background if it is shorter than the voiceover
        "-i",
        background,
        "-i",
        voiceover,
        "-filter_complex",
        vf,
        "-map",
        final_label,
        "-map",
        "1:a:0",
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    run(cmd)

    if ass_path.exists():
        try:
            ass_path.unlink()
        except OSError:
            pass
