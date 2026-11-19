"""Transcribe a clip's audio to word-timed English subtitles via faster-whisper.

We translate to English (task="translate") so clips always have English
captions regardless of the source language, matching the viral-short style.
Output is a list of short caption cues (a few words each) with start/end times
relative to the clip, which the renderer burns in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from . import config


@dataclass
class Word:
    """One spoken word with its own timing and an optional highlight color."""

    text: str
    start: float
    end: float
    # "" = normal (white), "yellow" or "red" = attention highlight.
    highlight: str = ""


@dataclass
class Cue:
    """A short caption line. `words` carries per-word timings for karaoke.

    `text` stays for backward compatibility and simple fallbacks; it is the
    joined words.
    """

    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@lru_cache(maxsize=1)
def _load_model():
    from faster_whisper import WhisperModel

    # int8 keeps it light on CPU; auto-detects GPU if available via "cuda".
    return WhisperModel(config.WHISPER_MODEL, device="auto", compute_type="int8")


def transcribe_clip(path: str, max_words_per_cue: int = 4) -> list[Cue]:
    """Short English caption cues for a clip (always translated to English)."""
    return transcribe_file(path, max_words_per_cue=max_words_per_cue, translate=True)


def transcribe_file(
    path: str,
    max_words_per_cue: int = 4,
    translate: bool = True,
    red_keywords: set[str] | None = None,
    yellow_keywords: set[str] | None = None,
) -> list[Cue]:
    """Return short, word-grouped caption cues for a media file.

    translate=True forces English output (used for source clips). For the
    commentary voiceover we set translate=False so captions match the spoken
    language of the script. red_keywords / yellow_keywords let the caller force
    specific words to be highlighted (from the user's marked script).
    """
    try:
        model = _load_model()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not load Whisper model: {exc}") from exc

    segments, _info = model.transcribe(
        path,
        task="translate" if translate else "transcribe",
        vad_filter=True,
        word_timestamps=True,
        beam_size=1,
    )

    cues: list[Cue] = []
    word_buffer: list[Word] = []

    def flush() -> None:
        if not word_buffer:
            return
        start = word_buffer[0].start
        end = word_buffer[-1].end
        text = " ".join(w.text for w in word_buffer).strip()
        if text:
            cues.append(
                Cue(start=start, end=end, text=text, words=list(word_buffer))
            )
        word_buffer.clear()

    for seg in segments:
        words = getattr(seg, "words", None)
        if not words:
            # No word timings: fall back to the whole segment as one cue.
            txt = seg.text.strip()
            if txt:
                cues.append(Cue(start=seg.start, end=seg.end, text=txt.upper()))
            continue
        for w in words:
            if w.word is None or w.start is None or w.end is None:
                continue
            token = w.word.strip().upper()
            if not token:
                continue
            word_buffer.append(
                Word(text=token, start=float(w.start), end=float(w.end))
            )
            if len(word_buffer) >= max_words_per_cue:
                flush()
        flush()

    assign_highlights(cues, extra_keywords=red_keywords, yellow_keywords=yellow_keywords)
    return cues


import re

# Words that grab attention in a viral reel -> painted RED (strongest).
_RED_WORDS = {
    "NEVER", "NOBODY", "NOTHING", "EVERYONE", "EVERYTHING", "SECRET",
    "SECRETLY", "HIDDEN", "BANNED", "ILLEGAL", "INSANE", "CRAZY", "SHOCKING",
    "UNBELIEVABLE", "IMPOSSIBLE", "DANGER", "DANGEROUS", "WARNING", "STOP",
    "FIRST", "LAST", "ONLY", "BIGGEST", "WORST", "BEST", "DEAD", "KILLED",
    "BROKEN", "BUG", "GLITCH", "EXPLOIT", "RARE", "LEAKED", "LEAK",
}
# Words worth emphasizing -> painted YELLOW.
_YELLOW_WORDS = {
    "NEW", "HUGE", "MASSIVE", "FREE", "MONEY", "CASH", "WIN", "WON", "LOSE",
    "FAST", "SECONDS", "MINUTES", "MILLION", "BILLION", "GTA", "ROCKSTAR",
    "MAP", "WEAPON", "CAR", "MISSION", "UPDATE", "RELEASE", "TRAILER",
    "ALWAYS", "ACTUALLY", "REALLY", "LITERALLY", "FINALLY", "SECRET",
}
_NUM_RE = re.compile(r"\d")


def _clean(token: str) -> str:
    """Strip surrounding punctuation for matching ("GTA6!" -> "GTA6")."""
    return re.sub(r"[^A-Z0-9]", "", token.upper())


def parse_marked_script(script: str) -> tuple[str, set[str], set[str]]:
    """Pull *yellow* / **red** marks out of a commentary script.

    The user writes `**banned**` for a red word and `*huge*` for a yellow one.
    Returns (clean_script_for_tts, red_words, yellow_words) with the markup
    stripped so the AI voice does not read the asterisks aloud.
    """
    red: set[str] = set()
    yellow: set[str] = set()

    # **red** first (so it is not eaten by the single-star rule).
    def take_red(m: re.Match) -> str:
        phrase = m.group(1)
        for tok in phrase.split():
            c = _clean(tok)
            if c:
                red.add(c)
        return phrase

    def take_yellow(m: re.Match) -> str:
        phrase = m.group(1)
        for tok in phrase.split():
            c = _clean(tok)
            if c:
                yellow.add(c)
        return phrase

    clean = re.sub(r"\*\*(.+?)\*\*", take_red, script)
    clean = re.sub(r"\*(.+?)\*", take_yellow, clean)
    return clean, red, yellow


def assign_highlights(
    cues: list[Cue],
    extra_keywords: set[str] | None = None,
    yellow_keywords: set[str] | None = None,
) -> None:
    """Color attention words yellow/red, in place.

    Heuristic:
      - numbers / money / big quantities              -> yellow
      - punchy "hook" words (never, insane, secret…)  -> red
      - words the caller flagged (extra_keywords)      -> red
      - a cue-ending "!" word                          -> red
    """
    extra = {_clean(k) for k in (extra_keywords or set()) if _clean(k)}
    yellow = {_clean(k) for k in (yellow_keywords or set()) if _clean(k)}
    for cue in cues:
        for w in cue.words:
            token = _clean(w.text)
            if not token:
                continue
            if token in extra or token in _RED_WORDS:
                w.highlight = "red"
            elif token in yellow or token in _YELLOW_WORDS or _NUM_RE.search(token):
                w.highlight = "yellow"
            elif w.text.endswith("!") or w.text.endswith("?"):
                w.highlight = "yellow"
