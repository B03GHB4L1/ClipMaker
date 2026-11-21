"""Code panels (templates) for the Code screen (docs/CODING_AND_PITCH_PLAN.md, C3).

A template is the set of codes and tags an analyst codes with. Built-in ones
ship with the app; the analyst's own live in ``code-templates/`` in the data
folder and import and export as JSON files. A project keeps its own copy of the
panel it codes with, so changing a template later never breaks its events.

Every field is checked and unknown fields are refused, so a template file from
someone else can only describe codes, never point at files or run anything."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

VERSION = 1
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
TEXT = re.compile(r"^[^\x00-\x1f\x7f<>]{1,40}$")
RESERVED_KEYS = {"h", "a"}  # H and A choose the team
OUTCOMES = {"Successful", "Unsuccessful"}
TEAMS = {"same", "other"}
MAX_CODES = 40
MAX_TAGS = 40
MAX_LEAD = 60
# Columns of the event table Filter's qualifiers read (clipmaker_core.INTENT_FLAG_TO_BOOL_COL);
# a tag may set one, so "Big chance" on a coded shot works with Filter's Big chances qualifier
# (each qualifier still applies to its own event types, as with scraped data).
FLAGS = (
    "is_header", "is_corner", "is_freekick", "is_cross", "is_penalty", "is_big_chance_shot", "is_left_foot",
    "is_right_foot", "is_volley", "is_fast_break", "is_own_goal", "is_yellow_card", "is_red_card",
    "is_throw_in", "is_through_ball", "is_long_ball", "is_key_pass", "is_assist", "is_1on1", "is_deflected",
    "is_hit_woodwork", "is_nutmeg", "is_gk_save",
)
CODE_FIELDS = {"id", "label", "kind", "type", "outcome", "key", "colour", "before", "after", "group", "tags", "starts", "stops"}
TAG_FIELDS = {"id", "label", "key", "group", "outcome", "flag"}
TEMPLATE_FIELDS = {"version", "id", "name", "codes", "tags"}


def _instant(code_id, label, kind, outcome, key, colour, before, after, **links):
    return {"id": code_id, "label": label, "kind": "instant", "type": kind, "outcome": outcome, "key": key,
            "colour": colour, "before": before, "after": after, **links}


def _interval(code_id, label, kind, key, colour, group=None, before=3, after=2):
    return {"id": code_id, "label": label, "kind": "interval", "type": kind, "outcome": "Successful", "key": key,
            "colour": colour, "before": before, "after": after, "group": group or code_id}


def _tag(tag_id, label, key, **extra):
    return {"id": tag_id, "label": label, "key": key, **extra}


SIDE_TAGS = [_tag("left", "Left", "L", group="side"), _tag("centre", "Centre", "C", group="side"),
             _tag("right", "Right", "R", group="side")]
RESULT_TAGS = [_tag("successful", "Successful", "S", group="result", outcome="Successful"),
               _tag("unsuccessful", "Unsuccessful", "U", group="result", outcome="Unsuccessful")]

BUILT_INS: list[dict[str, Any]] = [
    {"version": VERSION, "id": "match", "name": "Match: two teams", "codes": [
        _instant("goal", "Goal", "Goal", "Successful", "g", "#c8f135", 10, 6, stops=["possession"]),
        _instant("shot-on", "Shot on target", "SavedShot", "Successful", "s", "#5fb3ff", 6, 4),
        _instant("shot-off", "Shot off target", "MissedShot", "Unsuccessful", "d", "#7fa6c9", 6, 4),
        _instant("save", "Save", "Save", "Successful", "k", "#9b8cff", 6, 4),
        _instant("corner", "Corner", "CornerAwarded", "Successful", "c", "#ffb84d", 3, 10, tags=["set-piece"]),
        _instant("foul", "Foul", "Foul", "Unsuccessful", "f", "#ff8a65", 5, 4),
        _instant("card", "Card", "Card", "Successful", "y", "#ffd84d", 8, 4),
        _instant("offside", "Offside", "OffsideGiven", "Successful", "o", "#c9a0dc", 6, 3),
        _instant("won", "Ball won", "BallRecovery", "Successful", "b", "#4fd1a5", 4, 6,
                 starts=[{"code": "possession", "team": "same"}]),
        _instant("lost", "Ball lost", "Dispossessed", "Successful", "l", "#e57373", 4, 6,
                 starts=[{"code": "possession", "team": "other"}]),
        _instant("moment", "Key moment", "Key moment", "Successful", "m", "#e8eae5", 5, 5),
        _interval("possession", "Possession", "Possession", "p", "#8fd3ff"),
        _interval("build-up", "Build-up", "Build-up", "u", "#a5e887"),
        _interval("press", "Pressing", "Pressing phase", "r", "#ffa07a"),
        _interval("transition", "Transition", "Transition", "x", "#f5c26b"),
    ], "tags": [*SIDE_TAGS, *RESULT_TAGS,
                _tag("header", "Header", "E", flag="is_header"),
                _tag("set-piece", "Set piece", "P"),
                _tag("counter", "Counter-attack", "F", flag="is_fast_break"),
                _tag("big-chance", "Big chance", "B", flag="is_big_chance_shot")]},
    {"version": VERSION, "id": "set-pieces", "name": "Set pieces", "codes": [
        _instant("corner", "Corner", "CornerAwarded", "Successful", "c", "#ffb84d", 3, 12),
        _instant("free-kick", "Free kick", "Free kick", "Successful", "f", "#ff8a65", 3, 12, tags=["direct"]),
        _instant("throw-in", "Long throw", "Throw-in", "Successful", "t", "#c9a0dc", 3, 10),
        _instant("penalty", "Penalty", "Penalty", "Successful", "p", "#c8f135", 4, 6),
        _instant("shot", "Shot", "SavedShot", "Successful", "s", "#5fb3ff", 6, 4),
        _instant("goal", "Goal", "Goal", "Successful", "g", "#c8f135", 10, 6),
        _instant("cleared", "Cleared", "Clearance", "Successful", "x", "#7fa6c9", 6, 3),
    ], "tags": [_tag("near", "Near post", "N", group="target"), _tag("far", "Far post", "F", group="target"),
                _tag("short", "Short", "S", group="target"), _tag("direct", "Direct", "D"),
                _tag("header", "Header", "E", flag="is_header"), *RESULT_TAGS[1:]]},
    {"version": VERSION, "id": "training", "name": "Training: drills", "codes": [
        _interval("drill", "Drill", "Drill", "d", "#8fd3ff", before=2, after=2),
        _instant("rep", "Repetition", "Repetition", "Successful", "r", "#a5e887", 3, 5),
        _instant("good", "Good action", "Good action", "Successful", "g", "#c8f135", 5, 3),
        _instant("error", "Error", "Error", "Unsuccessful", "e", "#e57373", 5, 3),
        _instant("goal", "Goal", "Goal", "Successful", "s", "#ffd84d", 8, 4),
        _instant("point", "Coaching point", "Coaching point", "Successful", "c", "#e8eae5", 6, 6),
    ], "tags": [*RESULT_TAGS, _tag("decision", "Decision", "D"), _tag("technique", "Technique", "T"),
                _tag("intensity", "Intensity", "I")]},
    {"version": VERSION, "id": "keeper", "name": "Goalkeeper", "codes": [
        _instant("save", "Save", "Save", "Successful", "s", "#9b8cff", 6, 4),
        _instant("claim", "Claim", "KeeperPickup", "Successful", "c", "#4fd1a5", 6, 3),
        _instant("punch", "Punch", "Punch", "Successful", "p", "#ffb84d", 6, 3),
        _instant("sweep", "Sweeper action", "KeeperSweeper", "Successful", "w", "#8fd3ff", 6, 4),
        _instant("distribution", "Distribution", "Pass", "Successful", "d", "#a5e887", 3, 6),
        _instant("conceded", "Goal conceded", "Goal", "Successful", "g", "#e57373", 10, 4),
        _instant("error", "Error", "Error", "Unsuccessful", "e", "#ff8a65", 6, 4),
    ], "tags": [_tag("hands", "Hands", "H", group="body"), _tag("feet", "Feet", "F", group="body"),
                _tag("long", "Long", "L", group="range"), _tag("short", "Short", "T", group="range"),
                *RESULT_TAGS]},
]
BUILT_IN_IDS = {template["id"] for template in BUILT_INS}
DEFAULT_ID = "match"


def built_in(template_id: str = DEFAULT_ID) -> dict[str, Any]:
    return copy.deepcopy(next(template for template in BUILT_INS if template["id"] == template_id))


def _fail(message: str):
    raise ValueError(message)


def _text(value: Any, what: str) -> str:
    text = str(value if value is not None else "").strip()
    if not TEXT.match(text):
        _fail(f"{what} must be 1 to 40 characters, without < or >.")
    return text


def _whole(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or not 0 <= value <= MAX_LEAD:
        _fail(f"{what} must be whole seconds from 0 to {MAX_LEAD}.")
    return int(value)


def _unknown(value: dict, allowed: set, what: str) -> None:
    extra = set(value) - allowed
    if extra:
        _fail(f"{what} has an unknown field: {sorted(map(str, extra))[0][:40]}.")


def clean(value: Any) -> dict[str, Any]:
    """A template checked field by field, or ValueError saying what is wrong."""
    if not isinstance(value, dict):
        _fail("A code panel must be an object.")
    _unknown(value, TEMPLATE_FIELDS, "The code panel")
    if value.get("version", VERSION) != VERSION:
        _fail("This code panel was made by a newer VizorPlay.")
    template_id = str(value.get("id") or "")
    if not SLUG.match(template_id):
        _fail("A code panel's id is lowercase letters, digits and dashes.")
    name = _text(value.get("name"), "A code panel's name")
    raw_codes, raw_tags = value.get("codes"), value.get("tags", [])
    if not isinstance(raw_codes, list) or not 1 <= len(raw_codes) <= MAX_CODES:
        _fail(f"A code panel has 1 to {MAX_CODES} codes.")
    if not isinstance(raw_tags, list) or len(raw_tags) > MAX_TAGS:
        _fail(f"A code panel has at most {MAX_TAGS} tags.")

    tags, tag_keys = [], set()
    for item in raw_tags:
        if not isinstance(item, dict):
            _fail("Each tag must be an object.")
        _unknown(item, TAG_FIELDS, "A tag")
        tag = {"id": str(item.get("id") or ""), "label": _text(item.get("label"), "A tag's name"), "key": str(item.get("key") or "")}
        if not SLUG.match(tag["id"]) or tag["id"] in {t["id"] for t in tags}:
            _fail(f"Tag {tag['label']}: its id must be unique lowercase letters, digits and dashes.")
        if not re.fullmatch(r"[A-Z]", tag["key"]) or tag["key"] in tag_keys:
            _fail(f"Tag {tag['label']}: its key is one capital letter (pressed with Shift), used once.")
        tag_keys.add(tag["key"])
        if item.get("group") not in (None, ""):
            if not SLUG.match(str(item["group"])):
                _fail(f"Tag {tag['label']}: its group is lowercase letters, digits and dashes.")
            tag["group"] = str(item["group"])
        if item.get("outcome") not in (None, ""):
            if item["outcome"] not in OUTCOMES:
                _fail(f"Tag {tag['label']}: its outcome is Successful or Unsuccessful.")
            tag["outcome"] = item["outcome"]
        if item.get("flag") not in (None, ""):
            if item["flag"] not in FLAGS:
                _fail(f"Tag {tag['label']}: it can only set one of Filter's qualifier columns.")
            tag["flag"] = item["flag"]
        tags.append(tag)
    tag_ids = {tag["id"] for tag in tags}

    codes, code_keys = [], set()
    for item in raw_codes:
        if not isinstance(item, dict):
            _fail("Each code must be an object.")
        _unknown(item, CODE_FIELDS, "A code")
        label = _text(item.get("label"), "A code's name")
        code = {"id": str(item.get("id") or ""), "label": label, "kind": item.get("kind", "instant"),
                "type": _text(item.get("type") or label, f"Code {label}: its event type"),
                "outcome": item.get("outcome", "Successful"), "key": str(item.get("key") or ""),
                "colour": str(item.get("colour") or ""),
                "before": _whole(item.get("before", 5), f"Code {label}: its lead-in"),
                "after": _whole(item.get("after", 5), f"Code {label}: its lead-out")}
        if not SLUG.match(code["id"]) or code["id"] in {c["id"] for c in codes}:
            _fail(f"Code {label}: its id must be unique lowercase letters, digits and dashes.")
        if code["kind"] not in {"instant", "interval"}:
            _fail(f"Code {label}: it is an instant or an interval code.")
        if code["outcome"] not in OUTCOMES:
            _fail(f"Code {label}: its outcome is Successful or Unsuccessful.")
        if not re.fullmatch(r"[a-z]", code["key"]) or code["key"] in RESERVED_KEYS or code["key"] in code_keys:
            _fail(f"Code {label}: its key is one letter, not H or A, used once.")
        code_keys.add(code["key"])
        if not COLOUR.match(code["colour"]):
            _fail(f"Code {label}: its colour is written like #c8f135.")
        if code["kind"] == "interval":
            group = str(item.get("group") or code["id"])
            if not SLUG.match(group):
                _fail(f"Code {label}: its group is lowercase letters, digits and dashes.")
            code["group"] = group
        elif item.get("group") not in (None, ""):
            _fail(f"Code {label}: only interval codes have a group.")
        if item.get("tags"):
            if not isinstance(item["tags"], list) or len(item["tags"]) > 10 or not set(item["tags"]) <= tag_ids:
                _fail(f"Code {label}: it can add up to 10 of the panel's tags.")
            code["tags"] = list(dict.fromkeys(item["tags"]))
        for link in ("starts", "stops"):
            if item.get(link):
                if not isinstance(item[link], list) or len(item[link]) > 4:
                    _fail(f"Code {label}: it {link[:-1]}s at most 4 intervals.")
                code[link] = list(item[link])
        codes.append(code)

    kinds = {code["id"]: code["kind"] for code in codes}
    for code in codes:
        for target in code.get("stops", []):
            if kinds.get(target) != "interval" or target == code["id"]:
                _fail(f"Code {code['label']}: it can only stop another interval code of this panel.")
        starts = []
        for link in code.get("starts", []):
            if not isinstance(link, dict) or set(link) - {"code", "team"} or kinds.get(link.get("code")) != "interval" \
                    or link.get("code") == code["id"] or link.get("team", "same") not in TEAMS:
                _fail(f"Code {code['label']}: it can only start another interval code, for the same or the other team.")
            starts.append({"code": link["code"], "team": link.get("team", "same")})
        if starts:
            code["starts"] = starts
    return {"version": VERSION, "id": template_id, "name": name, "codes": codes, "tags": tags}


# ---------------------------------------------------------------------------
# The analyst's own templates
# ---------------------------------------------------------------------------
class TemplateLibrary:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    def _path(self, template_id: str) -> Path:
        if not SLUG.match(template_id or ""):
            raise ValueError("Unknown code panel.")
        return self.folder / f"{template_id}.json"

    def list(self) -> list[dict[str, Any]]:
        own = []
        if self.folder.is_dir():
            for path in sorted(self.folder.glob("*.json")):
                try:
                    own.append({**clean(json.loads(path.read_text(encoding="utf-8"))), "builtin": False})
                except (ValueError, json.JSONDecodeError):
                    continue  # a damaged file is skipped, never overwritten
        return [{**copy.deepcopy(template), "builtin": True} for template in BUILT_INS] + own

    def get(self, template_id: str) -> dict[str, Any]:
        for template in self.list():
            if template["id"] == template_id:
                return template
        raise ValueError("That code panel is no longer available.")

    def save(self, value: Any, replace: bool = False) -> dict[str, Any]:
        """Save a template under its name; a new name never replaces a built-in or (unless asked) another panel."""
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if key != "builtin"}
        template = clean(value)
        base = re.sub(r"[^a-z0-9]+", "-", template["name"].lower()).strip("-")[:32] or "panel"
        taken = {item["id"] for item in self.list()}
        template_id = template["id"] if replace and template["id"] not in BUILT_IN_IDS and template["id"] in taken else base
        if not replace or template_id in BUILT_IN_IDS:
            number = 2
            while template_id in taken:
                template_id = f"{base}-{number}"
                number += 1
        template["id"] = template_id
        self.folder.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.folder, prefix="saving-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(template, handle, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(template_id))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {**template, "builtin": False}

    def delete(self, template_id: str) -> None:
        if template_id in BUILT_IN_IDS:
            raise ValueError("Built-in code panels cannot be deleted.")
        path = self._path(template_id)
        if not path.is_file():
            raise ValueError("That code panel is no longer available.")
        trash = self.folder / "trash"
        trash.mkdir(exist_ok=True)
        os.replace(path, trash / f"{template_id}-{os.urandom(4).hex()}.json")
