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

from . import templates

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
# team stops it for the other). A project codes with its own copy of a template
# (templates.py, C3); without one it codes with the built-in match panel.
CODES: list[dict[str, Any]] = templates.built_in()["codes"]
CODE_IDS = {code["id"] for code in CODES}
CODE_BY_ID = {code["id"]: code for code in CODES}
MAX_LEAD = 60
MAX_SQUAD = 60
MAX_EVENT_TAGS = 10

_lock = threading.Lock()


def path_for(project_folder: Path) -> Path:
    return Path(project_folder) / FILE_NAME


def empty() -> dict[str, Any]:
    return {"version": VERSION, "events": [], "leads": {}, "panel": templates.built_in(), "squads": {"home": [], "away": []}}


def panel_codes(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {code["id"]: code for code in (document.get("panel") or templates.built_in())["codes"]}


def panel_tags(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {tag["id"]: tag for tag in (document.get("panel") or templates.built_in()).get("tags", [])}


def lead(document: dict[str, Any], code_id: str) -> tuple[int, int]:
    """(before, after) seconds of a code's clips: the project's choice, else the code's default."""
    code = panel_codes(document)[code_id]
    chosen = (document.get("leads") or {}).get(code_id) or {}
    return int(chosen.get("before", code["before"])), int(chosen.get("after", code["after"]))


def clean_leads(value: Any, code_ids: set[str] | None = None) -> dict[str, dict[str, int]]:
    code_ids = CODE_IDS if code_ids is None else code_ids
    if not isinstance(value, dict):
        raise ValueError("Lead-in and lead-out must be set per code.")
    clean = {}
    for code_id, item in value.items():
        if code_id not in code_ids or not isinstance(item, dict) or set(item) - {"before", "after"}:
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


def _shirt(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or not 0 <= value <= 99:
        raise ValueError("A shirt number is a whole number from 0 to 99.")
    return int(value)


def clean_squads(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Shirt numbers and names of each team, for number keys after a code."""
    if not isinstance(value, dict) or set(value) - {"home", "away"}:
        raise ValueError("Squads are a home and an away list.")
    squads = {}
    for side in ("home", "away"):
        players = value.get(side) or []
        if not isinstance(players, list) or len(players) > MAX_SQUAD:
            raise ValueError(f"A squad lists at most {MAX_SQUAD} players.")
        clean, numbers = [], set()
        for player in players:
            if not isinstance(player, dict) or set(player) - {"number", "name"}:
                raise ValueError("Each player has a shirt number and a name.")
            number = _shirt(player.get("number"))
            if number in numbers:
                raise ValueError(f"Shirt number {number} is listed twice in one squad.")
            numbers.add(number)
            name = str(player.get("name") or "").strip()
            if len(name) > 40 or any(ch in name for ch in "<>") or any(ord(ch) < 32 for ch in name):
                raise ValueError("A player's name is at most 40 characters, without < or >.")
            clean.append({"number": number, "name": name})
        squads[side] = sorted(clean, key=lambda player: player["number"])
    return squads


def clean_event(value: Any, max_seconds: float = MAX_SECONDS, document: dict[str, Any] | None = None) -> dict[str, Any]:
    """One coded event, checked against the project's panel, or ValueError saying what is wrong with it."""
    codes = panel_codes(document or {})
    tags = panel_tags(document or {})
    if not isinstance(value, dict):
        raise ValueError("Each coded event must be an object.")
    unknown = set(value) - {"id", "code", "team", "src", "t", "end", "tags", "player", "x", "y", "endX", "endY"}
    if unknown:
        raise ValueError(f"Unknown coded event field: {sorted(unknown)[0]}.")
    event_id = str(value.get("id") or "")
    if not EVENT_ID.match(event_id):
        raise ValueError("Coded event ids are 'c' followed by 6 to 32 letters or digits.")
    code = str(value.get("code") or "")
    if code not in codes:
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
    if codes[code]["kind"] == "interval":
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
    if value.get("tags"):
        chosen = value["tags"]
        if not isinstance(chosen, list) or len(chosen) > MAX_EVENT_TAGS:
            raise ValueError(f"A coded event has at most {MAX_EVENT_TAGS} tags.")
        chosen = list(dict.fromkeys(str(tag) for tag in chosen))
        missing = [tag for tag in chosen if tag not in tags]
        if missing:
            raise ValueError(f"The code panel has no tag {missing[0][:40]}.")
        groups = [tags[tag]["group"] for tag in chosen if tags[tag].get("group")]
        if len(groups) != len(set(groups)):
            raise ValueError("A coded event takes one tag of each group (Left or Right, not both).")
        event["tags"] = chosen
    if value.get("player") is not None:
        event["player"] = _shirt(value["player"])
    event.update(_location(value))
    return event


def _coordinate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("A pitch location is from 0 to 100 across and along the pitch.")
    return round(float(value), 1)


def _location(value: dict[str, Any]) -> dict[str, float]:
    """Where on the pitch (C4), in the scraped feeds' scale: x 0 to 100 from the event's
    team's own goal to the opponent's, y 0 to 100 from its right touchline to its left.
    An end point (a pass's target) needs a start; either both of a pair or neither."""
    pairs = {}
    for first, second in (("x", "y"), ("endX", "endY")):
        given = [value.get(first) is not None, value.get(second) is not None]
        if any(given) and not all(given):
            raise ValueError("A pitch location needs both its across and along values.")
        if all(given):
            pairs[first], pairs[second] = _coordinate(value[first]), _coordinate(value[second])
    if "endX" in pairs and "x" not in pairs:
        raise ValueError("An end point needs a start point on the pitch.")
    return pairs


def read(project_folder: Path) -> dict[str, Any]:
    path = path_for(project_folder)
    if not path.exists():
        return empty()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != VERSION or not isinstance(value.get("events"), list):
        raise ValueError("The saved codes are invalid; they have not been overwritten.")
    value.setdefault("leads", {})
    if value.get("panel") is None:
        value["panel"] = templates.built_in()
    value.setdefault("squads", {"home": [], "away": []})
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
    """Apply a batch ``{"add", "update", "delete", "leads", "panel", "squads"}`` and save.

    The whole batch is checked before anything is written: one bad event
    leaves the saved codes as they were. A new panel is refused while any
    event uses a code or tag it does not have. In an update, ``tags: []``,
    ``player: null`` and ``x: null`` (with ``y``, ``endX``, ``endY``) clear those fields."""
    if not isinstance(changes, dict) or set(changes) - {"add", "update", "delete", "leads", "panel", "squads"}:
        raise ValueError("Send codes as add, update and delete lists.")
    add = changes.get("add") or []
    update = changes.get("update") or []
    delete = changes.get("delete") or []
    if not all(isinstance(part, list) for part in (add, update, delete)):
        raise ValueError("Send codes as add, update and delete lists.")
    if len(add) + len(update) + len(delete) > MAX_CHANGES:
        raise ValueError(f"Send at most {MAX_CHANGES} code changes at once.")
    panel = templates.clean(changes["panel"]) if "panel" in changes else None
    squads = clean_squads(changes["squads"]) if "squads" in changes else None
    with _lock:
        document = read(project_folder)
        if panel is not None:
            document["panel"] = panel
        if squads is not None:
            document["squads"] = squads
        code_ids = set(panel_codes(document))
        leads = clean_leads(changes["leads"], code_ids) if "leads" in changes else None
        events = {event["id"]: event for event in document["events"] if isinstance(event, dict) and "id" in event}
        for event_id in delete:
            events.pop(str(event_id), None)  # already gone is fine: a repeated delete
        for item in update:
            if not isinstance(item, dict) or str(item.get("id") or "") not in events:
                raise ValueError("That coded event no longer exists.")
            events[item["id"]] = clean_event({**events[item["id"]], **item}, max_seconds, document)
        for item in add:
            event = clean_event(item, max_seconds, document)
            if event["id"] in events:
                raise ValueError("A coded event with that id already exists.")
            events[event["id"]] = event
        if panel is not None:
            for event_id, event in events.items():
                try:
                    events[event_id] = clean_event(event, max_seconds, document)
                except ValueError:
                    raise ValueError("Some coded events use codes or tags this panel does not have; "
                                     "delete or recode them first.") from None
        if len(events) > MAX_EVENTS:
            raise ValueError(f"A project holds at most {MAX_EVENTS} coded events.")
        ordered = sorted(events.values(), key=lambda event: (SOURCE_KEYS.index(event["src"]), event["t"], event["id"]))
        merged_leads = {code_id: entry for code_id, entry in (document.get("leads") or {}).items() if code_id in code_ids}
        for code_id, entry in (leads or {}).items():
            merged_leads[code_id] = {**merged_leads.get(code_id, {}), **entry}
        document = {"version": VERSION, "events": ordered, "leads": merged_leads,
                    "panel": document["panel"], "squads": document["squads"]}
        _write(project_folder, document)
        return document
