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

Box size is the fourth rule (2026-11-18, from a real clip): when the tracker
loses a player it can let its box swell over a crowd, and nothing else notices
because the box still holds shirts. A box more than SIZE_DOUBT times the
seed's area is doubtful (so is a box shrunk below SHRINK_DOUBT of it); more
than SIZE_STOP times is not the player any more, so tracking stops there.
A box's shape is not checked: it varies too much as a player runs and turns.
"""
from __future__ import annotations

from collections import deque
from typing import Any

TRACKED, KEYFRAME, REVIEW, LOST = 0, 1, 2, 3
COLOUR_LIMIT = 0.6  # Bhattacharyya distance to the seed's shirt colour
COLOUR_SECONDS = 0.2
DOUBT_SECONDS = 1.0
SIZE_DOUBT = 1.8  # box area against the seed's: beyond this the tracker may be wrong
SIZE_STOP = 4.0  # beyond this the box is not one player: stop at once
SHRINK_DOUBT = 0.2  # a box shrunk to this share of the seed's area may have slipped onto a limb
SHRINK_STOP = 0.08


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
        self.seed_area = 0.0

    def push(self, box: tuple[float, float, float, float], *, ok: bool = True, confidence: float = 1.0,
             colour: float | None = None, edge: bool = False, cut: bool = False) -> tuple[str, Any]:
        """("row", row) to store, or ("stop", reason) to end the span before this frame."""
        area = max(box[2] * box[3], 1e-9)
        if self.first:
            self.first = False
            self.seed_area = area
            return "row", row(box, 1.0, KEYFRAME)
        if cut:
            return "stop", "scene-cut"
        grown = area / self.seed_area  # 1 = the seed's size
        if grown > SIZE_STOP or grown < SHRINK_STOP:
            return "stop", "lost"
        wrong_size = grown > SIZE_DOUBT or grown < SHRINK_DOUBT
        self.colours.append(1.0 if colour is None else colour)
        colour_off = len(self.colours) == self.colours.maxlen and sum(self.colours) / len(self.colours) > COLOUR_LIMIT
        doubtful = not ok or colour_off or edge or wrong_size
        self.doubt = self.doubt + 1 if doubtful else 0
        if self.doubt >= self.doubt_limit:
            return "stop", "lost"
        return "row", row(box, confidence, REVIEW if doubtful else TRACKED)


def span_end(keyframes: dict[int, Any], start: int, limit: int) -> int:
    """Last frame to track from the keyframe at `start`: up to the next keyframe, or `limit`."""
    later = [frame for frame in keyframes if frame > start]
    return min(limit, min(later) - 1) if later else limit


# ---------------------------------------------------------------------------
# M5: tracking quality. A span between two keyframes is tracked forwards from
# the first and backwards from the second; the two are blended so the drawing
# arrives exactly on the next keyframe instead of jumping to it. Short holes
# are bridged, and the path is lightly smoothed (Metrica uses about 0.44 s).
# ---------------------------------------------------------------------------
GAP_SECONDS = 0.5
SMOOTH_SECONDS = 0.44
DISAGREE = 0.75  # passes further apart than this share of the player's box height follow different players

Row = list  # [footX, footY, w, h, confidence, state]


def blend(forward: list[Row | None], backward: list[Row | None]) -> list[Row | None]:
    """Per frame of the span: the forward pass leans on the first keyframe, the backward pass on the next one.
    Both lists are indexed from the span's first frame and are as long as the span."""
    count = len(forward)
    result: list[Row | None] = []
    for index in range(count):
        ahead, behind = forward[index], backward[index]
        if ahead is None or behind is None:
            result.append(ahead or behind)
            continue
        if ahead[5] == KEYFRAME:
            result.append(ahead)
            continue
        share = (index + 1) / (count + 1)  # weight of the backward pass: 0 at the first keyframe, 1 at the next
        apart = ((ahead[0] - behind[0]) ** 2 + (ahead[1] - behind[1]) ** 2) ** 0.5
        if apart > DISAGREE * max(ahead[3], behind[3], 1e-6):
            # Each pass is on a different player: trust the one nearer its own keyframe, and ask.
            chosen = behind if share > 0.5 else ahead
            result.append(row(tuple(chosen[:4]), min(ahead[4], behind[4]), REVIEW))
            continue
        box = tuple(a + (b - a) * share for a, b in zip(ahead[:4], behind[:4]))
        doubtful = ahead[5] == REVIEW and behind[5] == REVIEW
        result.append(row(box, max(ahead[4], behind[4]), REVIEW if doubtful else TRACKED))
    return result


def fill_gaps(rows: list[Row | None], fps: float) -> list[Row | None]:
    """Bridge holes of up to GAP_SECONDS between two known frames in a straight line, marked for review."""
    limit = max(1, round(GAP_SECONDS * fps))
    result = list(rows)
    index = 0
    while index < len(result):
        if result[index] is not None:
            index += 1
            continue
        end = index
        while end < len(result) and result[end] is None:
            end += 1
        before = result[index - 1] if index > 0 else None
        after = result[end] if end < len(result) else None
        if before is not None and after is not None and end - index <= limit:
            steps = end - index + 1
            for offset in range(1, steps):
                t = offset / steps
                box = tuple(a + (b - a) * t for a, b in zip(before[:4], after[:4]))
                result[index + offset - 1] = row(box, 0.0, REVIEW)
        index = end
    return result


def smooth(rows: list[Row | None], fps: float, after: Row | None = None) -> list[Row | None]:
    """A centred moving average over about SMOOTH_SECONDS. Keyframes stay exactly where they were placed,
    and the window narrows towards the ends of each run, so nothing is pulled off a placed position.
    `after` is the keyframe just past the last row, if any: it anchors the end like the first keyframe."""
    radius = max(0, round(SMOOTH_SECONDS * fps / 2))
    series = list(rows) + ([after] if after is not None and rows and rows[-1] is not None else [])
    result = list(series)
    if radius:
        index = 0
        while index < len(series):
            if series[index] is None:
                index += 1
                continue
            end = index
            while end < len(series) and series[end] is not None:
                end += 1
            for i in range(index, end):
                reach = min(radius, i - index, end - 1 - i)
                if series[i][5] == KEYFRAME or reach <= 0:
                    continue
                window = series[i - reach:i + reach + 1]
                box = tuple(sum(r[k] for r in window) / len(window) for k in range(4))
                result[i] = row(box, series[i][4], series[i][5])
            index = end
    return result[:len(rows)]


def finish(start: int, count: int, fps: float, forward: list[Row], forward_stop: dict | None,
           backward: list[Row | None] | None = None, after: Row | None = None) -> tuple[list[Row | None], dict | None]:
    """Combine the passes over the `count` frames from `start`: (rows from `start`, where coverage stops).
    `backward` (indexed from `start`, `count` long) is None when there is no later keyframe to track from;
    `after` is that keyframe's row."""
    ahead: list[Row | None] = list(forward) + [None] * (count - len(forward))
    rows = blend(ahead, backward) if backward is not None else ahead
    rows = smooth(fill_gaps(rows, fps), fps, after)
    hole = next((index for index, value in enumerate(rows) if value is None), None)
    stopped = None
    if hole is not None:
        reason = forward_stop["reason"] if forward_stop else "lost"
        stopped = {"frame": start + hole, "reason": reason}
    while rows and rows[-1] is None:
        rows.pop()
    return rows, stopped
