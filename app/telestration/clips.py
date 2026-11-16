"""Clips copied into a project for the analyst editor, and their saved drawings.

Preview clips live in scratch folders the engine prunes, so pressing Annotate
first copies the clip into the project:

    projects/<project>/clips/<clip>.mp4        the video
    projects/<project>/clips/<clip>.json       its facts (fps, size, frames...)
    projects/<project>/annotations/<clip>.json the drawings

Every write is atomic. Ids are checked against strict patterns, so no request
can name a path outside the project folder.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import annotations

PROJECT_ID = re.compile(r"^[a-zA-Z0-9_-]{1,160}$")
CLIP_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_CLIP_BYTES = 4 * 1024 ** 3  # a clip, not a match; refuse anything bigger


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="saving-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def probe_video(path: Path, ffmpeg: str) -> dict[str, Any]:
    """Frame rate, size and length read from FFmpeg's description of the file."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, errors="replace", timeout=30, creationflags=flags)
    text = result.stderr
    duration = re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", text)
    video = re.search(r"Stream #\S+.*?Video: .*?, (\d{2,5})x(\d{2,5})[ ,\[].*?(\d+(?:\.\d+)?) fps", text)
    if not duration or not video:
        raise ValueError("This clip could not be read as a video.")
    seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
    width, height, fps = int(video[1]), int(video[2]), float(video[3])
    if seconds <= 0 or not 1 <= fps <= 240:
        raise ValueError("This clip has no usable frames.")
    return {"fps": round(fps, 3), "width": width, "height": height, "duration": round(seconds, 3),
            "frames": max(1, int(round(seconds * fps)))}


class EditorClips:
    def __init__(self, data_dir: Path, ffmpeg: Callable[[], str]) -> None:
        self.data_dir = data_dir
        self.ffmpeg = ffmpeg

    def _project_dir(self, project_id: str) -> Path:
        if not PROJECT_ID.match(project_id or ""):
            raise ValueError("Invalid project id.")
        folder = self.data_dir / "projects" / project_id
        if not (folder / "project.json").is_file():
            raise ValueError("Save the project before annotating its clips.")
        return folder

    def _clip_paths(self, project_id: str, clip_id: str) -> tuple[Path, Path, Path]:
        folder = self._project_dir(project_id)
        if not CLIP_ID.match(clip_id or ""):
            raise ValueError("Invalid clip id.")
        return (folder / "clips" / f"{clip_id}.mp4", folder / "clips" / f"{clip_id}.json",
                folder / "annotations" / f"{clip_id}.json")

    def import_clip(self, project_id: str, source: Path, name: str) -> dict[str, Any]:
        """Copy `source` into the project and describe it."""
        folder = self._project_dir(project_id)
        if not source.is_file():
            raise ValueError("That clip is no longer available. Watch it again, then annotate it.")
        size = source.stat().st_size
        if not 0 < size <= MAX_CLIP_BYTES:
            raise ValueError("That clip is empty or too large to annotate.")
        info = probe_video(source, self.ffmpeg())
        clip_id = uuid.uuid4().hex
        video, meta, _ = self._clip_paths(project_id, clip_id)
        video.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=video.parent, prefix="saving-", suffix=".tmp")
        os.close(fd)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, video)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        stat = video.stat()
        clean_name = re.sub(r"\.mp4$", "", str(name or ""), flags=re.IGNORECASE).strip()[:120] or "Clip"
        record = {"id": clip_id, "project_id": folder.name, "name": clean_name,
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "size": stat.st_size, "mtime": int(stat.st_mtime), **info}
        _atomic_json(meta, record)
        return record

    def get(self, project_id: str, clip_id: str) -> tuple[dict[str, Any], Path]:
        video, meta, _ = self._clip_paths(project_id, clip_id)
        if not video.is_file() or not meta.is_file():
            raise LookupError("This clip is not in the project any more.")
        record = json.loads(meta.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("id") != clip_id:
            raise ValueError("This clip's saved details are damaged.")
        return record, video

    def changed(self, record: dict[str, Any], video: Path) -> bool:
        """True when the video on disk is not the one the drawings were made on."""
        stat = video.stat()
        return stat.st_size != record.get("size") or int(stat.st_mtime) != record.get("mtime")

    def load_annotations(self, project_id: str, clip_id: str) -> dict[str, Any]:
        record, _ = self.get(project_id, clip_id)
        _, _, path = self._clip_paths(project_id, clip_id)
        if not path.is_file():
            return annotations.empty_document()
        saved = json.loads(path.read_text(encoding="utf-8"))
        # Re-check what was stored, so a damaged file is reported, not drawn.
        return annotations.clean_document(saved, record["duration"])

    def save_annotations(self, project_id: str, clip_id: str, document: Any) -> dict[str, Any]:
        record, _ = self.get(project_id, clip_id)
        clean = annotations.clean_document(document, record["duration"])
        _, _, path = self._clip_paths(project_id, clip_id)
        _atomic_json(path, clean)
        return clean
