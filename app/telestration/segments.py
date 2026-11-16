"""Turning a tracker's raw output into rows the editor can trust (no OpenCV).

A track row is [footX, footY, w, h, confidence, state]: the bottom-centre of
the player's box and its size, as fractions of the frame. States:

    0 tracked   1 keyframe (placed or confirmed by the analyst)
    2 review    the tracker may be wrong here; the analyst should check
    3 lost      tracking stopped here (scene cut or lost player)

Review rules come from the M0 spike (docs/M0_TRACKING_SPIKE.md): the tracker's
own loss signal, a grass-masked shirt-colour check that stays different for
about 0.2 s, and a box squeezed against the frame edge. A scene cut stops
tracking at once; a second of uninterrupted doubt stops it too, so a drawing
never wanders off on its own for long.
"""
from __future__ import annotations

from collections import deque
from typing import Any

TRACKED, KEYFRAME, REVIEW, LOST = 0, 1, 2, 3
COLOUR_LIMIT = 0.6  # Bhattacharyya distance to the seed's shirt colour
COLOUR_SECONDS = 0.2
DOUBT_SECONDS = 1.0


def row(box: tuple[float, float, float, float], confidence: float, state: int) -> list[float]:
    fx, fy, w, h = box
    return [round(fx, 5), round(fy, 5), round(w, 5), round(h, 5), round(min(1.0, max(0.0, confidence)), 3), state]


class Flagger:
    """Feed it one frame at a time; it says what to store, or that tracking should stop."""

    def __init__(self, fps: float) -> None:
        self.colours: deque[float] = deque(maxlen=max(3, round(COLOUR_SECONDS * fps)))
        self.doubt_limit = max(2, round(DOUBT_SECONDS * fps))
        self.doubt = 0
        self.first = True

    def push(self, box: tuple[float, float, float, float], *, ok: bool = True, confidence: float = 1.0,
             colour: float | None = None, edge: bool = False, cut: bool = False) -> tuple[str, Any]:
        """("row", row) to store, or ("stop", reason) to end the span before this frame."""
        if self.first:
            self.first = False
            return "row", row(box, 1.0, KEYFRAME)
        if cut:
            return "stop", "scene-cut"
        self.colours.append(1.0 if colour is None else colour)
        colour_off = len(self.colours) == self.colours.maxlen and sum(self.colours) / len(self.colours) > COLOUR_LIMIT
        doubtful = not ok or colour_off or edge
        self.doubt = self.doubt + 1 if doubtful else 0
        if self.doubt >= self.doubt_limit:
            return "stop", "lost"
        return "row", row(box, confidence, REVIEW if doubtful else TRACKED)


def span_end(keyframes: dict[int, Any], start: int, limit: int) -> int:
    """Last frame to track from the keyframe at `start`: up to the next keyframe, or `limit`."""
    later = [frame for frame in keyframes if frame > start]
    return min(limit, min(later) - 1) if later else limit
