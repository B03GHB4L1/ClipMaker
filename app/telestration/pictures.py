"""Pictures an analyst puts into an annotated clip (docs/CODING_AND_PITCH_PLAN.md, section I).

    projects/<project>/pictures/<id>.png   the picture, re-encoded here so the file is always a clean PNG
    projects/<project>/pictures/<id>.json  its name, size and when it was added

The browser never names a path: ids are checked against a strict pattern and every file is read
from the project's own pictures folder. Writes are atomic.
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

PICTURE_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_BYTES = 20_000_000
MAX_SIDE = 4096
MAX_PICTURES = 200
FORMATS = {"PNG", "JPEG", "WEBP"}


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="saving-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clean_png(data: bytes) -> tuple[bytes, int, int]:
    """The picture re-encoded as a PNG, with its width and height. Anything that is not a PNG, JPEG or WebP is refused."""
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("A picture must be under 20 MB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in FORMATS:
                raise ValueError("Only PNG, JPEG and WebP pictures can be added.")
            width, height = image.size  # read from the header, before anything is decoded
            if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
                raise ValueError(f"A picture can be at most {MAX_SIDE} pixels on a side.")
            image.load()
            image = ImageOps.exif_transpose(image)
            alpha = "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)
            image = image.convert("RGBA" if alpha else "RGB")
            output = io.BytesIO()
            image.save(output, "PNG")
            return output.getvalue(), image.width, image.height
    except Image.DecompressionBombError:
        raise ValueError(f"A picture can be at most {MAX_SIDE} pixels on a side.") from None
    except (OSError, SyntaxError):
        raise ValueError("That file could not be read as a PNG, JPEG or WebP picture.") from None


def _name(value: Any) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", Path(str(value or "")).name).strip()
    return stem[:80] or "Picture"


def _paths(folder: Path, picture_id: str) -> tuple[Path, Path]:
    if not PICTURE_ID.match(picture_id or ""):
        raise ValueError("Invalid picture id.")
    return folder / f"{picture_id}.png", folder / f"{picture_id}.json"


def add(folder: Path, data: bytes, name: str) -> dict[str, Any]:
    """Save a picture in the project's pictures folder and describe it."""
    png, width, height = clean_png(data)
    if folder.is_dir() and len(list(folder.glob("*.json"))) >= MAX_PICTURES:
        raise ValueError(f"A project can keep up to {MAX_PICTURES} pictures. Delete some you no longer use.")
    picture_id = uuid.uuid4().hex
    image, meta = _paths(folder, picture_id)
    record = {"id": picture_id, "name": _name(name), "width": width, "height": height, "size": len(png),
              "created_at": datetime.now(timezone.utc).isoformat()}
    _atomic(image, png)
    try:
        _atomic(meta, json.dumps(record, indent=2).encode("utf-8"))
    except BaseException:
        image.unlink(missing_ok=True)
        raise
    return record


def listing(folder: Path) -> list[dict[str, Any]]:
    """The project's pictures, newest first. A picture whose file or details are damaged is left out."""
    records = []
    for meta in folder.glob("*.json") if folder.is_dir() else []:
        try:
            record = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(record, dict) and record.get("id") == meta.stem and (folder / f"{meta.stem}.png").is_file():
                records.append(record)
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda record: str(record.get("created_at", "")), reverse=True)


def file_of(folder: Path, picture_id: str) -> Path | None:
    image, meta = _paths(folder, picture_id)
    return image if image.is_file() and meta.is_file() else None


def picture_ids(document: Any) -> set[str]:
    """The pictures an annotation document's inserts show."""
    found = set()
    for freeze in (document.get("freezes") if isinstance(document, dict) else None) or []:
        background = freeze.get("background") if isinstance(freeze, dict) else None
        if isinstance(background, dict) and background.get("kind") == "picture" and isinstance(background.get("id"), str):
            found.add(background["id"])
    return found


def used_by(project: Path, picture_id: str) -> bool:
    """True when an annotated clip of the project has an insert showing this picture."""
    folder = project / "annotations"
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if picture_id in picture_ids(document):
            return True
    return False


def remove(project: Path, picture_id: str) -> None:
    """Delete a picture, unless an insert still shows it."""
    folder = project / "pictures"
    image, meta = _paths(folder, picture_id)
    if not meta.is_file():
        raise LookupError("That picture is not in the project any more.")
    if used_by(project, picture_id):
        raise ValueError("An insert in one of the project's clips shows this picture. Remove the insert first.")
    meta.unlink(missing_ok=True)
    image.unlink(missing_ok=True)
