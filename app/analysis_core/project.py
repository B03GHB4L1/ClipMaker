"""Project adapters shared by the analysis tabs.

``analysis_frame`` prepares a match CSV the way the analysis pages expect, and
``project_session`` maps a saved project to the session keys the copied
Tactical Lab code reads.
"""
from __future__ import annotations


def analysis_frame(frame):
    import pandas as pd
    from clipmaker_core import ensure_computed_event_flags
    from whoscored_scraper import _pitch_zone, _depth_zone
    frame = ensure_computed_event_flags(frame.copy())
    periods = {1: "FirstHalf", 2: "SecondHalf", 3: "FirstPeriodOfExtraTime", 4: "SecondPeriodOfExtraTime", 5: "PenaltyShootout"}
    if "period" in frame:
        def period_name(value):
            try:
                return periods.get(int(float(value)), str(value))
            except (ValueError, TypeError):
                return str(value)
        frame["period"] = frame["period"].map(period_name)
    for key, coordinate, resolver in (("pitch_zone", "y", _pitch_zone), ("depth_zone", "x", _depth_zone)):
        if key not in frame:
            if coordinate in frame:
                frame[key] = pd.to_numeric(frame[coordinate], errors="coerce").map(lambda value: resolver(value) if pd.notna(value) else "")
            else:
                frame[key] = ""
    return frame


def project_session(project: dict) -> dict:
    markers = project.get("markers") or {}
    videos = project.get("period_videos") or {}
    settings = project.get("filter_settings") or {}
    state = {
        "project_name": project.get("project_name", ""),
        "csv_path": project.get("csv_path", ""),
        "scraped_csv_path": project.get("csv_path", ""),
        "video_path": project.get("video_path", ""),
        "scraper_home_team": project.get("home_team", ""),
        "scraper_away_team": project.get("away_team", ""),
        "split_video": bool(any(videos.values())),
        "had_extra_time": bool(project.get("had_extra_time") or markers.get("ET1") or markers.get("ET2")),
        "had_penalties": bool(project.get("had_penalties") or markers.get("PEN")),
        "split_extra_time_video": bool(videos.get("ET1")),
        "split_penalties_video": bool(videos.get("PEN")),
        "extra_time_video_mode": "split" if videos.get("ET2") else "single",
        "timeline_corrections": settings.get("timeline_corrections", []),
        "light_mode": True,
    }
    for number, period in enumerate(("1H", "2H", "ET1", "ET2", "PEN"), 1):
        state[f"half{number}_time"] = markers.get(period, "")
        if number > 1:
            state[f"video{number}_path"] = videos.get(period, "")
    if videos.get("ET1") and not videos.get("ET2"):
        state["video4_path"] = videos["ET1"]
    if state["split_video"] and not state["video2_path"]:
        state["video2_path"] = project.get("video_path", "")
    for key in ("before_buffer", "after_buffer", "min_gap", "output_dir"):
        if key in settings:
            state[key] = settings[key]
    return state
