"""Media library for gameplay background videos (Commentary mode).

Videos are stored under config.LIBRARY_DIR with a JSON index describing each
item. The commentary pipeline picks one (random or chosen) as the background.
"""
from __future__ import annotations

import json
import random
import threading
import uuid
from pathlib import Path
from typing import Optional

from . import config
from .ffmpeg_utils import probe
from .models import LibraryItem

_INDEX = config.LIBRARY_DIR / "index.json"
_lock = threading.Lock()
_ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _load() -> list[dict]:
    if not _INDEX.exists():
        return []
    try:
        return json.loads(_INDEX.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(items: list[dict]) -> None:
    _INDEX.write_text(json.dumps(items, indent=2), encoding="utf-8")


def list_items() -> list[LibraryItem]:
    return [LibraryItem(**it) for it in _load()]


def add(original_name: str, data: bytes) -> LibraryItem:
    """Store an uploaded gameplay video and index it."""
    config.ensure_dirs()
    suffix = Path(original_name).suffix.lower()
    if suffix not in _ALLOWED:
        raise ValueError(
            f"Unsupported file type {suffix!r}. Allowed: {', '.join(sorted(_ALLOWED))}"
        )

    item_id = uuid.uuid4().hex[:12]
    filename = f"{item_id}{suffix}"
    path = config.LIBRARY_DIR / filename
    path.write_bytes(data)

    try:
        info = probe(str(path))
        duration, width, height = info.duration, info.width, info.height
    except Exception:  # noqa: BLE001 - index even if probe fails
        duration, width, height = 0.0, 0, 0

    item = LibraryItem(
        id=item_id,
        filename=filename,
        name=Path(original_name).stem or filename,
        duration=round(duration, 2),
        width=width,
        height=height,
    )
    with _lock:
        items = _load()
        items.append(item.model_dump())
        _save(items)
    return item


def get(item_id: str) -> Optional[LibraryItem]:
    for it in _load():
        if it["id"] == item_id:
            return LibraryItem(**it)
    return None


def path_for(item_id: str) -> Optional[Path]:
    it = get(item_id)
    if it is None:
        return None
    p = config.LIBRARY_DIR / it.filename
    return p if p.exists() else None


def pick(background_id: str = "") -> Optional[LibraryItem]:
    """Return a specific item by id, or a random one if id is empty."""
    items = list_items()
    if not items:
        return None
    if background_id:
        return get(background_id)
    return random.choice(items)


def delete(item_id: str) -> bool:
    with _lock:
        items = _load()
        remaining = [it for it in items if it["id"] != item_id]
        if len(remaining) == len(items):
            return False
        removed = next(it for it in items if it["id"] == item_id)
        _save(remaining)
    p = config.LIBRARY_DIR / removed["filename"]
    try:
        p.unlink()
    except OSError:
        pass
    return True
