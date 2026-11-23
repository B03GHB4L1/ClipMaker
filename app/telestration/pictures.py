"""Pictures an analyst puts into an annotated clip (docs/CODING_AND_PITCH_PLAN.md, section I).

    projects/<project>/pictures/<id>.png   the picture, re-encoded here so the file is always a clean PNG
    projects/<project>/pictures/<id>.json  its name, size and when it was added

The browser never names a path: ids are checked against a strict pattern and every file is read
from the project's own pictures folder. Writes are atomic.
"""
from __future__ import annotations

import json
import os
import re
import struct
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PICTURE_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_BYTES = 20_000_000
MAX_SIDE = 4096
MAX_PICTURES = 200


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


def _size(data: bytes) -> tuple[str, int, int]:
    """The format, width and height, read from the file's header before anything is decoded."""
    if data[:8] == bytes.fromhex("89504e470d0a1a0a") and len(data) >= 24:
        return "PNG", struct.unpack(">II", data[16:24])[0], struct.unpack(">II", data[16:24])[1]
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8X":
            return "WEBP", 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return "WEBP", 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
        if kind == b"VP8 ":
            return "WEBP", struct.unpack("<H", data[26:28])[0] & 0x3FFF, struct.unpack("<H", data[28:30])[0] & 0x3FFF
    if data[:2] == bytes.fromhex("ffd8"):
        position = 2
        while position + 9 < len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            marker = data[position + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                position += 2 if marker != 0xFF else 1
                continue
            length = struct.unpack(">H", data[position + 2:position + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[position + 5:position + 9])
                return "JPEG", width, height
            position += 2 + length
    raise ValueError("Only PNG, JPEG and WebP pictures can be added.")


def clean_png(data: bytes) -> tuple[bytes, int, int]:
    """The picture re-encoded as a PNG, with its width and height. Anything that is not a PNG, JPEG or WebP is refused."""
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("A picture must be under 20 MB.")
    kind, width, height = _size(data)
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise ValueError(f"A picture can be at most {MAX_SIDE} pixels on a side.")
    import cv2  # bundled for the tracker; Pillow is not shipped
    import numpy as np
    # A JPEG is read with its camera orientation applied; PNG and WebP keep their transparency.
    flag = cv2.IMREAD_COLOR if kind == "JPEG" else cv2.IMREAD_UNCHANGED
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), flag)
    if image is None or image.ndim not in (2, 3):
        raise ValueError("That file could not be read as a PNG, JPEG or WebP picture.")
    if image.dtype != np.uint8:
        image = cv2.convertScaleAbs(image, alpha=255.0 / (65535.0 if image.dtype == np.uint16 else 1.0))
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 2:
        image = cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2BGR)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("That file could not be read as a PNG, JPEG or WebP picture.")
    return encoded.tobytes(), int(image.shape[1]), int(image.shape[0])


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
    try:
        sessions = json.loads((project / "sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(isinstance(card, dict) and card.get("picture_id") == picture_id
               for session in sessions if isinstance(session, dict) for card in session.get("cards") or [])


def remove(project: Path, picture_id: str) -> None:
    """Delete a picture, unless an insert still shows it."""
    folder = project / "pictures"
    image, meta = _paths(folder, picture_id)
    if not meta.is_file():
        raise LookupError("That picture is not in the project any more.")
    if used_by(project, picture_id):
        raise ValueError("An insert or a card in one of the project's sessions shows this picture. Remove it first.")
    meta.unlink(missing_ok=True)
    image.unlink(missing_ok=True)
