"""Coded events of one project, saved as ``coded_events.json`` in its folder.

Events are kept in video time (the file that was playing and the second in
it), never in match clock, so moving a kick-off marker later re-times them
instead of corrupting them. Every write is validated and atomic."""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

FILE_NAME = "coded_events.json"
VERSION = 1
MAX_EVENTS = 5000
MAX_CHANGES = 500
# Without a known video length, no time may be later than this.
MAX_SECONDS = 24 * 3600
SOURCE_KEYS = ("1H", "2H", "ET1", "ET2", "PEN")
TEAMS = ("home", "away", "")
EVENT_ID = re.compile(r"^c[0-9a-z]{6,32}$")

# The C1 code panel. Each code makes one event at the playhead. `type` and
# `outcome` are the names scraped feeds use, so coded events work in the
# Filter's type list and in Analyst Room tabs that need only time and type.
# Templates replace this list in C3.
CODES: list[dict[str, Any]] = [
    {"id": "goal", "label": "Goal", "type": "Goal", "outcome": "Successful", "key": "g", "colour": "#c8f135"},
    {"id": "shot-on", "label": "Shot on target", "type": "SavedShot", "outcome": "Successful", "key": "s", "colour": "#5fb3ff"},
    {"id": "shot-off", "label": "Shot off target", "type": "MissedShot", "outcome": "Unsuccessful", "key": "d", "colour": "#7fa6c9"},
    {"id": "save", "label": "Save", "type": "Save", "outcome": "Successful", "key": "k", "colour": "#9b8cff"},
    {"id": "corner", "label": "Corner", "type": "CornerAwarded", "outcome": "Successful", "key": "c", "colour": "#ffb84d"},
    {"id": "foul", "label": "Foul", "type": "Foul", "outcome": "Unsuccessful", "key": "f", "colour": "#ff8a65"},
    {"id": "card", "label": "Card", "type": "Card", "outcome": "Successful", "key": "y", "colour": "#ffd84d"},
    {"id": "offside", "label": "Offside", "type": "OffsideGiven", "outcome": "Successful", "key": "o", "colour": "#c9a0dc"},
    {"id": "won", "label": "Ball won", "type": "BallRecovery", "outcome": "Successful", "key": "b", "colour": "#4fd1a5"},
    {"id": "lost", "label": "Ball lost", "type": "Dispossessed", "outcome": "Successful", "key": "l", "colour": "#e57373"},
    {"id": "moment", "label": "Key moment", "type": "Key moment", "outcome": "Successful", "key": "m", "colour": "#e8eae5"},
]
CODE_IDS = {code["id"] for code in CODES}

_lock = threading.Lock()


def path_for(project_folder: Path) -> Path:
    return Path(project_folder) / FILE_NAME


def empty() -> dict[str, Any]:
    return {"version": VERSION, "events": []}


def clean_event(value: Any, max_seconds: float = MAX_SECONDS) -> dict[str, Any]:
    """One coded event, or ValueError saying what is wrong with it."""
    if not isinstance(value, dict):
        raise ValueError("Each coded event must be an object.")
    unknown = set(value) - {"id", "code", "team", "src", "t"}
    if unknown:
        raise ValueError(f"Unknown coded event field: {sorted(unknown)[0]}.")
    event_id = str(value.get("id") or "")
    if not EVENT_ID.match(event_id):
        raise ValueError("Coded event ids are 'c' followed by 6 to 32 letters or digits.")
    code = str(value.get("code") or "")
    if code not in CODE_IDS:
        raise ValueError(f"Unknown code: {code[:40] or '(none)'}.")
    team = str(value.get("team") or "")
    if team not in TEAMS:
        raise ValueError("A coded event's team is home, away or none.")
    src = str(value.get("src") or "1H")
    if src not in SOURCE_KEYS:
        raise ValueError("A coded event's video is 1H, 2H, ET1, ET2 or PEN.")
    try:
        seconds = float(value.get("t"))
    except (TypeError, ValueError):
        raise ValueError("A coded event needs a time in seconds.") from None
    if not math.isfinite(seconds) or seconds < 0 or seconds > max_seconds:
        raise ValueError("A coded event's time must be inside the video.")
    return {"id": event_id, "code": code, "team": team, "src": src, "t": round(seconds, 3)}


def read(project_folder: Path) -> dict[str, Any]:
    path = path_for(project_folder)
    if not path.exists():
        return empty()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != VERSION or not isinstance(value.get("events"), list):
        raise ValueError("The saved codes are invalid; they have not been overwritten.")
    return value


def _write(project_folder: Path, value: dict[str, Any]) -> None:
    path = path_for(project_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="saving-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=1, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(project_folder: Path, changes: Any, max_seconds: float = MAX_SECONDS) -> dict[str, Any]:
    """Apply a batch ``{"add": [...], "update": [...], "delete": [ids]}`` and save.

    The whole batch is checked before anything is written: one bad event
    leaves the saved codes as they were."""
    if not isinstance(changes, dict) or set(changes) - {"add", "update", "delete"}:
        raise ValueError("Send codes as add, update and delete lists.")
    add = changes.get("add") or []
    update = changes.get("update") or []
    delete = changes.get("delete") or []
    if not all(isinstance(part, list) for part in (add, update, delete)):
        raise ValueError("Send codes as add, update and delete lists.")
    if len(add) + len(update) + len(delete) > MAX_CHANGES:
        raise ValueError(f"Send at most {MAX_CHANGES} code changes at once.")
    with _lock:
        document = read(project_folder)
        events = {event["id"]: event for event in document["events"] if isinstance(event, dict) and "id" in event}
        for event_id in delete:
            events.pop(str(event_id), None)  # already gone is fine: a repeated delete
        for item in update:
            if not isinstance(item, dict) or str(item.get("id") or "") not in events:
                raise ValueError("That coded event no longer exists.")
            events[item["id"]] = clean_event({**events[item["id"]], **item}, max_seconds)
        for item in add:
            event = clean_event(item, max_seconds)
            if event["id"] in events:
                raise ValueError("A coded event with that id already exists.")
            events[event["id"]] = event
        if len(events) > MAX_EVENTS:
            raise ValueError(f"A project holds at most {MAX_EVENTS} coded events.")
        ordered = sorted(events.values(), key=lambda event: (SOURCE_KEYS.index(event["src"]), event["t"], event["id"]))
        document = {"version": VERSION, "events": ordered}
        _write(project_folder, document)
        return document
