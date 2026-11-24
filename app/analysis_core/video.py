"""Where an event sits in the match video (moved from the Analyst Room's cut_clip)."""
from __future__ import annotations

from .frames import PERIOD_MAP

PERIOD_OFFSET = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0), 5: (120, 0)}
MARKER_KEYS = ("1H", "2H", "ET1", "ET2", "PEN")


def kickoff_times_from_project(project):
    """Period number -> kick-off clock text, from a saved project's markers."""
    markers = project.get("markers") or {}
    return {number: markers.get(key, "") for number, key in enumerate(MARKER_KEYS, 1)}


def clip_window(df_all, kickoffs, corrections, minute, second, period_str, before, after):
    """Return (period, start, duration) in video seconds for an event clip.

    ``kickoffs`` maps period number to kick-off clock text ("HH:MM:SS");
    ``corrections`` is the project's timeline corrections list.
    """
    from clipmaker_core import (
        apply_timeline_corrections, match_clock_to_video_time, normalise_timeline_corrections,
        resolve_period_starts_for_video, to_seconds,
    )
    period_int = PERIOD_MAP.get(period_str, 1)
    period_start = {number: to_seconds(text) for number, text in kickoffs.items() if text}
    period_start = resolve_period_starts_for_video(df_all, period_start)
    if period_int not in period_start:
        raise ValueError(f"No kick-off time set for period {period_int}.")
    base_ts = match_clock_to_video_time(int(minute), int(second), period_int, period_start, PERIOD_OFFSET)
    video_ts = apply_timeline_corrections(
        base_ts, int(minute) * 60 + int(second), period_int,
        normalise_timeline_corrections({"timeline_corrections": corrections or []}),
    )
    start_ts = max(0.0, video_ts - before)
    duration = (video_ts + after) - start_ts
    return period_int, start_ts, duration
