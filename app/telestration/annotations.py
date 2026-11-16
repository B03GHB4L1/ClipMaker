"""Validate the drawings saved for one clip.

The editor sends the whole document on every save. Anything that does not
match this schema is refused rather than repaired, so a bad request can never
overwrite good drawings with something half-understood.

Coordinates are fractions of the frame (0 = left/top, 1 = right/bottom), with
a margin so shapes may hang slightly off the picture. Sizes (`width`, `size`)
are pixels on a 1080-pixel-high frame and scale with the video.
"""
from __future__ import annotations

import math
import re
from typing import Any

VERSION = 1
KINDS = {"ring", "spotlight", "arrow", "line", "freehand", "text", "zone"}
ANIMATIONS = {"none", "fade", "draw", "grow", "slide"}  # how a drawing comes in
EXIT_ANIMATIONS = {"none", "fade"}
EASES = {"linear", "ease-out", "ease-in-out"}
PULSE_KINDS = {"ring", "spotlight", "zone"}
MAX_FREEZES = 50
MAX_TRACKS = 40
MAX_KEYFRAMES = 500
OFFSET = 1.0  # a linked point may sit up to a frame's width or height from its player's feet
FREEZE_SECONDS = (0.04, 60.0)
MAX_ITEMS = 300
MAX_POINTS = {"ring": 1, "spotlight": 1, "arrow": 2, "line": 2, "freehand": 2000, "text": 1, "zone": 40}
MIN_POINTS = {"ring": 1, "spotlight": 1, "arrow": 2, "line": 2, "freehand": 2, "text": 1, "zone": 3}
MAX_TEXT = 300
COORD_MIN, COORD_MAX = -0.5, 1.5
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

STYLE_RULES: dict[str, tuple[str, float, float]] = {
    # key: (type, minimum, maximum) for numbers; colours are checked separately.
    "width": ("number", 1, 40),
    "opacity": ("number", 0, 1),
    "fillOpacity": ("number", 0, 1),
    "size": ("number", 8, 160),
}
COLOUR_KEYS = {"stroke", "fill", "color", "background"}
FLAG_KEYS = {"dashed", "bold"}


def _number(value: Any, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a number.")
    if not low <= value <= high:
        raise ValueError(f"{what} must be between {low:g} and {high:g}.")
    return float(value)


def _point(value: Any, what: str, tracks: set[str]) -> list[float] | dict[str, Any]:
    """A fixed [x, y], or a point linked to a tracked player: {"track", "dx", "dy"}."""
    if isinstance(value, dict):
        if set(value) != {"track", "dx", "dy"} or value["track"] not in tracks:
            raise ValueError(f"{what} is linked to a player that is not tracked.")
        return {"track": value["track"], "dx": round(_number(value["dx"], -OFFSET, OFFSET, what), 5),
                "dy": round(_number(value["dy"], -OFFSET, OFFSET, what), 5)}
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{what} must be an [x, y] pair.")
    return [round(_number(v, COORD_MIN, COORD_MAX, what), 5) for v in value]


def clean_box(value: Any, what: str) -> list[float]:
    """[footX, footY, w, h] as fractions of the frame."""
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{what} must be [footX, footY, width, height].")
    fx, fy = (_number(v, COORD_MIN, COORD_MAX, what) for v in value[:2])
    w, h = (_number(v, 0.001, 1.0, what) for v in value[2:])
    return [round(fx, 5), round(fy, 5), round(w, 5), round(h, 5)]


def _tracks(value: Any, frames: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_TRACKS:
        raise ValueError(f"A clip can follow up to {MAX_TRACKS} players.")
    clean = []
    for track in value:
        if not isinstance(track, dict) or set(track) - {"id", "label", "keyframes", "from", "boxes"}:
            raise ValueError("A followed player has unknown settings.")
        track_id = track.get("id")
        if not isinstance(track_id, str) or not ITEM_ID.match(track_id):
            raise ValueError("Each followed player needs a short id.")
        label = track.get("label", "")
        if not isinstance(label, str) or len(label) > 40:
            raise ValueError("A player label can have up to 40 characters.")
        keyframes = track.get("keyframes")
        if not isinstance(keyframes, dict) or not 1 <= len(keyframes) <= MAX_KEYFRAMES:
            raise ValueError("A followed player needs at least one placed frame.")
        clean_keys = {}
        for key, box in keyframes.items():
            if not isinstance(key, str) or not key.isdigit() or int(key) >= frames:
                raise ValueError("A placed frame must be a frame of the clip.")
            clean_keys[str(int(key))] = clean_box(box, "A placed player box")
        start = track.get("from", 0)
        boxes = track.get("boxes", [])
        if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start < frames:
            raise ValueError("Tracking must start on a frame of the clip.")
        if not isinstance(boxes, list) or start + len(boxes) > frames:
            raise ValueError("Tracking runs past the end of the clip.")
        clean_boxes: list[list[float] | None] = []
        for row in boxes:
            if row is None:
                clean_boxes.append(None)
                continue
            if not isinstance(row, list) or len(row) != 6 or row[5] not in (0, 1, 2, 3) or isinstance(row[5], bool):
                raise ValueError("A tracked frame must be [footX, footY, width, height, confidence, state].")
            clean_boxes.append(clean_box(row[:4], "A tracked player box") + [round(_number(row[4], 0, 1, "Confidence"), 3), row[5]])
        entry = {"id": track_id, "keyframes": clean_keys, "from": start, "boxes": clean_boxes}
        if label:
            entry["label"] = label
        clean.append(entry)
    if len({track["id"] for track in clean}) != len(clean):
        raise ValueError("Two followed players share the same id.")
    return clean


def _style(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("A drawing style must be an object.")
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if key in COLOUR_KEYS:
            if key == "background" and item is None:
                clean[key] = None  # transparent text background
            elif isinstance(item, str) and COLOUR.match(item):
                clean[key] = item.lower()
            else:
                raise ValueError(f"Style {key} must be a colour like #ffd400.")
        elif key in FLAG_KEYS:
            if not isinstance(item, bool):
                raise ValueError(f"Style {key} must be true or false.")
            clean[key] = item
        elif key in STYLE_RULES:
            _, low, high = STYLE_RULES[key]
            clean[key] = _number(item, low, high, f"Style {key}")
        else:
            raise ValueError(f"Unknown style setting: {key}.")
    return clean


def _geometry(kind: str, value: Any) -> dict[str, float]:
    if kind not in {"ring", "spotlight"}:
        if value not in (None, {}):
            raise ValueError(f"A {kind} has no geometry settings.")
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"A {kind} needs its size.")
    clean = {
        "rx": _number(value.get("rx"), 0.002, 0.5, "Ring width"),
        "ry": _number(value.get("ry"), 0.001, 0.5, "Ring height"),
    }
    if kind == "spotlight":
        clean["h"] = _number(value.get("h", 0.3), 0.02, 1.0, "Spotlight height")
    extra = set(value) - set(clean)
    if extra:
        raise ValueError(f"Unknown {kind} setting: {sorted(extra)[0]}.")
    return clean


def _show(value: Any, limit: float, kind: str) -> dict[str, Any]:
    """`limit` is the output length in seconds: the clip plus its freezes."""
    if not isinstance(value, dict):
        raise ValueError("A drawing needs the time it shows from and to.")
    start = _number(value.get("from"), 0, limit, "Show-from time")
    end = _number(value.get("to"), 0, limit, "Show-to time")
    if end < start:
        raise ValueError("A drawing cannot end before it starts.")
    animate = value.get("animate", "none")
    if animate not in ANIMATIONS:
        raise ValueError(f"Unknown animation: {animate}.")
    exit_animation = value.get("animateOut", "none")
    if exit_animation not in EXIT_ANIMATIONS:
        raise ValueError(f"Unknown exit animation: {exit_animation}.")
    ease = value.get("ease", "ease-out")
    if ease not in EASES:
        raise ValueError(f"Unknown easing: {ease}.")
    pulse = value.get("pulse", False)
    if not isinstance(pulse, bool) or (pulse and kind not in PULSE_KINDS):
        raise ValueError(f"A {kind} cannot pulse.")
    extra = set(value) - {"from", "to", "animate", "animateOut", "animSeconds", "ease", "pulse"}
    if extra:
        raise ValueError(f"Unknown timing setting: {sorted(extra)[0]}.")
    clean: dict[str, Any] = {"from": round(start, 3), "to": round(end, 3), "animate": animate}
    if exit_animation != "none":
        clean["animateOut"] = exit_animation
    if animate != "none" or exit_animation != "none":
        clean["animSeconds"] = round(_number(value.get("animSeconds", 0.5), 0.05, 5, "Animation length"), 3)
        clean["ease"] = ease
    if pulse:
        clean["pulse"] = True
    return clean


def _freezes(value: Any, frames: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_FREEZES:
        raise ValueError(f"A clip can hold up to {MAX_FREEZES} freezes.")
    clean = []
    for freeze in value:
        if not isinstance(freeze, dict) or set(freeze) != {"atFrame", "seconds"}:
            raise ValueError("Each freeze needs its frame and length only.")
        frame = freeze["atFrame"]
        if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < frames:
            raise ValueError("A freeze must be on a frame of the clip.")
        seconds = _number(freeze["seconds"], *FREEZE_SECONDS, "Freeze length")
        clean.append({"atFrame": frame, "seconds": round(seconds, 3)})
    if len({freeze["atFrame"] for freeze in clean}) != len(clean):
        raise ValueError("Two freezes are on the same frame.")
    return sorted(clean, key=lambda freeze: freeze["atFrame"])


def _item(value: Any, limit: float, tracks: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Each drawing must be an object.")
    item_id = value.get("id")
    if not isinstance(item_id, str) or not ITEM_ID.match(item_id):
        raise ValueError("Each drawing needs a short id.")
    kind = value.get("kind")
    if kind not in KINDS:
        raise ValueError(f"Unknown drawing type: {kind}.")
    points = value.get("points")
    if not isinstance(points, list) or not MIN_POINTS[kind] <= len(points) <= MAX_POINTS[kind]:
        raise ValueError(f"A {kind} needs {MIN_POINTS[kind]} to {MAX_POINTS[kind]} points.")
    clean = {
        "id": item_id,
        "kind": kind,
        "points": [_point(p, f"A {kind} point", tracks) for p in points],
        "style": _style(value.get("style")),
        "show": _show(value.get("show"), limit, kind),
    }
    geometry = _geometry(kind, value.get("geometry"))
    if geometry:
        clean["geometry"] = geometry
    if kind == "text":
        text = value.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError(f"Text must have 1 to {MAX_TEXT} characters.")
        clean["text"] = text
    elif "text" in value:
        raise ValueError(f"A {kind} has no text.")
    known = {"id", "kind", "points", "style", "show", "geometry", "text"}
    extra = set(value) - known
    if extra:
        raise ValueError(f"Unknown drawing setting: {sorted(extra)[0]}.")
    return clean


def clean_document(value: Any, duration: float, frames: int) -> dict[str, Any]:
    """The document to store, or ValueError explaining what is wrong.

    `duration` is the clip length in seconds and `frames` its frame count.
    Drawing times are output seconds, so they may run into the freezes' time.
    """
    if not isinstance(value, dict):
        raise ValueError("Annotations must be an object.")
    if value.get("version") != VERSION:
        raise ValueError("These annotations were made by a different version of the editor.")
    items = value.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError(f"A clip can hold up to {MAX_ITEMS} drawings.")
    freezes = _freezes(value.get("freezes", []), frames)
    limit = duration + sum(freeze["seconds"] for freeze in freezes) + 0.5
    tracks = _tracks(value.get("tracks", []), frames)
    track_ids = {track["id"] for track in tracks}
    clean_items = [_item(item, limit, track_ids) for item in items]
    ids = [item["id"] for item in clean_items]
    if len(ids) != len(set(ids)):
        raise ValueError("Two drawings share the same id.")
    extra = set(value) - {"version", "items", "freezes", "tracks"}
    if extra:
        raise ValueError(f"Unknown annotation setting: {sorted(extra)[0]}.")
    clean = {"version": VERSION, "items": clean_items, "freezes": freezes}
    if tracks:
        clean["tracks"] = tracks
    return clean


def empty_document() -> dict[str, Any]:
    return {"version": VERSION, "items": [], "freezes": []}
