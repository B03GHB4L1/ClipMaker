"""Parts of a clip: cut, reorder and repeat (docs/TELESTRATION_PLAN.md, M9).

A document may list `parts`: [{"from", "to"}], source frame ranges (`to` is
exclusive) in play order. The same frame may be in several parts. Without
`parts` the clip plays whole, so older documents are unchanged.

The parts joined end to end are the *cut clip*. It has its own frame numbers
(cut frame 0 is the first frame of the first part) and everything that counts
clip frames, such as freezes, boards and output time, counts cut frames. Only
the picture, the tracks and the sound need the real source frame.

ui/annotate/parts.js implements the same rules; tests/fixtures/parts_cases.json
is checked against both.
"""
from __future__ import annotations

from typing import Any

MAX_PARTS = 200


def clean(value: Any, frames: int) -> list[dict[str, int]] | None:
    """The parts to store, or None when they play the whole clip once. ValueError if they are wrong."""
    if value is None:
        return None
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PARTS:
        raise ValueError(f"A clip has between 1 and {MAX_PARTS} parts.")
    parts = []
    for part in value:
        if not isinstance(part, dict) or set(part) != {"from", "to"}:
            raise ValueError("Each part needs the frame it starts and ends on.")
        start, end = part["from"], part["to"]
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end)):
            raise ValueError("A part's frames must be whole numbers.")
        if not 0 <= start < end <= frames:
            raise ValueError("A part must be one or more frames of the clip.")
        parts.append({"from": start, "to": end})
    if parts == [{"from": 0, "to": frames}]:
        return None
    return parts


def spans(parts: list[dict[str, int]] | None, frames: int) -> list[tuple[int, int]]:
    return [(p["from"], p["to"]) for p in parts] if parts else [(0, frames)]


def cut_frames(parts: list[dict[str, int]] | None, frames: int) -> int:
    """How many frames the cut clip has."""
    return sum(end - start for start, end in spans(parts, frames))


def cut_clip(record: dict[str, Any], parts: list[dict[str, int]] | None) -> dict[str, Any]:
    """The clip record as the timeline sees it: the cut clip's length and frame count."""
    if not parts:
        return record
    count = cut_frames(parts, record["frames"])
    return {**record, "frames": count, "duration": count / record["fps"]}


def cut_to_source(frame: int, parts: list[dict[str, int]] | None, frames: int) -> int:
    """The source frame that cut frame `frame` shows."""
    if not parts:
        return min(frames - 1, max(0, frame))
    remaining = max(0, frame)
    for start, end in spans(parts, frames):
        if remaining < end - start:
            return start + remaining
        remaining -= end - start
    return parts[-1]["to"] - 1


def audio_plan(parts: list[dict[str, int]] | None, freezes: list[dict[str, Any]], fps: float, rate: int,
               frames: int) -> list[tuple[str, int, int]]:
    """The sound of the cut clip as ordered steps: ("copy", first sample, end sample) from the source sound
    (end -1: to the end of it) and ("silence", samples, 0) under each freeze."""
    by_frame = sorted(freezes, key=lambda f: f["atFrame"])
    steps: list[tuple[str, int, int]] = []
    offset = 0
    ranges = spans(parts, frames)
    for index, (start, end) in enumerate(ranges):
        cursor = start
        for freeze in by_frame:
            if offset <= freeze["atFrame"] < offset + (end - start):
                at = start + freeze["atFrame"] - offset
                if at > cursor:
                    steps.append(("copy", round(cursor / fps * rate), round(at / fps * rate)))
                    cursor = at
                steps.append(("silence", round(freeze["seconds"] * rate), 0))
        last = index == len(ranges) - 1 and not parts
        steps.append(("copy", round(cursor / fps * rate), -1 if last else round(end / fps * rate)))
        offset += end - start
    return steps
