"""Project adapter for the existing, shared analytical workspaces."""

from __future__ import annotations

import json
import base64
from functools import lru_cache
import os
import re
import sys
from pathlib import Path


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


def session_video(period: int) -> str:
    import streamlit as st
    if st.session_state.get("split_video") and period > 1:
        return st.session_state.get(f"video{period}_path") or st.session_state.get("video2_path", "")
    return st.session_state.get("video_path", "")


def load_project(project_id: str) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", project_id):
        raise ValueError("Open a saved project in Intake first.")
    root = Path(os.environ["CLIPMAKER_DATA_DIR"])
    path = root / "projects" / project_id / "project.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    legacy = root / "matches.json"
    if legacy.is_file():
        for project in json.loads(legacy.read_text(encoding="utf-8")):
            if project.get("id") == project_id:
                return project
    raise ValueError("This project could not be found.")


def sync_project_state():
    import streamlit as st

    if not os.environ.get("CLIPMAKER_ANALYSIS_MODE"):
        return
    project_id = str(st.query_params.get("project", ""))
    project = load_project(project_id)
    identity = (project_id, project.get("updated_at"))
    if st.session_state.get("_project_revision") == identity:
        return
    if st.session_state.get("_project_revision", (None,))[0] != project_id:
        for key in list(st.session_state):
            if key != "_project_revision":
                del st.session_state[key]
    st.session_state.update(project_session(project))
    root = Path(os.environ["CLIPMAKER_DATA_DIR"])
    projects = []
    legacy = root / "matches.json"
    if legacy.is_file():
        projects.extend(json.loads(legacy.read_text(encoding="utf-8")))
    projects.extend(json.loads(path.read_text(encoding="utf-8")) for path in (root / "projects").glob("*/project.json"))
    projects = list({item["id"]: item for item in projects}.values())
    st.session_state["match_setup_by_csv"] = {
        item["csv_path"]: project_session(item) for item in projects if item.get("csv_path")
    }
    st.session_state["multi_scraped_csv_paths"] = list(dict.fromkeys(
        item["csv_path"] for item in projects if item.get("csv_path") and Path(item["csv_path"]).is_file()
    ))
    st.session_state["_project_revision"] = identity


@lru_cache(maxsize=1)
def analysis_font_css():
    relative = Path("ui/assets/fonts/GeistMono-Variable.ttf")
    roots = [Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent]
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    font = next((root / relative for root in roots if (root / relative).is_file()), None)
    if font is None:
        raise FileNotFoundError("Bundled Geist Mono font is missing.")
    encoded = base64.b64encode(font.read_bytes()).decode("ascii")
    return '<style>@font-face{font-family:"Geist Mono";src:url(data:font/ttf;base64,' + encoded + ') format("truetype");font-weight:100 900;font-display:swap;}</style>'


def compact_analysis_style():
    import streamlit as st

    st.markdown(analysis_font_css() + """<style>
    :root {--cm-bg:#f4f4f0!important;--cm-surface:#fff!important;--cm-border:#d7d8d2!important;--cm-title:#151916!important;--cm-subtitle:#62655d!important;}
    html, body, body [class*='css'], body .block-container,
    body [data-testid='stApp'], body [data-testid='stAppViewContainer'],
    body [data-testid='stAppViewBlockContainer'], body [data-testid='stMain'] {background:#f4f4f0!important;}
    [data-testid='stMainBlockContainer'] {padding-top:4px!important;}
    header[data-testid='stHeader'], [data-testid='stSidebar'], .cm-top-nav {display:none!important;}
    .block-container {padding:0.25rem 1rem 1rem!important;max-width:1600px!important;}
    .project-analysis-title {margin:0!important;font:600 22px Arial,sans-serif!important;letter-spacing:0!important;}
    .stApp h1.project-analysis-title {text-transform:none!important;}
    .stApp p, .stApp [data-baseweb='select'], .stApp [data-baseweb='radio'] {font-family:Arial,sans-serif!important;letter-spacing:0!important;}
    .stApp [data-baseweb='select'] > div, .stApp [data-baseweb='input'],
    .stApp input, .stApp textarea {background:#fff!important;color:#151916!important;border-color:#d7d8d2!important;border-radius:4px!important;}
    .stApp [data-testid='stExpander'], .stApp .cm-stats-bar, .stApp .cm-event-panel,
    .stApp .cm-context-bar, .stApp .cm-support-panel {background:#fff!important;border-color:#d7d8d2!important;}
    .stApp .cm-stats-cell {padding:10px!important;}
    .stApp .cm-stats-home {color:#235a9b!important;} .stApp .cm-stats-away {color:#ba3c35!important;}
    .stApp .stTabs [aria-selected='true'] {background:#eaf2da!important;color:#2f5d16!important;}
    .stApp .stTabs [data-baseweb='tab']:hover {background:#eef0e9!important;}
    [data-testid='stMarkdown'] hr {margin:0.25rem 0!important;}
    [data-testid='stElementContainer']:has(iframe[height='0']) {display:none!important;}
    h1 {font-size:24px!important;} h2 {font-size:20px!important;} h3 {font-size:17px!important;}
    [data-testid='stVerticalBlock'] {gap:0.65rem!important;}
    .stTabs [data-baseweb='tab-list'] {gap:8px!important;}
    .stTabs [data-baseweb='tab'] {font-size:12px!important;padding:8px!important;}
    [data-testid='stWidgetLabel'] p, .stTabs p {letter-spacing:0!important;}
    .stApp :is(h1,h2,h3,p,label,button,input,textarea),
    .stApp [data-baseweb='select'] :is(div,span) {font-family:Arial,Helvetica,sans-serif!important;letter-spacing:0!important;}
    .stApp :is(h1,h2,h3), .stApp [data-testid='stWidgetLabel'] p {text-transform:none!important;}
    .stApp [data-testid='stWidgetLabel'] p {font-size:13px!important;line-height:1.4!important;}
    .stApp :is(.cm-stats-label,.cm-stats-home,.cm-stats-away) {font-family:Arial,Helvetica,sans-serif!important;letter-spacing:0!important;text-transform:none!important;}
    .stApp .cm-stats-label {color:#62655d!important;font-size:12px!important;}
    .stApp .stTabs p {text-transform:none!important;}
    .stTabs [data-baseweb='tab-list'] {overflow-x:auto!important;flex-wrap:nowrap!important;}
    .stTabs [data-baseweb='tab'] {white-space:nowrap!important;flex-shrink:0!important;}
    html, body, .stApp, body .block-container,
    body [data-testid='stAppViewContainer'], body [data-testid='stAppViewBlockContainer'], body [data-testid='stMain'] {background:#f7f7f7!important;}
    .stApp :is(h1,h2,h3,h4,p,label,button,input,textarea,code,small,strong),
    .stApp [data-baseweb='select'] :is(div,span),
    .stApp :is(.cm-stats-label,.cm-stats-home,.cm-stats-away,.cm-stats-share) {font-family:'Geist Mono',monospace!important;letter-spacing:0!important;}
    .stApp h1.project-analysis-title {font-weight:450!important;font-size:26px!important;line-height:1.25!important;}
    .stApp h2, .stApp h3 {font-weight:450!important;}
    .stApp .stTabs [data-baseweb='tab-list'] {gap:4px!important;}
    .stApp .stTabs [data-baseweb='tab'] {padding:8px 10px!important;border-radius:3px!important;}
    .stApp .stTabs [aria-selected='true'] {background:#171817!important;color:#fff!important;}
    .stApp .stTabs [aria-selected='true'] p {color:#fff!important;}
    .stApp .stTabs [aria-selected='true']:hover {background:#303330!important;color:#fff!important;}
    .stApp :is(.cm-stats-label,[data-testid='stWidgetLabel'] p) {font-size:11px!important;}
    .stApp :is(.cm-stats-home,.cm-stats-away) {font-size:17px!important;font-weight:450!important;}
    </style>""", unsafe_allow_html=True)


def preserve_analysis_controls(prefixes):
    import streamlit as st
    # Streamlit normally discards widgets belonging to an inactive lazy tab.
    for key in list(st.session_state):
        if key.startswith(prefixes):
            st.session_state[key] = st.session_state[key]
