# Viral Clipper

A local web app with **two modes**, chosen from the menu at the top:

### 1. 🎬 AI Clipping (auto-clip from a URL)
Turns a YouTube video (or stream VOD) into ~10 short vertical clips
(9:16, Reels/Shorts), Opus-Clip style:

- **Split-screen layout**: streamer cam on top, gameplay on the bottom.
- **Real-time word-by-word subtitles** (karaoke style, like TikTok/Reels):
  each word pops the moment it is spoken, with attention words in
  **yellow/red**.
- **Lively editing**: long silences / dead air are trimmed automatically.
- **No watermark** — clips are rendered clean.

The "find the viral moments" part uses a **heuristic** (audio loudness peaks +
speech activity + scene changes). It finds the loud, dense, high-action
moments that tend to perform well, and ranks them.

### 2. 🎙️ Commentary (voiceover over gameplay)
Build a reel where **gameplay plays in the background** and an **AI voice**
reads your script, with synced subtitles:

- Upload GTA 6 (or any) gameplay to a **media library**.
- One clip is picked **at random** (or you choose a specific one) as background.
- Paste a **script** (facts, bugs, viral takes). It is read by an AI voice.
- **Subtitles track the voice word-by-word in real time** (karaoke style).
  Mark words to highlight them: `*word*` = yellow, `**word**` = red. The
  asterisks are stripped before the voice reads the script, and numbers /
  punchy words are auto-highlighted.
- Output is a 9:16 reel, no watermark.

---

## How it works (pipeline)

```
YouTube URL
   │  yt-dlp
   ▼
Downloaded video + audio
   │  analysis (loudness, speech, scene cuts)
   ▼
Scored candidate moments  ──►  pick top ~10
   │  faster-whisper (per clip)
   ▼
English transcript + word timings
   │  ffmpeg
   ▼
9:16 split-screen clip  +  burned subtitles  +  silence trimmed
   ▼
MP4 files you can download (no watermark)
```

---

## Requirements (install once on your machine)

1. **Python 3.10+**
2. **FFmpeg** (must be on your PATH)
   - macOS: `brew install ffmpeg`
   - Ubuntu/Debian: `sudo apt install ffmpeg`
   - Windows: `winget install Gyan.FFmpeg` (or download from ffmpeg.org)
3. Python packages (installed by the setup step below).

> `yt-dlp` is installed as a Python package, so you do **not** need it
> separately.

### Voice (Commentary mode only)

The AI voice is a **swappable backend**. Pick one via the
`CLIPPER_TTS_PROVIDER` environment variable:

| Provider | Setup | Cost |
|---|---|---|
| `openai` (default) | `export OPENAI_API_KEY=sk-...`  · `pip install openai` | paid API |
| `elevenlabs` | `export ELEVENLABS_API_KEY=...` and `export CLIPPER_ELEVENLABS_VOICE_ID=...` | paid API |
| `piper` | free & local — [download a `.onnx` voice](https://github.com/rhasspy/piper), install the `piper` binary, then `export CLIPPER_PIPER_MODEL=/path/to/voice.onnx` | free |

Example (OpenAI, the default):

```bash
export OPENAI_API_KEY=sk-your-key
# optional: export CLIPPER_OPENAI_TTS_VOICE=onyx   (nova / shimmer / echo / ...)
```

Example (free, local Piper):

```bash
export CLIPPER_TTS_PROVIDER=piper
export CLIPPER_PIPER_MODEL=/path/to/en_US-amy-medium.onnx
```

> AI Clipping mode needs **no** API key — only Commentary mode uses TTS.

---

## Setup

```bash
cd clipper
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
```

The first run downloads a Whisper model (a few hundred MB). This happens once.

---

## Run

```bash
python -m app.main
# then open http://127.0.0.1:8000
```

In the browser, pick a mode at the top:

**AI Clipping**
1. Paste a YouTube URL **or upload a video file**.
2. Adjust the **cam region** (the box on top is the streamer's webcam area)
   and how many clips you want.
3. In the **Recipe** section pick a subtitle style (Karaoke / Word Cut /
   Highlight) and optionally turn on **Auto-Hook** (a big headline over the
   first seconds) and **Color correction** (a one-tap saturation/contrast
   boost).
4. Click **Analyze & Clip**.
5. Watch the progress. When done, preview and **Download** each clip.

**Commentary**
1. Click **Add gameplay video** and upload one or more GTA 6 gameplay clips.
2. Choose a background (or leave it on 🎲 Random).
3. Paste your script (facts / bugs / viral takes).
4. Click **Generate Commentary Reel**, then **Download** the result.

---

## Notes & limits

- Cam detection is **manual** for now: you set the crop box for the top
  (cam) section. Auto-detection can be added later.
- Processing a long video is CPU/time heavy. A GPU + the `large` Whisper model
  gives better subtitles but is slower to set up. Defaults use a small model
  so it runs on any laptop.
- Only download content you have the right to use.

---

## Project layout

```
clipper/
  app/
    main.py          # FastAPI app + server entry, routes for both modes
    config.py        # settings / paths / TTS config
    models.py        # request/response + job data models
    jobs.py          # in-memory job store + single worker
    pipeline.py      # orchestrates clip AND commentary pipelines
    download.py      # yt-dlp wrapper              (clip mode)
    analyze.py       # heuristic viral-moment detection (clip mode)
    trim.py          # silence/dead-air trimming   (clip mode)
    transcribe.py    # faster-whisper -> word-timed subtitles (both modes)
    tts.py           # swappable AI voice backends (commentary mode)
    library.py       # gameplay media library      (commentary mode)
    render.py        # ffmpeg: split-screen / commentary + subtitles
    ffmpeg_utils.py  # ffprobe / ffmpeg helpers
  web/
    index.html       # single-page UI with the mode menu
    app.js
    styles.css
  requirements.txt
```
