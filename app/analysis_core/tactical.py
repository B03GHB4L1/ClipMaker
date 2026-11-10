"""Native Tactical Lab: runs the classic tab code against a recorder.

The classic functions (``tactical_page``, copied verbatim) draw through a
module-level ``st`` and read page globals, so renders are serialized with a
lock. Each render rebuilds the classic session from the saved projects, loads
the selected match or matches the way the classic page does, and returns the
recorded elements and controls.
"""
from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

from . import tactical_fast
from . import tactical_page as page
from .frames import FrameCache
from .plotly_theme import streamlit_palette
from .st_shim import Recorder, StopRender

TABS = {
    "defensive-transitions": page.render_defensive_transitions,
    "attacking-transitions": page.render_attacking_transitions,
    "style-profile": page.render_style_profile,
    "set-pieces": page.render_set_pieces,
    "video-lab": page.render_video_lab,
}
MAX_MATCHES = 20
tactical_fast.install()  # Identical results, computed without per-event full-match scans.
# Only the classic tab widgets' keys may reach the session, never its
# internal state (video setups, clip paths).
CONTROL_KEY = re.compile(r"^(dt_seconds|dt_events|at_seconds|at_events|[a-z]{2,5}_match_scope|"
                         r"vl_playlist|vl_before|vl_after|vl_reel_count|style_trend_dim|"
                         r"vl_selected_moment_[A-Za-z ]{1,40})$")
_lock = threading.Lock()
_prepared: OrderedDict = OrderedDict()


def _load_prepared(csv_path):
    """The classic page's cached _load_csv, keyed by CSV identity."""
    key = FrameCache.identity(csv_path)
    if key not in _prepared:
        _prepared[key] = page._prepare_df(page.read_csv_safe(csv_path))
        while len(_prepared) > 6:
            _prepared.popitem(last=False)
    _prepared.move_to_end(key)
    return _prepared[key]


def _session(project, projects):
    """The classic session the project shell would sync (project_analysis.sync_project_state)."""
    from project_analysis import project_session
    state = project_session(project)
    state["match_setup_by_csv"] = {item["csv_path"]: project_session(item) for item in projects if item.get("csv_path")}
    state["multi_scraped_csv_paths"] = list(dict.fromkeys(
        item["csv_path"] for item in projects if item.get("csv_path") and Path(item["csv_path"]).is_file()))
    return state


def _matches(controls, project, projects, state):
    """(frame, labels, chosen project ids) like the classic _load_matches.

    Matches are chosen by project id; ids map to their saved CSVs here."""
    by_id = {item["id"]: item["csv_path"] for item in projects
             if item.get("csv_path") and item["csv_path"] in state["multi_scraped_csv_paths"]}
    page.st = Recorder(state)  # _match_label reads st.session_state
    if controls.get("multi"):
        ids = [str(value) for value in controls.get("matches") or [] if str(value) in by_id][:MAX_MATCHES]
        chosen = [by_id[value] for value in ids]
        if not chosen:
            return None, [], []
        frames, labels = [], []
        for index, path in enumerate(chosen):
            frame = _load_prepared(path).copy()
            frame["match_id"] = index
            frame["match_label"] = page._match_label(path)
            frame["source_csv"] = os.path.realpath(os.path.abspath(path))
            frames.append(frame)
            labels.append(page._match_label(path))
        return page._prepare_df(page.pd.concat(frames, ignore_index=True)), labels, ids
    path = project["csv_path"]
    frame = _load_prepared(path).copy()
    frame["match_id"] = 0
    frame["match_label"] = page._match_label(path)
    frame["source_csv"] = os.path.realpath(os.path.abspath(path))
    return page._prepare_df(frame), [page._match_label(path)], [project["id"]]


def render(tab, controls, project, projects, action=None):
    """Render one Tactical tab; returns (view dict, final session state)."""
    if tab not in TABS:
        raise ValueError("Unknown analytical tab")
    controls = controls if isinstance(controls, dict) else {}
    with _lock:
        state = _session(project, projects)
        frame, labels, chosen = _matches(controls, project, projects, state)
        options = [{"value": item["id"], "label": page._match_label(item["csv_path"])} for item in projects
                   if item.get("csv_path") and item["csv_path"] in state["multi_scraped_csv_paths"]]
        scope = {"multi": bool(controls.get("multi")), "matches": chosen, "match_options": options}
        if frame is None:
            return {"empty": "Select at least one match.", "scope": scope, "teams": [], "team": "",
                    "elements": [], "match_name": ""}, state
        teams = page._team_names(frame)
        team = controls.get("team") if controls.get("team") in teams else (teams[0] if teams else "")
        count = len(labels)
        name = f"{count} matches" if count > 1 else (labels[0] if count == 1 else "")
        if not name and "matchName" in frame.columns and not frame["matchName"].dropna().empty:
            name = str(frame["matchName"].dropna().iloc[0])
        # Tab controls (sliders, selects) arrive by their classic widget keys.
        for key, value in controls.items():
            if CONTROL_KEY.match(str(key)) and (value is None or isinstance(value, (str, int, float, bool))):
                state[key] = value
        recorder = Recorder(state)
        if action:
            original = recorder.button
            recorder.button = lambda label, *a, key=None, disabled=False, **k: (
                original(label, *a, key=key, disabled=disabled, **k), key == action and not disabled)[1]
        page.st, page.df_all, page.team, page.match_name = recorder, frame, team, name
        try:
            with streamlit_palette():
                TABS[tab](frame, team)
        except StopRender:
            pass
        finally:
            page.df_all, page.team, page.match_name = None, "", ""
        return {"empty": None, "scope": scope, "teams": teams, "team": team, "match_name": name,
                "elements": recorder.elements}, state


def clip(tab, controls, project, projects, action):
    """Run the classic Video Lab cut or reel; returns (path, download name)."""
    if tab != "video-lab" or action not in {"vl_cut", "vl_reel"}:
        raise ValueError("Clips are cut from the Video Lab.")
    view, state = render(tab, controls, project, projects, action=action)
    key = "vl_clip" if action == "vl_cut" else "vl_reel"
    if state.get(f"{key}_error"):
        raise ValueError(state[f"{key}_error"])
    path = state.get(f"{key}_path")
    if not path or not os.path.isfile(path):
        button = next((e for e in view["elements"] if e["kind"] == "Button" and e["key"] == action), None)
        reasons = [e["value"] for e in view["elements"] if e["kind"] == "Caption" and "video" in e["value"].lower()]
        raise ValueError(reasons[0] if reasons else ("This moment is not ready to cut." if button else
                                                      "No tactical moments to cut."))
    playlist = state.get("vl_playlist", "playlist")
    name = (f"{view['team']}_{playlist.replace(' ', '_')}_reel.mp4" if action == "vl_reel"
            else f"{view['team']}_{playlist.replace(' ', '_')}_moment.mp4")
    return path, name
