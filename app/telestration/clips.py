"""Clips copied into a project for the analyst editor, and their saved drawings.

Preview clips live in scratch folders the engine prunes, so pressing Annotate
first copies the clip into the project:

    projects/<project>/clips/<clip>.mp4        the video
    projects/<project>/clips/<clip>.json       its facts (fps, size, frames...)
    projects/<project>/annotations/<clip>.json the drawings
    projects/<project>/sessions.json           annotate sessions: named groups of clips, their order, and cards
                                               (a picture or a line of text shown for a few seconds between clips)

A clip saved before sessions existed gets a session of its own when the
project's sessions are listed. Every write is atomic. Ids are checked against strict patterns, so no request
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

from . import annotations, parts as cuts, pictures

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
        return annotations.clean_document(saved, record["duration"], record["frames"])

    def save_annotations(self, project_id: str, clip_id: str, document: Any) -> dict[str, Any]:
        record, _ = self.get(project_id, clip_id)
        clean = annotations.clean_document(document, record["duration"], record["frames"])
        _, _, path = self._clip_paths(project_id, clip_id)
        folder = self.pictures_dir(project_id)
        if any(pictures.file_of(folder, picture_id) is None for picture_id in pictures.picture_ids(clean)):
            raise ValueError("A picture in this clip is not in the project any more. Remove its insert or add the picture again.")
        _atomic_json(path, clean)
        return clean

    def project_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id)

    def pictures_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "pictures"

    # -----------------------------------------------------------------------
    # Sessions: named groups of clips annotated together (the Annotate tab)
    # -----------------------------------------------------------------------
    def _clip_ids(self, project_id: str) -> list[str]:
        folder = self._project_dir(project_id) / "clips"
        if not folder.is_dir():
            return []
        found = [path.stem for path in folder.glob("*.json") if CLIP_ID.match(path.stem) and path.with_suffix(".mp4").is_file()]
        return found

    def _read_sessions(self, project_id: str) -> list[dict[str, Any]]:
        path = self._project_dir(project_id) / "sessions.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        except (OSError, ValueError):
            value = []  # a damaged list is rebuilt from the clips below; no clip is lost
        sessions = []
        for entry in value if isinstance(value, list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and SESSION_ID.match(entry["id"]):
                clips = [c for c in entry.get("clips", []) if isinstance(c, str) and CLIP_ID.match(c)]
                cards = [card for card in (clean_card(each) for each in entry.get("cards") or []) if card][:MAX_CARDS]
                order = _in_order(entry.get("order"), clips, cards)
                sessions.append({"id": entry["id"], "name": str(entry.get("name") or "Session")[:120],
                                 "clips": [token for token in order if CLIP_ID.match(token)], "cards": cards, "order": order,
                                 "created_at": str(entry.get("created_at") or ""), "updated_at": str(entry.get("updated_at") or "")})
        return sessions

    def _write_sessions(self, project_id: str, sessions: list[dict[str, Any]]) -> None:
        _atomic_json(self._project_dir(project_id) / "sessions.json", sessions)

    def sessions(self, project_id: str) -> list[dict[str, Any]]:
        """The project's sessions, newest first, each with its clips' details and drawing counts.

        Clips that are in no session (saved before sessions, or left over) each get one.
        """
        present = set(self._clip_ids(project_id))
        sessions = self._read_sessions(project_id)
        grouped = {clip for session in sessions for clip in session["clips"]}
        changed = False
        for session in sessions:
            kept = [clip for clip in session["clips"] if clip in present]
            changed |= kept != session["clips"]
            session["clips"] = kept
            session["order"] = _in_order(session["order"], kept, session["cards"])
        for clip_id in sorted(present - grouped):
            record, _ = self.get(project_id, clip_id)
            sessions.append(_new_session(record.get("name") or "Clip", [clip_id], record.get("created_at") or ""))
            changed = True
        sessions = [session for session in sessions if session["clips"]]
        if changed:
            self._write_sessions(project_id, sessions)
        result = []
        for session in sessions:
            clips = []
            for clip_id in session["clips"]:
                record, _ = self.get(project_id, clip_id)
                _, _, notes = self._clip_paths(project_id, clip_id)
                drawings = 0
                edited = record.get("created_at") or ""
                seconds = record.get("duration")
                if notes.is_file():
                    try:
                        saved = json.loads(notes.read_text(encoding="utf-8"))
                        drawings = len(saved.get("items", [])) + len(saved.get("freezes", []))
                        seconds = output_seconds(record, saved)
                    except (OSError, ValueError, TypeError, KeyError):
                        pass
                    edited = datetime.fromtimestamp(notes.stat().st_mtime, timezone.utc).isoformat()
                clips.append({"id": clip_id, "name": record.get("name") or "Clip", "duration": record.get("duration"),
                              "seconds": seconds, "width": record.get("width"), "height": record.get("height"),
                              "drawings": drawings, "edited_at": edited})
            updated = max([session.get("updated_at") or "", *(clip["edited_at"] for clip in clips)])
            by_id = {clip["id"]: {"kind": "clip", **clip} for clip in clips}
            by_id.update({card["id"]: {**card, "type": card["kind"], "kind": "card"} for card in session["cards"]})
            items = [by_id[token] for token in session["order"] if token in by_id]
            result.append({**session, "clips": clips, "items": items, "updated_at": updated})
        return sorted(result, key=lambda session: session["updated_at"], reverse=True)

    def has_session(self, project_id: str, session_id: str) -> bool:
        return any(session["id"] == session_id for session in self._read_sessions(project_id))

    def add_to_session(self, project_id: str, clip_id: str, session_id: str | None = None, name: str = "") -> dict[str, Any]:
        """Put a clip in session `session_id`, or in a new session (named `name`). Returns the session."""
        self.get(project_id, clip_id)
        sessions = self._read_sessions(project_id)
        for session in sessions:
            if clip_id in session["clips"] and session["id"] != session_id:
                session["clips"].remove(clip_id)
        target = next((session for session in sessions if session["id"] == session_id), None) if session_id else None
        if session_id and target is None:
            raise LookupError("That annotate session is not in the project any more.")
        if target is None:
            target = _new_session(name or "Session", [])
            sessions.append(target)
        if clip_id not in target["clips"]:
            target["clips"].append(clip_id)
            target["order"] = [*target["order"], clip_id]
        target["updated_at"] = _now()
        self._write_sessions(project_id, [session for session in sessions if session["clips"]])
        return target

    def _session(self, project_id: str, session_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        sessions = self._read_sessions(project_id)
        target = next((session for session in sessions if session["id"] == session_id), None)
        if target is None:
            raise LookupError("That annotate session is not in the project any more.")
        return sessions, target

    def reorder_session(self, project_id: str, session_id: str, order: Any) -> dict[str, Any]:
        """Put a session's clips and cards in `order` (the same ids, each once): the order a sequence plays and exports."""
        sessions, target = self._session(project_id, session_id)
        known = [*target["clips"], *(card["id"] for card in target["cards"])]
        if not isinstance(order, list) or len(order) != len(known) or sorted(str(item) for item in order) != sorted(known):
            raise ValueError("The new order must list the session's clips and cards, each once.")
        target["order"] = [str(item) for item in order]
        target["clips"] = [token for token in target["order"] if CLIP_ID.match(token)]
        target["updated_at"] = _now()
        self._write_sessions(project_id, sessions)
        return target

    def add_card(self, project_id: str, session_id: str, fields: dict[str, Any], index: Any = None) -> dict[str, Any]:
        """Put a card (a picture or a line of text, shown for a few seconds) in a session, at `index` or the end."""
        sessions, target = self._session(project_id, session_id)
        if len(target["cards"]) >= MAX_CARDS:
            raise ValueError(f"A session can have up to {MAX_CARDS} cards.")
        card = clean_card({**fields, "id": f"k{uuid.uuid4().hex[:16]}"}, strict=True)
        if card["kind"] == "picture" and pictures.file_of(self.pictures_dir(project_id), card["picture_id"]) is None:
            raise ValueError("That picture is not in the project any more.")
        target["cards"].append(card)
        order = list(target["order"])
        at = index if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= len(order) else len(order)
        order.insert(at, card["id"])
        target["order"] = order
        target["updated_at"] = _now()
        self._write_sessions(project_id, sessions)
        return card

    def update_card(self, project_id: str, session_id: str, card_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        sessions, target = self._session(project_id, session_id)
        old = next((card for card in target["cards"] if card["id"] == card_id), None)
        if old is None:
            raise LookupError("That card is not in the session any more.")
        card = clean_card({**old, **{key: value for key, value in fields.items() if key in ("text", "seconds", "picture_id", "kind")}}, strict=True)
        if card["kind"] == "picture" and pictures.file_of(self.pictures_dir(project_id), card["picture_id"]) is None:
            raise ValueError("That picture is not in the project any more.")
        target["cards"] = [card if each["id"] == card_id else each for each in target["cards"]]
        target["updated_at"] = _now()
        self._write_sessions(project_id, sessions)
        return card

    def remove_card(self, project_id: str, session_id: str, card_id: str) -> None:
        sessions, target = self._session(project_id, session_id)
        if not any(card["id"] == card_id for card in target["cards"]):
            raise LookupError("That card is not in the session any more.")
        target["cards"] = [card for card in target["cards"] if card["id"] != card_id]
        target["order"] = [token for token in target["order"] if token != card_id]
        target["updated_at"] = _now()
        self._write_sessions(project_id, sessions)

    def rename_session(self, project_id: str, session_id: str, name: str) -> dict[str, Any]:
        clean = re.sub(r"\s+", " ", str(name or "")).strip()[:120]
        if not clean:
            raise ValueError("Give the session a name.")
        sessions = self._read_sessions(project_id)
        target = next((session for session in sessions if session["id"] == session_id), None)
        if target is None:
            raise LookupError("That annotate session is not in the project any more.")
        target["name"] = clean
        target["updated_at"] = _now()
        self._write_sessions(project_id, sessions)
        return target

    def remove_clip(self, project_id: str, clip_id: str) -> None:
        """Move a clip, its facts and its drawings to the project's trash folder (not deleted outright)."""
        paths = self._clip_paths(project_id, clip_id)
        if not paths[0].is_file():
            raise LookupError("This clip is not in the project any more.")
        trash = self._project_dir(project_id) / "editor-trash" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{clip_id}"
        trash.mkdir(parents=True, exist_ok=True)
        for path, name in zip(paths, ("clip.mp4", "clip.json", "annotations.json")):
            if path.is_file():
                os.replace(path, trash / name)
        sessions = self._read_sessions(project_id)
        for session in sessions:
            if clip_id in session["clips"]:
                session["clips"].remove(clip_id)
        self._write_sessions(project_id, [session for session in sessions if session["clips"]])

    def remove_session(self, project_id: str, session_id: str) -> int:
        """Remove a session and move its clips to the trash. Returns how many clips went."""
        target = next((session for session in self._read_sessions(project_id) if session["id"] == session_id), None)
        if target is None:
            raise LookupError("That annotate session is not in the project any more.")
        for clip_id in list(target["clips"]):
            try:
                self.remove_clip(project_id, clip_id)
            except LookupError:
                pass
        self._write_sessions(project_id, [s for s in self._read_sessions(project_id) if s["id"] != session_id and s["clips"]])
        return len(target["clips"])


SESSION_ID = re.compile(r"^s[a-f0-9]{16}$")
CARD_ID = re.compile(r"^k[a-f0-9]{16}$")
MAX_CARDS = 50
CARD_SECONDS = (0.5, 30.0)
CARD_TEXT = 200


def clean_card(value: Any, strict: bool = False) -> dict[str, Any] | None:
    """A card as stored: {id, kind: "picture" | "text", seconds, picture_id | text}. Damaged saved cards are dropped
    (None); a card a request sends raises ValueError (`strict`) so the analyst is told what is wrong."""
    def fail(message: str) -> None:
        if strict:
            raise ValueError(message)
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not CARD_ID.match(value["id"]):
        fail("Invalid card.")
        return None
    seconds = value.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not seconds == seconds:
        fail("A card needs a length in seconds.")
        return None
    seconds = round(min(CARD_SECONDS[1], max(CARD_SECONDS[0], float(seconds))), 2)
    if value.get("kind") == "picture":
        if not isinstance(value.get("picture_id"), str) or not pictures.PICTURE_ID.match(value["picture_id"]):
            fail("Choose a picture for the card.")
            return None
        return {"id": value["id"], "kind": "picture", "seconds": seconds, "picture_id": value["picture_id"]}
    if value.get("kind") == "text":
        text = re.sub(r"[ \t]+", " ", str(value.get("text") or "")).strip()[:CARD_TEXT]
        if not text:
            fail("Type the card's text.")
            return None
        return {"id": value["id"], "kind": "text", "seconds": seconds, "text": text}
    fail("A card is a picture or a line of text.")
    return None


def _in_order(saved: Any, clips: list[str], cards: list[dict[str, Any]]) -> list[str]:
    """`saved` order kept for the clips and cards that exist, with any not in it added at the end."""
    known = [*clips, *(card["id"] for card in cards)]
    order = []
    for token in saved if isinstance(saved, list) else []:
        if token in known and token not in order:
            order.append(token)
    return [*order, *(token for token in known if token not in order)]


def output_seconds(record: dict[str, Any], saved: dict[str, Any]) -> float:
    """How long the clip plays once exported: its parts joined, plus every freeze and board."""
    frames = int(record["frames"])
    cut = cuts.cut_frames(saved.get("parts") or None, frames)
    held = sum(float(freeze.get("seconds") or 0) for freeze in saved.get("freezes") or [] if isinstance(freeze, dict))
    return round(cut / float(record["fps"]) + held, 3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_session(name: str, clips: list[str], created: str = "") -> dict[str, Any]:
    stamp = created or _now()
    return {"id": f"s{uuid.uuid4().hex[:16]}", "name": str(name)[:120] or "Session", "clips": list(clips),
            "cards": [], "order": list(clips), "created_at": stamp, "updated_at": stamp}
