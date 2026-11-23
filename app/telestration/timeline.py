"""Output time with freezes, and how far a drawing's animation has got.

Freezes make the finished clip longer than the source clip, so there are two
clocks (docs/TELESTRATION_PLAN.md, "Two timelines"):

- source time: the clip's own frames;
- output time: what the viewer sees, source frames with freezes inserted.

A freeze at frame f holds that frame for `seconds`, starting where frame f
would start. Drawing times (`show.from` / `show.to`) are output seconds.

ui/annotate/timeline.js implements the same rules for the live preview;
tests/fixtures/timeline_cases.json is checked against both.
"""
from __future__ import annotations

import math
from typing import Any

PULSE_SECONDS = 1.2
SLIDE_DISTANCE = 0.04  # fraction of the frame height a slide-in travels
DEFAULT_ANIM_SECONDS = 0.5

EASES = {
    "linear": lambda p: p,
    "ease-out": lambda p: 1 - (1 - p) ** 3,
    "ease-in-out": lambda p: 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2,
}


def _sorted(freezes: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return sorted(freezes or [], key=lambda freeze: freeze["atFrame"])


def total_seconds(duration: float, freezes: list[dict[str, Any]] | None) -> float:
    return duration + sum(freeze["seconds"] for freeze in freezes or [])


def freeze_start(frame: int, fps: float, freezes: list[dict[str, Any]] | None) -> float:
    """Output time where frame `frame` starts (its freeze, if it has one, starts here)."""
    return frame / fps + sum(f["seconds"] for f in freezes or [] if f["atFrame"] < frame)


def play_start(frame: int, fps: float, freezes: list[dict[str, Any]] | None) -> float:
    """Output time where frame `frame` starts playing, after any freeze on it."""
    return frame / fps + sum(f["seconds"] for f in freezes or [] if f["atFrame"] <= frame)


def output_to_source(t: float, fps: float, duration: float, frames: int,
                     freezes: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The source frame shown at output time `t`, and the freeze holding it, if any."""
    held = 0.0
    for freeze in _sorted(freezes):
        start = freeze["atFrame"] / fps + held
        if t < start:
            break
        if t < start + freeze["seconds"]:
            return {"time": freeze["atFrame"] / fps, "frame": freeze["atFrame"], "freeze": freeze["atFrame"],
                    "freezeStart": start}
        held += freeze["seconds"]
    time = min(duration, max(0.0, t - held))
    frame = min(frames - 1, max(0, math.floor(time * fps + 1e-6)))
    return {"time": time, "frame": frame, "freeze": None, "freezeStart": None}


def animation(item: dict[str, Any], t: float) -> dict[str, Any] | None:
    """How a drawing looks at output time `t`, or None when it is hidden.

    alpha: opacity multiplier; draw: share of the path drawn (draw-on);
    scale: size multiplier (grow); offsetY: slide-in offset as a fraction of the
    frame height; pulse: 0-1 phase of the pulse loop, or None.
    """
    show = item["show"]
    start, end = show["from"], show["to"]
    if t < start - 1e-3 or t > end + 1e-3:
        return None
    seconds = show.get("animSeconds", DEFAULT_ANIM_SECONDS)
    ease = EASES[show.get("ease", "ease-out")]

    def progress(span: float) -> float:
        return ease(min(1.0, max(0.0, span / seconds))) if seconds > 0 else 1.0

    state = {"alpha": 1.0, "draw": 1.0, "scale": 1.0, "offsetY": 0.0, "pulse": None}
    coming = progress(t - start)
    animate = show.get("animate", "none")
    if animate == "fade":
        state["alpha"] *= coming
    elif animate == "draw":
        if item["kind"] in {"arrow", "line", "freehand", "zone", "ring", "shape"}:
            state["draw"] = coming
        else:
            state["alpha"] *= coming  # nothing to trace: fade instead
    elif animate == "grow":
        state["scale"] = coming
    elif animate == "slide":
        state["offsetY"] = (1 - coming) * SLIDE_DISTANCE
        state["alpha"] *= coming
    if show.get("animateOut", "none") == "fade":
        state["alpha"] *= progress(end - t)
    if show.get("pulse"):
        state["pulse"] = ((t - start) % PULSE_SECONDS) / PULSE_SECONDS
    return state
