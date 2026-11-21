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

# The code panel. An instant code makes one event at the playhead; an interval
# code starts on one press and stops on the next. `type` and `outcome` are the
# names scraped feeds use, so coded events work in the Filter's type list and in
# Analyst Room tabs that need only time and type. `before` and `after` are the
# lead-in and lead-out a clip of the code gets (a project can change them).
# Starting an interval stops the running one of its `group` (Possession for one
# team stops it for the other). Templates replace this list in C3.
def _instant(code_id, label, kind, outcome, key, colour, before, after):
    return {"id": code_id, "label": label, "kind": "instant", "type": kind, "outcome": outcome, "key": key,
            "colour": colour, "before": before, "after": after}


def _interval(code_id, label, kind, key, colour, group=None):
    return {"id": code_id, "label": label, "kind": "interval", "type": kind, "outcome": "Successful", "key": key,
            "colour": colour, "before": 3, "after": 2, "group": group or code_id}


CODES: list[dict[str, Any]] = [
    _instant("goal", "Goal", "Goal", "Successful", "g", "#c8f135", 10, 6),
    _instant("shot-on", "Shot on target", "SavedShot", "Successful", "s", "#5fb3ff", 6, 4),
    _instant("shot-off", "Shot off target", "MissedShot", "Unsuccessful", "d", "#7fa6c9", 6, 4),
    _instant("save", "Save", "Save", "Successful", "k", "#9b8cff", 6, 4),
    _instant("corner", "Corner", "CornerAwarded", "Successful", "c", "#ffb84d", 3, 10),
    _instant("foul", "Foul", "Foul", "Unsuccessful", "f", "#ff8a65", 5, 4),
    _instant("card", "Card", "Card", "Successful", "y", "#ffd84d", 8, 4),
    _instant("offside", "Offside", "OffsideGiven", "Successful", "o", "#c9a0dc", 6, 3),
    _instant("won", "Ball won", "BallRecovery", "Successful", "b", "#4fd1a5", 4, 6),
    _instant("lost", "Ball lost", "Dispossessed", "Successful", "l", "#e57373", 4, 6),
    _instant("moment", "Key moment", "Key moment", "Successful", "m", "#e8eae5", 5, 5),
    _interval("possession", "Possession", "Possession", "p", "#8fd3ff"),
    _interval("build-up", "Build-up", "Build-up", "u", "#a5e887"),
    _interval("press", "Pressing", "Pressing phase", "r", "#ffa07a"),
    _interval("transition", "Transition", "Transition", "x", "#f5c26b"),
]
CODE_IDS = {code["id"] for code in CODES}
CODE_BY_ID = {code["id"]: code for code in CODES}
MAX_LEAD = 60

_lock = threading.Lock()


def path_for(project_folder: Path) -> Path:
    return Path(project_folder) / FILE_NAME


def empty() -> dict[str, Any]:
    return {"version": VERSION, "events": [], "leads": {}}


def lead(document: dict[str, Any], code_id: str) -> tuple[int, int]:
    """(before, after) seconds of a code's clips: the project's choice, else the code's default."""
    code = CODE_BY_ID[code_id]
    chosen = (document.get("leads") or {}).get(code_id) or {}
    return int(chosen.get("before", code["before"])), int(chosen.get("after", code["after"]))


def clean_leads(value: Any) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        raise ValueError("Lead-in and lead-out must be set per code.")
    clean = {}
    for code_id, item in value.items():
        if code_id not in CODE_IDS or not isinstance(item, dict) or set(item) - {"before", "after"}:
            raise ValueError("Lead-in and lead-out are set per known code, as before and after.")
        entry = {}
        for side in ("before", "after"):
            if side in item:
                number = item[side]
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= MAX_LEAD or number != int(number):
                    raise ValueError(f"Lead-in and lead-out are whole seconds from 0 to {MAX_LEAD}.")
                entry[side] = int(number)
        clean[code_id] = entry
    return clean


def clean_event(value: Any, max_seconds: float = MAX_SECONDS) -> dict[str, Any]:
    """One coded event, or ValueError saying what is wrong with it."""
    if not isinstance(value, dict):
        raise ValueError("Each coded event must be an object.")
    unknown = set(value) - {"id", "code", "team", "src", "t", "end"}
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
    event = {"id": event_id, "code": code, "team": team, "src": src, "t": round(seconds, 3)}
    if CODE_BY_ID[code]["kind"] == "interval":
        end = value.get("end")
        if end is not None:  # None: still running
            try:
                end = float(end)
            except (TypeError, ValueError):
                raise ValueError("An interval's end must be a time in seconds.") from None
            if not math.isfinite(end) or end < seconds or end > max_seconds:
                raise ValueError("An interval must end after it starts, inside the video.")
            end = round(end, 3)
        event["end"] = end
    elif value.get("end") is not None:
        raise ValueError("Only interval codes have an end.")
    return event


def read(project_folder: Path) -> dict[str, Any]:
    path = path_for(project_folder)
    if not path.exists():
        return empty()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != VERSION or not isinstance(value.get("events"), list):
        raise ValueError("The saved codes are invalid; they have not been overwritten.")
    value.setdefault("leads", {})
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
    """Apply a batch ``{"add": [...], "update": [...], "delete": [ids], "leads": {...}}`` and save.

    The whole batch is checked before anything is written: one bad event
    leaves the saved codes as they were."""
    if not isinstance(changes, dict) or set(changes) - {"add", "update", "delete", "leads"}:
        raise ValueError("Send codes as add, update and delete lists.")
    leads = clean_leads(changes["leads"]) if "leads" in changes else None
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
        merged_leads = dict(document.get("leads") or {})
        for code_id, entry in (leads or {}).items():
            merged_leads[code_id] = {**merged_leads.get(code_id, {}), **entry}
        document = {"version": VERSION, "events": ordered, "leads": merged_leads}
        _write(project_folder, document)
        return document
