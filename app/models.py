"""Pydantic request/response models and internal job data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from . import config


class CamRegion(BaseModel):
    """Fractional crop box for the streamer cam, relative to source video size.

    Values are fractions in [0, 1]. Example: a 16:9 webcam overlay sitting in
    the top-left quarter might be x=0.0, y=0.0, w=0.33, h=0.33.
    """

    x: float = Field(0.0, ge=0.0, le=1.0)
    y: float = Field(0.0, ge=0.0, le=1.0)
    w: float = Field(1.0, gt=0.0, le=1.0)
    h: float = Field(0.5, gt=0.0, le=1.0)


class GameRegion(BaseModel):
    """Fractional crop box for the gameplay (bottom) section."""

    x: float = Field(0.0, ge=0.0, le=1.0)
    y: float = Field(0.0, ge=0.0, le=1.0)
    w: float = Field(1.0, gt=0.0, le=1.0)
    h: float = Field(1.0, gt=0.0, le=1.0)


class SubtitleStyle(str, Enum):
    """Caption presentation styles, inspired by OpusClip's picker.

    - KARAOKE:   full line visible, the spoken word pops/colors in real time.
    - WORD_CUT:  only the current word is on screen (one word at a time).
    - HIGHLIGHT: full line, the spoken word gets a filled highlight box.
    """

    KARAOKE = "karaoke"
    WORD_CUT = "word_cut"
    HIGHLIGHT = "highlight"


class ClipRequest(BaseModel):
    """Payload to start a clipping job."""

    # Either `url` (download) or `upload_id` (a previously uploaded file) is set.
    url: str = ""
    upload_id: str = ""
    num_clips: int = Field(10, ge=1, le=30)
    min_seconds: int = Field(config.MIN_CLIP_SECONDS, ge=5, le=120)
    max_seconds: int = Field(config.MAX_CLIP_SECONDS, ge=10, le=180)
    # Fraction of output height given to the cam (top). Rest is gameplay.
    cam_height_fraction: float = Field(0.4, ge=0.1, le=0.9)
    cam_region: CamRegion = Field(default_factory=CamRegion)
    game_region: GameRegion = Field(default_factory=GameRegion)
    subtitles: bool = True
    subtitle_style: SubtitleStyle = SubtitleStyle.KARAOKE
    trim_silence: bool = True
    # Auto-Hook: show a big headline over the first seconds of each clip.
    hook: bool = False
    hook_text: str = ""  # empty -> auto-generated from the clip's first words
    # One-tap color grade (saturation/contrast bump) like OpusClip's option.
    color_correction: bool = False


class JobKind(str, Enum):
    CLIP = "clip"
    COMMENTARY = "commentary"


class JobState(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"  # commentary: TTS voiceover
    TRANSCRIBING = "transcribing"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"


class CommentaryRequest(BaseModel):
    """Payload to start a commentary job.

    A random (or chosen) gameplay video from the library plays in the
    background while the script is read by an AI voice, with synced subtitles.
    """

    script: str = Field(..., min_length=1)
    # Optional: pick a specific library video by id. Empty -> random.
    background_id: str = ""
    voice: str = ""  # provider-specific voice override; empty -> config default
    subtitles: bool = True
    # Where captions sit vertically (fraction from top). 0.5 = middle.
    subtitle_position: float = Field(0.5, ge=0.1, le=0.9)


class LibraryItem(BaseModel):
    """A gameplay background video stored in the media library."""

    id: str
    filename: str
    name: str
    duration: float = 0.0
    width: int = 0
    height: int = 0


class ClipInfo(BaseModel):
    """A single produced clip."""

    index: int
    filename: str
    title: str
    start: float
    end: float
    score: float
    duration: float


class JobStatus(BaseModel):
    """Public job status returned to the frontend."""

    id: str
    state: JobState
    progress: float = 0.0  # 0..1
    message: str = ""
    error: Optional[str] = None
    video_title: Optional[str] = None
    clips: list[ClipInfo] = Field(default_factory=list)


@dataclass
class Moment:
    """A scored candidate moment found during analysis."""

    start: float
    end: float
    score: float
    reason: str = ""


@dataclass
class Job:
    """Internal mutable job record held in the job store.

    Either `request` (clip mode) or `commentary` (commentary mode) is set,
    selected by `kind`.
    """

    id: str
    request: Optional[ClipRequest] = None
    commentary: Optional["CommentaryRequest"] = None
    kind: JobKind = JobKind.CLIP
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    video_title: Optional[str] = None
    source_path: Optional[str] = None
    duration: float = 0.0
    width: int = 0
    height: int = 0
    clips: list[ClipInfo] = field(default_factory=list)

    def to_status(self) -> JobStatus:
        return JobStatus(
            id=self.id,
            state=self.state,
            progress=round(self.progress, 3),
            message=self.message,
            error=self.error,
            video_title=self.video_title,
            clips=list(self.clips),
        )
