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
ANIMATIONS = {"none"}  # M2 adds draw-on, fade, grow, slide and pulse.
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


def _point(value: Any, what: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{what} must be an [x, y] pair.")
    return [round(_number(v, COORD_MIN, COORD_MAX, what), 5) for v in value]


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


def _show(value: Any, duration: float) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("A drawing needs the time it shows from and to.")
    limit = duration + 0.5
    start = _number(value.get("from"), 0, limit, "Show-from time")
    end = _number(value.get("to"), 0, limit, "Show-to time")
    if end < start:
        raise ValueError("A drawing cannot end before it starts.")
    animate = value.get("animate", "none")
    if animate not in ANIMATIONS:
        raise ValueError(f"Unknown animation: {animate}.")
    return {"from": round(start, 3), "to": round(end, 3), "animate": animate}


def _item(value: Any, duration: float) -> dict[str, Any]:
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
        "points": [_point(p, f"A {kind} point") for p in points],
        "style": _style(value.get("style")),
        "show": _show(value.get("show"), duration),
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


def clean_document(value: Any, duration: float) -> dict[str, Any]:
    """The document to store, or ValueError explaining what is wrong.

    `duration` is the clip length in seconds; drawings may not be timed past it.
    """
    if not isinstance(value, dict):
        raise ValueError("Annotations must be an object.")
    if value.get("version") != VERSION:
        raise ValueError("These annotations were made by a different version of the editor.")
    items = value.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError(f"A clip can hold up to {MAX_ITEMS} drawings.")
    clean_items = [_item(item, duration) for item in items]
    ids = [item["id"] for item in clean_items]
    if len(ids) != len(set(ids)):
        raise ValueError("Two drawings share the same id.")
    freezes = value.get("freezes", [])
    if freezes != []:
        raise ValueError("Freeze frames arrive in a later version of the editor.")
    extra = set(value) - {"version", "items", "freezes"}
    if extra:
        raise ValueError(f"Unknown annotation setting: {sorted(extra)[0]}.")
    return {"version": VERSION, "items": clean_items, "freezes": []}


def empty_document() -> dict[str, Any]:
    return {"version": VERSION, "items": [], "freezes": []}
