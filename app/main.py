"""FastAPI app: serves the UI and the clipping API, runs the local server."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, library
from .jobs import JobStore
from .models import (
    ClipRequest,
    CommentaryRequest,
    Job,
    JobKind,
    JobStatus,
    LibraryItem,
)
from .pipeline import run_job

config.ensure_dirs()

app = FastAPI(title="Viral Clipper", version="2.0")
store = JobStore(runner=run_job)


# ---- Clip mode -------------------------------------------------------------
@app.post("/api/jobs", response_model=JobStatus)
def create_job(req: ClipRequest) -> JobStatus:
    if not req.url.strip() and not req.upload_id.strip():
        raise HTTPException(
            status_code=400, detail="Provide a video URL or upload a file."
        )
    if req.upload_id.strip() and not _upload_path(req.upload_id).exists():
        raise HTTPException(status_code=400, detail="Uploaded file not found.")
    job = store.create(Job(id=_new_id(), request=req, kind=JobKind.CLIP))
    return job.to_status()


_UPLOAD_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _upload_path(upload_id: str) -> Path:
    # upload_id is "<hex>.<ext>"; guard against traversal.
    safe = Path(upload_id).name
    return config.DOWNLOAD_DIR / safe


@app.post("/api/upload")
async def upload_source(file: UploadFile = File(...)) -> dict:
    """Store a user-uploaded video for clipping; returns an upload_id."""
    import uuid

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _UPLOAD_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported type {suffix!r}. Allowed: "
            + ", ".join(sorted(_UPLOAD_EXT)),
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    config.ensure_dirs()
    upload_id = f"up_{uuid.uuid4().hex[:12]}{suffix}"
    (config.DOWNLOAD_DIR / upload_id).write_bytes(data)
    return {"upload_id": upload_id, "name": file.filename}


# ---- Commentary mode -------------------------------------------------------
@app.post("/api/commentary", response_model=JobStatus)
def create_commentary(req: CommentaryRequest) -> JobStatus:
    if not req.script.strip():
        raise HTTPException(status_code=400, detail="A script is required.")
    if not library.list_items():
        raise HTTPException(
            status_code=400,
            detail="Media library is empty. Upload a gameplay video first.",
        )
    job = store.create(Job(id=_new_id(), commentary=req, kind=JobKind.COMMENTARY))
    return job.to_status()


# ---- Media library ---------------------------------------------------------
@app.get("/api/library", response_model=list[LibraryItem])
def get_library() -> list[LibraryItem]:
    return library.list_items()


@app.post("/api/library", response_model=LibraryItem)
async def upload_library(file: UploadFile = File(...)) -> LibraryItem:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    try:
        return library.add(file.filename or "video.mp4", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/library/{item_id}")
def delete_library(item_id: str) -> dict:
    ok = library.delete(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"deleted": item_id}


@app.get("/api/library/{item_id}/video")
def library_video(item_id: str):
    path = library.path_for(item_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    return FileResponse(str(path), media_type="video/mp4")


# ---- Shared ----------------------------------------------------------------
@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.to_status()


@app.get("/api/clips/{job_id}/{filename}")
def get_clip(job_id: str, filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    # A job output lives in either the clips dir or the commentary dir.
    for base in (config.CLIPS_DIR, config.COMMENTARY_DIR):
        path = base / job_id / filename
        if path.exists():
            return FileResponse(str(path), media_type="video/mp4", filename=filename)
    raise HTTPException(status_code=404, detail="Clip not found.")


def _new_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


# Serve the frontend. API routes are registered above so they take priority.
app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")


def main() -> None:
    import uvicorn

    print(f"Viral Clipper running at http://{config.HOST}:{config.PORT}")
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
