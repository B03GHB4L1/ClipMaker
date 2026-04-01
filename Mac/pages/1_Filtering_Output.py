import sys
import os
import re
import threading
import queue
import time
import platform
import tempfile
import subprocess
import shutil
import streamlit as st
import pandas as pd

# Add parent directory so we can import clipmaker_core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme
from clipmaker_core import (
    run_clip_maker, apply_filters, read_csv_safe,
    query_data, parse_filters, render_stats_panel,
    to_seconds, assign_periods, match_clock_to_video_time,
    merge_overlapping_windows,
    save_filter_snapshot, load_filter_snapshot, list_snapshots, delete_snapshot,
)

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="Filtering/Output — ClipMaker",
    page_icon="../ClipMaker_logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

IS_MAC = platform.system() == "Darwin"

theme.inject(
    logo_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ClipMaker_logo.png")
)
theme.init_shared_state()
theme.render_top_nav("filtering")
# =============================================================================
# SESSION STATE HELPERS
# =============================================================================
def _ss(key, default=""):
    return st.session_state.get(key, default)


_FILENAME_STOPWORDS = {
    "a", "an", "and", "all", "build", "clip", "clips", "create", "for", "from",
    "highlight", "highlights", "make", "made", "me", "of", "please", "reel",
    "show", "the", "to", "video", "with"
}

# C1 — Quick Preset Filter configurations
FILTER_PRESETS = {
    "Set Pieces":        {"filter_types": ["Pass"], "corner_or_freekick": True},
    "Ball Progression":  {"filter_types": ["Pass", "Carry"], "progressive_only": True},
    "Attacking Chaos":   {"filter_types": ["Pass", "SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost", "BlockedShot", "AttemptSaved", "Attempt"], "shots_and_key_passes_only": True, "depth_zone_filter": "Attacking Third"},
    "Defensive Display": {"filter_types": ["Tackle", "Interception", "Clearance", "BallRecovery", "BlockedPass", "Block", "Aerial", "OffsideProvoked"], "depth_zone_filter": "Defensive Third"},
}


def _prompt_slug(prompt, fallback="ai-highlight"):
    words = re.findall(r"[a-z0-9]+", (prompt or "").lower())
    keywords = [w for w in words if w not in _FILENAME_STOPWORDS]
    chosen = keywords[:6] or words[:6]
    slug = "-".join(chosen).strip("-")[:64]
    return slug or fallback


def _seconds_slug(secs):
    total = max(0, int(round(float(secs))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}{minutes:02d}{seconds:02d}"


def _clip_download_name(base_slug, window, index):
    start, end, _, _ = window
    return f"{base_slug}_{index:02d}_{_seconds_slug(start)}-{_seconds_slug(end)}.mp4"


def _compute_windows_from_config(cfg):
    if not cfg.get("data_file") or not cfg.get("half1_time") or not cfg.get("half2_time"):
        return []
    df = pd.read_csv(cfg["data_file"])
    for col in ["minute", "second", "type"]:
        if col not in df.columns:
            return []
    period_col_val = cfg.get("period_column") or None
    df = assign_periods(df, period_col_val, cfg.get("fallback_row"))
    hf = cfg.get("half_filter", "Both halves")
    if hf == "1st half only":
        df = df[df["resolved_period"] == 1]
    elif hf == "2nd half only":
        df = df[df["resolved_period"] == 2]
    df, _ = apply_filters(df, cfg)
    ps = {1: to_seconds(cfg["half1_time"]), 2: to_seconds(cfg["half2_time"])}
    if cfg.get("half3_time", "").strip():
        ps[3] = to_seconds(cfg["half3_time"])
    if cfg.get("half4_time", "").strip():
        ps[4] = to_seconds(cfg["half4_time"])
    if cfg.get("half5_time", "").strip():
        ps[5] = to_seconds(cfg["half5_time"])
    po = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0), 5: (120, 0)}
    timestamps = []
    for _, row in df.iterrows():
        try:
            timestamps.append(match_clock_to_video_time(
                int(row["minute"]), int(row["second"]),
                int(row["resolved_period"]), ps, po
            ))
        except ValueError:
            timestamps.append(None)
    df["video_timestamp"] = timestamps
    df = df.dropna(subset=["video_timestamp"]).sort_values("video_timestamp")
    raw = []
    for _, row in df.iterrows():
        ts = row["video_timestamp"]
        period = int(row["resolved_period"])
        label = f"{row['type']} @ {int(row['minute'])}:{int(row['second']):02d} (P{period})"
        raw.append((ts - cfg["before_buffer"], ts + cfg["after_buffer"], label, period))
    return merge_overlapping_windows(raw, cfg["min_gap"])


def _recent_mp4s(directory, started_at):
    if not directory or not os.path.isdir(directory):
        return []
    files = []
    threshold = started_at - 2
    for name in os.listdir(directory):
        if not name.lower().endswith(".mp4"):
            continue
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) >= threshold:
                files.append(path)
        except OSError:
            continue
    return sorted(files, key=lambda p: os.path.basename(p).lower())


def _render_ai_video_output():
    result = st.session_state.get("_ai_video_output")
    if not result:
        return
    st.markdown("##### Latest AI Video Output")
    st.caption(f"Prompt summary: `{result['base_slug']}`")
    if result.get("individual_clips"):
        files = result.get("files", [])
        if not files:
            st.info("No AI clips are ready to preview yet.")
            return
        st.success(f"{len(files)} AI clip{'s' if len(files) != 1 else ''} rendered.")
        for i, item in enumerate(files, 1):
            path = item.get("path", "")
            if not path or not os.path.exists(path):
                continue
            with st.expander(item.get("title") or f"Clip {i}", expanded=(i == 1)):
                with open(path, "rb") as vf:
                    clip_bytes = vf.read()
                st.video(clip_bytes)
                st.download_button(
                    "Download clip",
                    data=clip_bytes,
                    file_name=item.get("download_name") or os.path.basename(path),
                    mime="video/mp4",
                    use_container_width=True,
                    key=f"ai_clip_download_{i}_{os.path.basename(path)}",
                    icon=theme.icon_shortcode("[DL]"),
                )
    else:
        reel_path = result.get("reel_path", "")
        if reel_path and os.path.exists(reel_path):
            with open(reel_path, "rb") as vf:
                reel_bytes = vf.read()
            st.video(reel_bytes)
            st.download_button(
                "Download reel",
                data=reel_bytes,
                file_name=result.get("download_name") or os.path.basename(reel_path),
                mime="video/mp4",
                use_container_width=True,
                key=f"ai_reel_download_{os.path.basename(reel_path)}",
                icon=theme.icon_shortcode("[DL]"),
            )
        else:
            st.info("The last AI reel could not be found in the output folder.")


def _iconize_log_lines(lines):
    return "<br>".join(theme.ui_html(str(line)) for line in lines)

final_csv     = _ss("csv_path") or _ss("scraped_csv_path")
final_video   = _ss("video_path")
final_video2  = _ss("video2_path")
split_video   = _ss("split_video", False)
half1         = _ss("half1_time")
half2         = _ss("half2_time")
half3         = _ss("half3_time")
half4         = _ss("half4_time")
half5         = _ss("half5_time")
before_buf    = int(_ss("before_buffer") or 5)
after_buf     = int(_ss("after_buffer") or 8)
min_gap       = int(_ss("min_gap") or 6)
output_dir    = _ss("output_dir")

period_col  = "period"
use_fallback = False
fallback_row = 0


# =============================================================================
# HEADER
# =============================================================================
_logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ClipMaker_logo.png")
_logo_b64 = theme.load_logo_b64(_logo_path)
st.markdown(theme.logo_header("Filtering/Output", "Filter events and generate your highlight reel", _logo_b64 or None), unsafe_allow_html=True)

# Context bar — show current loaded data state
def _dot(ok): return f'<span class="ctx-dot-{"ok" if ok else "bad"}"></span>'
def _dot_dim(): return '<span class="cm-ctx-dot-dim"></span>'

csv_ok    = bool(final_csv and os.path.exists(final_csv))
video_ok  = bool(final_video and os.path.exists(final_video))
times_ok  = bool(half1 and half2)
csv_name  = os.path.basename(final_csv) if csv_ok else "No CSV"
video_name = os.path.basename(final_video) if video_ok else "No video"
times_str = f"{half1} / {half2}" if times_ok else "Not set"

st.markdown(f"""
    <div class="cm-context-bar">
        <div class="cm-ctx-item">{_dot(csv_ok)} <span>{csv_name}</span></div>
        <div class="cm-ctx-item">{_dot(video_ok)} <span>{video_name}</span></div>
        <div class="cm-ctx-item">{_dot(times_ok)} <span>Kick-offs: {times_str}</span></div>
        <div class="cm-ctx-item">{_dot_dim()} <span>Buffer: {before_buf}s before · {after_buf}s after · {min_gap}s merge</span></div>
    </div>
""", unsafe_allow_html=True)

if not csv_ok:
    st.warning("No CSV loaded. Go to **Home** to load or scrape match data first.", icon=":material/dataset:")

# =============================================================================
# LOAD CSV FOR FILTER OPTIONS
# =============================================================================
action_types = []
has_xt = has_prog = has_key_pass = has_pass_types = False
_home_team = _away_team = ""
_filter_df = None
_all_players = _home_players = _away_players = []

if csv_ok:
    try:
        _filter_df = read_csv_safe(final_csv.strip().strip("\"'"))  # lru_cache in core
        action_types = sorted(_filter_df["type"].dropna().unique().tolist()) if "type" in _filter_df.columns else []
        has_xt       = "xT" in _filter_df.columns
        has_prog     = any(c in _filter_df.columns for c in ["prog_pass", "prog_carry"])
        has_key_pass = "is_key_pass" in _filter_df.columns
        has_pass_types = any(c in _filter_df.columns for c in [
            "is_cross", "is_long_ball", "is_switch_of_play", "is_diagonal_long_ball", "is_through_ball", "is_corner",
            "is_freekick", "is_header", "is_big_chance", "is_big_chance_shot",
            "is_penalty", "is_volley", "is_chipped", "is_direct_from_corner",
            "is_left_foot", "is_right_foot", "is_fast_break", "is_touch_in_box",
            "is_assist_throughball", "is_assist_cross", "is_assist_corner",
            "is_assist_freekick", "is_intentional_assist",
            "is_yellow_card", "is_red_card", "is_second_yellow",
            "is_nutmeg", "is_success_in_box",
        ])
        if "team" in _filter_df.columns:
            teams = [t for t in _filter_df["team"].dropna().unique().tolist() if t]
            if len(teams) >= 2:
                _home_team, _away_team = teams[0], teams[1]
            elif len(teams) == 1:
                _home_team = teams[0]
        if "playerName" in _filter_df.columns:
            _all_players = sorted(_filter_df["playerName"].dropna().unique().tolist())
            if "team" in _filter_df.columns:
                _home_players = sorted(_filter_df[_filter_df["team"] == _home_team]["playerName"].dropna().unique()) if _home_team else _all_players
                _away_players = sorted(_filter_df[_filter_df["team"] == _away_team]["playerName"].dropna().unique()) if _away_team else _all_players
            else:
                _home_players = _away_players = _all_players
    except Exception as e:
        st.error(f"Could not read CSV: {e}")


# =============================================================================
# TABS
# =============================================================================
tab_manual, tab_ai = st.tabs([
    theme.ui("[FILTER] Manual Filters"),
    theme.ui("[AI] ClipMaker AI"),
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — MANUAL FILTERS
# ─────────────────────────────────────────────────────────────────────────────
with tab_manual:
    st.markdown("##### Filters")
    st.caption("Leave all blank to clip every event in the CSV.")

    # ── C1: Apply pending preset (must run before widgets render) ─────────────
    _pending_preset = st.session_state.pop("_cm_pending_preset", None)
    if _pending_preset is not None:
        # Reset all filter state before applying preset so stale values don't persist
        st.session_state["_cm_filter_types"] = []
        st.session_state["_cm_depth_zone"] = ""
        st.session_state["_cm_pitch_zone"] = ""
        st.session_state["_cm_progressive"] = False
        st.session_state["_cm_selected_pass_types"] = []
        st.session_state["_cm_shots_and_kp"] = False
        # Apply preset values
        if "filter_types" in _pending_preset:
            _avail = set(action_types)
            st.session_state["_cm_filter_types"] = [t for t in _pending_preset["filter_types"] if t in _avail]
        if "depth_zone_filter" in _pending_preset:
            st.session_state["_cm_depth_zone"] = _pending_preset.get("depth_zone_filter") or ""
        if "pitch_zone_filter" in _pending_preset:
            st.session_state["_cm_pitch_zone"] = _pending_preset.get("pitch_zone_filter") or ""
        if "progressive_only" in _pending_preset:
            st.session_state["_cm_progressive"] = _pending_preset["progressive_only"]
        if "corner_or_freekick" in _pending_preset and _pending_preset["corner_or_freekick"]:
            st.session_state["_cm_selected_pass_types"] = ["Corners", "Freekicks"]
        if "shots_and_key_passes_only" in _pending_preset and _pending_preset["shots_and_key_passes_only"]:
            st.session_state["_cm_shots_and_kp"] = True
            st.session_state["_cm_selected_pass_types"] = ["Key passes"]

    # ── C1: Quick Preset Buttons ──────────────────────────────────────────────
    st.caption("Quick presets")
    _preset_cols = st.columns(len(FILTER_PRESETS))
    for _pcol, (_pname, _pcfg) in zip(_preset_cols, FILTER_PRESETS.items()):
        with _pcol:
            if st.button(_pname, key=f"preset_{_pname}", use_container_width=True):
                st.session_state["_cm_pending_preset"] = _pcfg
                st.rerun()

    # ── C2: Load snapshot (must run before widgets render) ────────────────────
    _snap_to_load = st.session_state.pop("_cm_snapshot_to_load", None)
    if _snap_to_load is not None:
        _snap_cfg = load_filter_snapshot(_snap_to_load)
        if _snap_cfg:
            _avail = set(action_types)
            st.session_state["_cm_filter_types"]             = [t for t in _snap_cfg.get("filter_types", []) if t in _avail]
            st.session_state["_cm_depth_zone"]               = _snap_cfg.get("depth_zone_filter", "")
            st.session_state["_cm_pitch_zone"]               = _snap_cfg.get("pitch_zone_filter", "")
            st.session_state["_cm_progressive"]              = _snap_cfg.get("progressive_only", False)
            st.session_state["_cm_snap_pass_types_pending"]  = _snap_cfg.get("selected_pass_types", [])

    _pending_matrix_apply = st.session_state.pop("_cm_pending_matrix_apply", None)
    if _pending_matrix_apply is not None:
        _avail = set(action_types)
        _action = _pending_matrix_apply.get("filter_type")
        st.session_state["_cm_filter_types"] = [_action] if _action in _avail else []
        st.session_state["_cm_pitch_zone"] = _pending_matrix_apply.get("pitch_zone_filter") or ""

    # ── Team / Player ────────────────────────────────────────────────────────
    team_filter = "All players"
    player_filter = "All players"

    if len(_all_players) == 1:
        st.caption(f"Player: **{_all_players[0]}**")
        player_filter = _all_players[0]
    elif _home_team and _away_team:
        team_filter = st.radio(
            "Team",
            options=["Both teams", _home_team, _away_team],
            horizontal=True
        )
        if team_filter == _home_team:
            _pool = ["All players"] + list(_home_players)
        elif team_filter == _away_team:
            _pool = ["All players"] + list(_away_players)
        else:
            team_filter = "All players"
            _pool = ["All players"] + _all_players
        player_filter = st.selectbox("Player", options=_pool, index=0)
    elif _all_players:
        player_filter = st.selectbox("Player", options=["All players"] + _all_players, index=0)

    # ── Half filter ──────────────────────────────────────────────────────────
    half_filter = st.selectbox(
        "Half",
        options=["Both halves", "1st half only", "2nd half only"],
        help="Restrict clips to a specific half."
    )

    # ── Action Type ──────────────────────────────────────────────────────────
    filter_types = st.multiselect(
        "Action Type",
        options=action_types,
        placeholder="All types" if action_types else "Load a CSV first",
        key="_cm_filter_types",
    )

    # ── Action Qualifiers ─────────────────────────────────────────────────────
    PASS_TYPE_MAP = {
        # Outcome
        "Successful":            ("successful_only",           "outcomeType"),
        "Unsuccessful":          ("unsuccessful_only",         "outcomeType"),
        # Pass qualifiers
        "Key passes":            ("key_passes_only",           "is_key_pass"),
        "Crosses":               ("crosses_only",              "is_cross"),
        "Long balls":            ("long_balls_only",           "is_long_ball"),
        "Switches of play":      ("switches_only",             "is_switch_of_play"),
        "Diagonals":             ("diagonals_only",            "is_diagonal_long_ball"),
        "Through balls":         ("through_balls_only",        "is_through_ball"),
        "Corners":               ("corners_only",              "is_corner"),
        "Freekicks":             ("freekicks_only",            "is_freekick"),
        "Headers":               ("headers_only",              "is_header"),
        "Big chances":           ("big_chances_only",          "is_big_chance_shot"),
        "Big chances created":   ("big_chances_created_only",  "is_big_chance"),
        # Shot qualifiers
        "Own goal":              ("own_goals_only",            "is_own_goal"),
        "Penalties":             ("penalties_only",            "is_penalty"),
        "Volleys":               ("volleys_only",              "is_volley"),
        "Chipped shots":         ("chipped_only",              "is_chipped"),
        "Direct from corner":    ("direct_from_corner_only",   "is_direct_from_corner"),
        "Left foot":             ("left_foot_only",            "is_left_foot"),
        "Right foot":            ("right_foot_only",           "is_right_foot"),
        # Context
        "Fast break":            ("fast_break_only",           "is_fast_break"),
        "Touch in box":          ("touch_in_box_only",         "is_touch_in_box"),
        # Assist qualifiers
        "Assist (through ball)": ("assist_throughball_only",   "is_assist_throughball"),
        "Assist (cross)":        ("assist_cross_only",         "is_assist_cross"),
        "Assist (corner)":       ("assist_corner_only",        "is_assist_corner"),
        "Assist (free kick)":    ("assist_freekick_only",      "is_assist_freekick"),
        "Intentional assists":   ("intentional_assists_only",  "is_intentional_assist"),
        # Goalkeeper qualifiers
        "GK save":               ("gk_saves_only",             "is_gk_save"),
        # Card subtypes
        "Yellow card":           ("yellow_cards_only",         "is_yellow_card"),
        "Red card":              ("red_cards_only",            "is_red_card"),
        "Second yellow":         ("second_yellow_only",        "is_second_yellow"),
        # TakeOn qualifiers
        "Nutmeg":                ("nutmegs_only",              "is_nutmeg"),
        "Success in box":        ("success_in_box_only",       "is_success_in_box"),
    }
    available_pass_types = []
    if _filter_df is not None:
        for label, (flag, col) in PASS_TYPE_MAP.items():
            if col == "outcomeType":
                outcome_val = "Successful" if flag == "successful_only" else "Unsuccessful"
                if col in _filter_df.columns and (_filter_df[col] == outcome_val).any():
                    available_pass_types.append(label)
            elif col in _filter_df.columns and _filter_df[col].any():
                available_pass_types.append(label)
    # Apply any qualifiers restored from a snapshot (validated against available options)
    _pending_pass_types = st.session_state.pop("_cm_snap_pass_types_pending", None)
    if _pending_pass_types is not None:
        st.session_state["_cm_selected_pass_types"] = [q for q in _pending_pass_types if q in available_pass_types]

    selected_pass_types = []
    key_passes_only = False
    progressive_only = False

    if available_pass_types:
        selected_pass_types = st.multiselect(
            "Action Qualifier",
            options=available_pass_types,
            placeholder="All qualifiers",
            key="_cm_selected_pass_types",
        )
        key_passes_only = "Key passes" in selected_pass_types

    if has_prog:
        progressive_only = st.checkbox("Progressive actions only",
            help="Only include actions where prog_pass or prog_carry > 0",
            key="_cm_progressive")

    # ── Zone Filters ──────────────────────────────────────────────────────────
    _pz_col, _dz_col = st.columns(2)
    with _pz_col:
        pitch_zone_filter = st.selectbox(
            "Pitch Zone",
            options=["", "Entire Left Side", "Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing", "Entire Right Side"],
            format_func=lambda x: "Any zone" if x == "" else x,
            key="_cm_pitch_zone",
        )
    with _dz_col:
        depth_zone_filter = st.selectbox(
            "Depth Zone",
            options=["", "Defensive Third", "Middle Third", "Attacking Third"],
            format_func=lambda x: "Any zone" if x == "" else x,
            key="_cm_depth_zone",
        )

    # ── xT Filters ───────────────────────────────────────────────────────────
    xt_min = 0.0
    top_n  = 0
    if has_xt:
        with st.expander("xT Filters"):
            xt_min = st.number_input("Min xT value", min_value=0.0, value=0.0, step=0.001, format="%.3f")
            top_n  = st.number_input("Top N by xT (0 = all)", min_value=0, value=0, step=1)

    # ── C2: Filter Snapshots ─────────────────────────────────────────────────
    with st.expander("Filter Snapshots"):
        st.caption("Save and reload filter presets across sessions.")
        _snap_save_col, _snap_load_col, _snap_del_col = st.columns([2, 2, 2])

        with _snap_save_col:
            _snap_name = st.text_input("Snapshot name", placeholder="e.g. Pressing_Press",
                                        key="_cm_snap_name_input", label_visibility="collapsed")
            if st.button("Save snapshot", key="_cm_save_snap", use_container_width=True):
                if _snap_name:
                    _snap_data = {
                        "filter_types":      st.session_state.get("_cm_filter_types", []),
                        "pitch_zone_filter": st.session_state.get("_cm_pitch_zone", ""),
                        "depth_zone_filter": st.session_state.get("_cm_depth_zone", ""),
                        "progressive_only":  st.session_state.get("_cm_progressive", False),
                        "selected_pass_types": st.session_state.get("_cm_selected_pass_types", []),
                    }
                    save_filter_snapshot(_snap_name, _snap_data)
                    st.success(f"Saved: {_snap_name}")
                else:
                    st.warning("Enter a name first.")

        _existing_snaps = list_snapshots()

        with _snap_load_col:
            if _existing_snaps:
                _sel_load = st.selectbox("Load", _existing_snaps, key="_cm_snap_load_sel",
                                          label_visibility="collapsed")
                if st.button("Load snapshot", key="_cm_load_snap", use_container_width=True):
                    st.session_state["_cm_snapshot_to_load"] = _sel_load
                    st.rerun()
            else:
                st.caption("No snapshots saved yet.")

        with _snap_del_col:
            if _existing_snaps:
                _sel_del = st.selectbox("Delete", _existing_snaps, key="_cm_snap_del_sel",
                                         label_visibility="collapsed")
                if st.button("Delete snapshot", key="_cm_del_snap", use_container_width=True):
                    delete_snapshot(_sel_del)
                    st.success(f"Deleted: {_sel_del}")
                    st.rerun()

    st.divider()

    # ── Output ───────────────────────────────────────────────────────────────
    st.markdown("##### Output")

    if IS_MAC:
        out_dir_input = st.text_input("Output Folder", value=output_dir,
                                       placeholder="Paste folder path, e.g. /Users/yourname/Desktop/Clips")
    else:
        import queue as _q_mod
        oc1, oc2 = st.columns([5, 1])
        with oc1:
            out_dir_input = st.text_input("Output Folder", value=output_dir,
                                           placeholder="Click Browse to choose folder")
        with oc2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Browse", key="browse_out"):
                import tkinter as tk
                from tkinter import filedialog
                _q = _q_mod.Queue()
                def _pick():
                    r = tk.Tk(); r.withdraw()
                    try: r.wm_attributes("-topmost", True)
                    except: pass
                    p = filedialog.askdirectory(); r.destroy(); _q.put(p)
                _t = threading.Thread(target=_pick, daemon=True); _t.start(); _t.join(timeout=60)
                try:
                    picked = _q.get_nowait()
                    if picked:
                        st.session_state["output_dir"] = picked
                        st.rerun()
                except: pass

    if out_dir_input and out_dir_input != st.session_state.get("output_dir", ""):
        st.session_state["output_dir"] = out_dir_input

    final_out_dir = st.session_state.get("output_dir") or out_dir_input or "output"

    individual = st.checkbox("Save individual clips instead of one combined reel")
    if not individual:
        out_filename = st.text_input("Output Filename", value="Highlights.mp4")
    else:
        out_filename = "Highlights.mp4"

    st.divider()

    # ── Shared: apply team / player filter to temp CSV ────────────────────────
    _team_data_file = final_csv or ""
    _needs_filter = (team_filter != "All players") or (player_filter != "All players")
    if _needs_filter and final_csv and os.path.exists(final_csv.strip().strip("\"'")):
        try:
            _tdf = read_csv_safe(final_csv.strip().strip("\"'"))
            if team_filter != "All players" and "team" in _tdf.columns:
                _tdf = _tdf[_tdf["team"] == team_filter]
            if player_filter != "All players" and "playerName" in _tdf.columns:
                _tdf = _tdf[_tdf["playerName"] == player_filter]
            if len(_tdf) > 0:
                _tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
                _tdf.to_csv(_tmp.name, index=False)
                _tmp.close()
                _team_data_file = _tmp.name
        except Exception:
            pass

    # ── Shared config builder ─────────────────────────────────────────────────
    def _build_config(dry_run=False):
        return {
            "video_file":       final_video or "",
            "video2_file":      final_video2 or "",
            "split_video":      split_video,
            "data_file":        _team_data_file,
            "half1_time":       half1,
            "half2_time":       half2,
            "half3_time":       half3 or "",
            "half4_time":       half4 or "",
            "half5_time":       half5 or "",
            "period_column":    "" if use_fallback else period_col,
            "fallback_row":     int(fallback_row) if use_fallback else None,
            "before_buffer":    before_buf,
            "after_buffer":     after_buf,
            "min_gap":          min_gap,
            "output_dir":       final_out_dir,
            "output_filename":  out_filename,
            "individual_clips": individual,
            "dry_run":          dry_run,
            "half_filter":      half_filter,
            "filter_types":              filter_types,
            "progressive_only":          progressive_only,
            "key_passes_only":           key_passes_only,
            "shots_and_key_passes_only": st.session_state.get("_cm_shots_and_kp", False),
            "successful_only":           "Successful"            in selected_pass_types,
            "unsuccessful_only":         "Unsuccessful"          in selected_pass_types,
            "crosses_only":              "Crosses"               in selected_pass_types,
            "long_balls_only":           "Long balls"            in selected_pass_types,
            "switches_only":             "Switches of play"      in selected_pass_types,
            "diagonals_only":            "Diagonals"             in selected_pass_types,
            "through_balls_only":        "Through balls"         in selected_pass_types,
            "corners_only":              "Corners"               in selected_pass_types,
            "freekicks_only":            "Freekicks"             in selected_pass_types,
            "headers_only":              "Headers"               in selected_pass_types,
            "big_chances_only":          "Big chances"           in selected_pass_types,
            "big_chances_created_only":  "Big chances created"   in selected_pass_types,
            "own_goals_only":            "Own goal"              in selected_pass_types,
            "penalties_only":            "Penalties"             in selected_pass_types,
            "volleys_only":              "Volleys"               in selected_pass_types,
            "chipped_only":              "Chipped shots"         in selected_pass_types,
            "direct_from_corner_only":   "Direct from corner"    in selected_pass_types,
            "left_foot_only":            "Left foot"             in selected_pass_types,
            "right_foot_only":           "Right foot"            in selected_pass_types,
            "fast_break_only":           "Fast break"            in selected_pass_types,
            "touch_in_box_only":         "Touch in box"          in selected_pass_types,
            "assist_throughball_only":   "Assist (through ball)" in selected_pass_types,
            "assist_cross_only":         "Assist (cross)"        in selected_pass_types,
            "assist_corner_only":        "Assist (corner)"       in selected_pass_types,
            "assist_freekick_only":      "Assist (free kick)"    in selected_pass_types,
            "intentional_assists_only":  "Intentional assists"   in selected_pass_types,
            "gk_saves_only":             "GK save"               in selected_pass_types,
            "yellow_cards_only":         "Yellow card"           in selected_pass_types,
            "red_cards_only":            "Red card"              in selected_pass_types,
            "second_yellow_only":        "Second yellow"         in selected_pass_types,
            "nutmegs_only":              "Nutmeg"                in selected_pass_types,
            "success_in_box_only":       "Success in box"        in selected_pass_types,
            "pitch_zone_filter": pitch_zone_filter,
            "depth_zone_filter": depth_zone_filter,
            "xt_min":           xt_min,
            "top_n":            int(top_n) if top_n > 0 else None,
        }

    # ── Helper: compute clip windows from current filters ─────────────────────
    def _compute_windows():
        """Return (windows, video_file) using the same pipeline as run_clip_maker."""
        if not final_csv or not half1 or not half2:
            return [], ""
        cfg = _build_config(dry_run=True)
        return _compute_windows_from_config(cfg), cfg["video_file"]

    # ── Helper: cut a single clip with ffmpeg ─────────────────────────────────
    def _get_ffmpeg():
        cmd = shutil.which("ffmpeg")
        if cmd: return cmd
        try:
            from moviepy.config import FFMPEG_BINARY
            if os.path.exists(FFMPEG_BINARY): return FFMPEG_BINARY
        except Exception: pass
        raise ValueError("FFmpeg not found.")

    def _cut_clip(src, start, end, out_path):
        ff = _get_ffmpeg()
        r = subprocess.run(
            [ff, "-y", "-ss", str(start), "-to", str(end), "-i", src,
             "-c:v", "libx264", "-preset", "ultrafast", "-threads", "0",
             "-c:a", "aac", "-avoid_negative_ts", "make_zero", out_path],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise ValueError(f"FFmpeg error: {r.stderr[-300:]}")

    def _fmt(secs):
        total = max(0, int(round(float(secs))))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    # ── Buttons row ───────────────────────────────────────────────────────────
    btn1, btn2 = st.columns(2)
    with btn1:
        preview_btn = st.button("Preview Clip List", use_container_width=True, icon=theme.icon_shortcode("[SEARCH]"))
    with btn2:
        run_btn = st.button("Run ClipMaker", type="primary", use_container_width=True, icon=theme.icon_shortcode("[RUN]"))

    progress_placeholder = st.empty()
    status_placeholder   = st.empty()
    log_placeholder      = st.empty()

    # ── Helper: clear stale preview state ────────────────────────────────────
    def _clear_preview():
        old_pw = st.session_state.get("_preview_windows") or []
        for j in range(len(old_pw)):
            st.session_state.pop(f"_filt_clip_{j}", None)
        st.session_state.pop("_preview_windows", None)
        st.session_state.pop("_preview_video", None)

    # ── Preview Clip List ─────────────────────────────────────────────────────
    if preview_btn:
        _clear_preview()
        errors = []
        if not final_csv:
            errors.append("CSV file is required (set it on the Home page).")
        if not half1:
            errors.append("1st half kick-off time is required (set it on the Home page).")
        if not half2:
            errors.append("2nd half kick-off time is required (set it on the Home page).")
        if errors:
            for e in errors: st.error(e)
        else:
            try:
                windows, vid_src = _compute_windows()
                if not windows:
                    st.info("No clips match the current filters.")
                else:
                    st.session_state["_preview_windows"] = windows
                    st.session_state["_preview_video"] = vid_src
                    st.rerun()
            except Exception as ex:
                st.error(f"Could not compute clip list: {ex}")

    # ── Show persisted preview list ───────────────────────────────────────────
    _pw = st.session_state.get("_preview_windows")
    _pv = st.session_state.get("_preview_video", "")
    if _pw:
        _hdr1, _hdr2 = st.columns([5, 1])
        with _hdr1:
            st.success(f"**{len(_pw)} clip{'s' if len(_pw) != 1 else ''}** match the current filters.")
        with _hdr2:
            if st.button("Clear", key="_clear_preview_btn", use_container_width=True, icon=theme.icon_shortcode("[X]")):
                _clear_preview()
                st.rerun()
        for i, (s, e, lbl, p) in enumerate(_pw):
            dur = e - s
            with st.expander(
                f"**Clip {i+1}** · {_fmt(s)} → {_fmt(e)} · {dur:.0f}s · {lbl}",
                expanded=False,
            ):
                mc1, mc2 = st.columns([1, 1], gap="large")
                with mc1:
                    st.markdown(f"**Start:** {_fmt(s)}  \n**End:** {_fmt(e)}  \n**Duration:** {dur:.0f}s")
                    st.caption(lbl)
                with mc2:
                    clip_key = f"_filt_clip_{i}"
                    clip_path = st.session_state.get(clip_key, "")
                    if clip_path and os.path.exists(clip_path):
                        with open(clip_path, "rb") as vf:
                            st.video(vf.read())
                        with open(clip_path, "rb") as vf:
                            st.download_button(
                                "Download clip",
                                data=vf.read(),
                                file_name=f"clip_{i+1}_{_fmt(s).replace(':','')}.mp4",
                                mime="video/mp4",
                                use_container_width=True,
                                key=f"dl_filt_{i}",
                                icon=theme.icon_shortcode("[DL]"),
                            )
                    else:
                        if _pv and os.path.exists(_pv):
                            if st.button("Render this clip", key=f"rend_{i}",
                                          icon=theme.icon_shortcode("[RUN]"),
                                          use_container_width=True):
                                with st.spinner("Cutting clip…"):
                                    try:
                                        _otmp = tempfile.NamedTemporaryFile(
                                            suffix=".mp4", delete=False,
                                            dir=tempfile.gettempdir())
                                        _otmp.close()
                                        _cut_clip(_pv, s, e, _otmp.name)
                                        st.session_state[clip_key] = _otmp.name
                                        st.rerun()
                                    except Exception as ex:
                                        st.error(f"Could not cut clip: {ex}")
                        else:
                            st.caption("Set your video file on the Home page to render clips.")

    # ── Full Run ──────────────────────────────────────────────────────────────
    if run_btn:
        _clear_preview()
        errors = []
        if not final_video:
            errors.append("Video file is required (set it on the Home page).")
        if not final_csv:
            errors.append("CSV file is required (set it on the Home page).")
        if not half1:
            errors.append("1st half kick-off time is required (set it on the Home page).")
        if not half2:
            errors.append("2nd half kick-off time is required (set it on the Home page).")

        if errors:
            for e in errors:
                st.error(e)
        else:
            config = _build_config(dry_run=False)

            log_q  = queue.Queue()
            prog_q = queue.Queue()
            log_lines = []
            last_progress = {"current": 0, "total": 1, "elapsed": 0}

            _run_start_t = time.time()
            thread = threading.Thread(
                target=run_clip_maker, args=(config, log_q, prog_q), daemon=True
            )
            thread.start()

            while thread.is_alive() or not log_q.empty():
                while not prog_q.empty():
                    last_progress = prog_q.get_nowait()

                updated = False
                while not log_q.empty():
                    msg = log_q.get_nowait()
                    if msg["type"] == "log":
                        log_lines.append(msg["msg"])
                        updated = True

                cur = last_progress["current"]
                tot = last_progress["total"]
                elapsed = last_progress["elapsed"]
                frac = cur / tot if tot > 0 else 0
                phase = last_progress.get("phase", "clips")

                if cur > 0 and elapsed > 0:
                    rate = cur / elapsed
                    remaining = (tot - cur) / rate
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    eta_str = f"{mins}m {secs:02d}s remaining"
                else:
                    eta_str = "Calculating..."

                if phase == "assembly":
                    label_str = "Finalising — merging audio and video..." if frac >= 0.99 else f"Assembling — frame {cur:,} of {tot:,} — {eta_str}"
                else:
                    label_str = f"Clip {cur} of {tot} — {eta_str}"

                with progress_placeholder.container():
                    st.markdown(f'<div class="cm-progress-label">{label_str}</div>', unsafe_allow_html=True)
                    st.progress(frac)

                if updated:
                    log_placeholder.markdown(
                        f'<div class="cm-log-box">{_iconize_log_lines(log_lines)}</div>',
                        unsafe_allow_html=True
                    )
                time.sleep(0.3)

            thread.join()

            while not log_q.empty():
                msg = log_q.get_nowait()
                if msg["type"] == "log":
                    log_lines.append(msg["msg"])

            log_placeholder.markdown(
                f'<div class="cm-log-box">{_iconize_log_lines(log_lines)}</div>',
                unsafe_allow_html=True
            )
            progress_placeholder.empty()

            if any("[OK]" in l for l in log_lines):
                st.success("Done!", icon=theme.icon_shortcode("[OK]"))
                import glob as _iglob
                if individual:
                    _new_clips = sorted([
                        f for f in _iglob.glob(os.path.join(final_out_dir, "*.mp4"))
                        if os.path.getmtime(f) >= _run_start_t - 2
                    ])
                    if _new_clips:
                        st.markdown("**Preview — Individual Clips:**")
                        for _ic in _new_clips:
                            _ic_name = os.path.basename(_ic)
                            with st.expander(_ic_name, expanded=False):
                                with open(_ic, "rb") as _vf:
                                    _vbytes = _vf.read()
                                st.video(_vbytes)
                                st.download_button(
                                    "Download",
                                    data=_vbytes,
                                    file_name=_ic_name,
                                    mime="video/mp4",
                                    key=f"dl_run_ic_{_ic_name}",
                                    use_container_width=True,
                                    icon=theme.icon_shortcode("[DL]"),
                                )
                else:
                    _reel_path = os.path.join(final_out_dir, out_filename)
                    if os.path.exists(_reel_path):
                        st.markdown("**Preview:**")
                        with open(_reel_path, "rb") as _vf:
                            _reel_bytes = _vf.read()
                        st.video(_reel_bytes)
                        st.download_button(
                            "Download reel",
                            data=_reel_bytes,
                            file_name=out_filename,
                            mime="video/mp4",
                            key="dl_run_reel",
                            use_container_width=True,
                            icon=theme.icon_shortcode("[DL]"),
                        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — CLIPMAKER AI
# ─────────────────────────────────────────────────────────────────────────────
with tab_ai:
    _ai_csv = final_csv

    if _ai_csv and os.path.exists(_ai_csv.strip().strip("\"'")):
        with st.expander(theme.ui("[DATA] Data summary"), expanded=False):
            try:
                render_stats_panel(read_csv_safe(_ai_csv.strip().strip("\"'")))
            except Exception:
                pass
    else:
        st.info("Load a CSV on the Home page to unlock AI analysis.", icon=":material/dataset:")

    st.markdown("##### Ask about your data or describe the clips you want")

    ai_input = st.text_area(
        "AI query",
        placeholder='e.g. "Who had the most take ons" or "Make a reel of Estevao\'s passes in the second half"',
        height=100,
        label_visibility="collapsed"
    )

    ai_c1, ai_c2 = st.columns(2)
    with ai_c1:
        ask_btn = st.button("Ask about data", use_container_width=True, icon=theme.icon_shortcode("[ASK]"))
    with ai_c2:
        make_clips_ai_btn = st.button("Make clips with AI", type="primary", use_container_width=True, icon=theme.icon_shortcode("[CLIP]"))

    ai_answer_placeholder = st.empty()

    # ── Ask about data ────────────────────────────────────────────────────────
    if ask_btn:
        if not _ai_csv:
            ai_answer_placeholder.error("Load a CSV file first.")
        elif not ai_input.strip():
            ai_answer_placeholder.error("Please enter a question.")
        else:
            with ai_answer_placeholder.container():
                with st.spinner("Analysing..."):
                    try:
                        df_ai = read_csv_safe(_ai_csv.strip().strip("\"'"))
                        result = query_data(ai_input, df_ai)

                        st.markdown("**Answer:**")
                        if result["type"] == "top_player":
                            st.markdown(f'<div class="cm-ai-box">{result["data"]}</div>',
                                        unsafe_allow_html=True)
                            with st.expander("Full breakdown"):
                                st.dataframe(result["breakdown"],
                                             use_container_width=True, hide_index=True)
                        elif result["type"] == "table":
                            st.dataframe(result["data"],
                                         use_container_width=True, hide_index=True)
                            st.caption(f"{result['count']} event{'s' if result['count'] != 1 else ''} · "
                                       f"To clip these, describe them in the box above and click **Make clips with AI**.")
                        else:
                            st.markdown(f'<div class="cm-ai-box">{result["data"]}</div>',
                                        unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error: {e}")

    # ── Make clips with AI ────────────────────────────────────────────────────
    if make_clips_ai_btn:
        if not final_video:
            st.error("Video file is required. Set it on the Home page.")
        elif not final_csv:
            st.error("CSV file is required. Set it on the Home page.")
        elif not ai_input.strip():
            st.error("Please describe what clips you want.")
        else:
            df_ai = read_csv_safe(final_csv.strip().strip("\"'"))
            available_types = df_ai["type"].dropna().unique().tolist() if "type" in df_ai.columns else []

            with st.spinner("AI is interpreting your request..."):
                try:
                    filters = parse_filters(ai_input, df_ai, available_types)
                except Exception as e:
                    st.error(f"Could not parse request: {e}")
                    st.stop()

            _ai_prompt_lower = ai_input.lower()
            _explicit_buffer_requested = bool(re.search(
                r"\b("
                r"buffer|buffers|before|after|pre[-\s]?roll|post[-\s]?roll|"
                r"seconds?\s+before|seconds?\s+after|secs?\s+before|secs?\s+after"
                r")\b",
                _ai_prompt_lower,
            ))
            _ai_before_buffer = filters.get("before_buffer", before_buf) if _explicit_buffer_requested else before_buf
            _ai_after_buffer = filters.get("after_buffer", after_buf) if _explicit_buffer_requested else after_buf

            st.session_state["ai_last_filters"] = filters

            # Apply team/player filter
            team_filter_ai   = filters.get("team_filter", "").strip()
            player_filter_ai = filters.get("player_filter", "").strip()
            ai_data_file = final_csv.strip().strip("\"'")
            df_filtered = df_ai.copy()

            if team_filter_ai and "team" in df_filtered.columns:
                df_team = df_filtered[df_filtered["team"].str.contains(team_filter_ai, case=False, na=False)]
                if len(df_team) == 0:
                    st.warning(f"No events for team '{team_filter_ai}'. Running on all teams.")
                else:
                    df_filtered = df_team
                    st.info(f"Filtered to {len(df_filtered)} events for team '{team_filter_ai}'.")

            if player_filter_ai and "playerName" in df_filtered.columns:
                player_names = [p.strip() for p in player_filter_ai.split(",") if p.strip()]
                if len(player_names) > 1:
                    mask = df_filtered["playerName"].apply(
                        lambda x: any(n.lower() in str(x).lower() for n in player_names)
                    )
                else:
                    mask = df_filtered["playerName"].str.contains(player_filter_ai, case=False, na=False)
                df_player = df_filtered[mask]
                if len(df_player) == 0:
                    st.warning(f"No events for '{player_filter_ai}'. Running on all players.")
                else:
                    df_filtered = df_player
                    st.info(f"Filtered to {len(df_filtered)} events for '{player_filter_ai}'.")

            if df_filtered is not df_ai:
                tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
                df_filtered.to_csv(tmp.name, index=False)
                tmp.close()
                ai_data_file = tmp.name

            ai_out_dir = st.session_state.get("output_dir") or "output"
            ai_slug = _prompt_slug(ai_input)
            ai_output_name = f"{ai_slug}.mp4"

            ai_config = {
                "video_file":       final_video,
                "video2_file":      final_video2 or "",
                "split_video":      split_video,
                "data_file":        ai_data_file,
                "half1_time":       half1 or "0:00",
                "half2_time":       half2 or "45:00",
                "half3_time":       half3 or "",
                "half4_time":       half4 or "",
                "half5_time":       half5 or "",
                "period_column":    "" if use_fallback else period_col,
                "fallback_row":     int(fallback_row) if use_fallback else None,
                "before_buffer":    _ai_before_buffer,
                "after_buffer":     _ai_after_buffer,
                "min_gap":          min_gap,
                "output_dir":       ai_out_dir,
                "output_filename":  ai_output_name,
                "individual_clips": filters.get("individual_clips", False),
                "dry_run":          False,
                "half_filter":      filters.get("half_filter", "Both halves"),
                "filter_types":     filters.get("filter_types", []),
                "progressive_only":   filters.get("progressive_only", False),
                "key_passes_only":    filters.get("key_passes_only", False),
                "crosses_only":       filters.get("crosses_only", False),
                "long_balls_only":    filters.get("long_balls_only", False),
                "switches_only":      filters.get("switches_only", False),
                "diagonals_only":     filters.get("diagonals_only", False),
                "through_balls_only": filters.get("through_balls_only", False),
                "corners_only":       filters.get("corners_only", False),
                "freekicks_only":     filters.get("freekicks_only", False),
                "headers_only":       filters.get("headers_only", False),
                "big_chances_only":         filters.get("big_chances_only", False),
                "big_chances_created_only": filters.get("big_chances_created_only", False),
                "xt_min":             filters.get("xt_min", 0.0),
                "top_n":              int(filters.get("top_n", 0)) or None,
                "successful_only":    filters.get("successful_only", False),
                "unsuccessful_only":  filters.get("unsuccessful_only", False),
                "minute_min":         filters.get("minute_min", None),
                "minute_max":         filters.get("minute_max", None),
                "pitch_zone_filter":  filters.get("pitch_zone_filter", ""),
                "depth_zone_filter":  filters.get("depth_zone_filter", ""),
                "own_goals_only":             filters.get("own_goals_only", False),
                "gk_saves_only":              filters.get("gk_saves_only", False),
                "penalties_only":             filters.get("penalties_only", False),
                "volleys_only":               filters.get("volleys_only", False),
                "chipped_only":               filters.get("chipped_only", False),
                "direct_from_corner_only":    filters.get("direct_from_corner_only", False),
                "left_foot_only":             filters.get("left_foot_only", False),
                "right_foot_only":            filters.get("right_foot_only", False),
                "fast_break_only":            filters.get("fast_break_only", False),
                "touch_in_box_only":          filters.get("touch_in_box_only", False),
                "assist_throughball_only":    filters.get("assist_throughball_only", False),
                "assist_cross_only":          filters.get("assist_cross_only", False),
                "assist_corner_only":         filters.get("assist_corner_only", False),
                "assist_freekick_only":       filters.get("assist_freekick_only", False),
                "intentional_assists_only":   filters.get("intentional_assists_only", False),
                "yellow_cards_only":          filters.get("yellow_cards_only", False),
                "red_cards_only":             filters.get("red_cards_only", False),
                "second_yellow_only":         filters.get("second_yellow_only", False),
                "nutmegs_only":               filters.get("nutmegs_only", False),
                "success_in_box_only":        filters.get("success_in_box_only", False),
                "deep_completion_only":       filters.get("deep_completion_only", False),
                "box_entry_pass_only":        filters.get("box_entry_pass_only", False),
                "box_entry_carry_only":       filters.get("box_entry_carry_only", False),
                "final_third_entry_pass_only":  filters.get("final_third_entry_pass_only", False),
                "final_third_entry_carry_only": filters.get("final_third_entry_carry_only", False),
            }

            ai_windows = _compute_windows_from_config(ai_config)
            st.session_state.pop("_ai_video_output", None)

            ai_log_queue    = queue.Queue()
            ai_progress_queue = queue.Queue()
            ai_log_lines    = []
            ai_log_ph       = st.empty()
            run_started_at  = time.time()

            ai_thread = threading.Thread(
                target=run_clip_maker,
                args=(ai_config, ai_log_queue, ai_progress_queue),
                daemon=True
            )
            ai_thread.start()

            while ai_thread.is_alive() or not ai_log_queue.empty():
                updated = False
                while not ai_log_queue.empty():
                    msg = ai_log_queue.get_nowait()
                    if isinstance(msg, dict) and msg.get("type") == "log":
                        ai_log_lines.append(msg.get("msg", ""))
                        updated = True
                if updated:
                    ai_log_ph.markdown(
                        f'<div class="cm-log-box">{_iconize_log_lines(ai_log_lines)}</div>',
                        unsafe_allow_html=True
                    )
                time.sleep(0.3)

            ai_thread.join()
            ai_log_ph.markdown(
                f'<div class="cm-log-box">{_iconize_log_lines(ai_log_lines)}</div>',
                unsafe_allow_html=True
            )
            if any("[OK]" in l for l in ai_log_lines):
                st.success("Done!", icon=theme.icon_shortcode("[OK]"))

            if any(("Saved to:" in l) or ("clips saved to:" in l) for l in ai_log_lines):
                if ai_config["individual_clips"]:
                    rendered_paths = _recent_mp4s(ai_out_dir, run_started_at)
                    numbered_paths = [
                        p for p in rendered_paths
                        if re.match(r"^\d+_", os.path.basename(p))
                    ]
                    clip_paths = numbered_paths or rendered_paths
                    clip_items = []
                    for idx, (src_path, window) in enumerate(zip(clip_paths, ai_windows), 1):
                        download_name = _clip_download_name(ai_slug, window, idx)
                        final_path = os.path.join(ai_out_dir, download_name)
                        try:
                            if os.path.abspath(src_path) != os.path.abspath(final_path):
                                os.replace(src_path, final_path)
                        except OSError:
                            final_path = src_path
                        clip_items.append({
                            "path": final_path,
                            "download_name": download_name,
                            "title": f"Clip {idx} · {_fmt(window[0])} → {_fmt(window[1])}",
                        })
                    st.session_state["_ai_video_output"] = {
                        "base_slug": ai_slug,
                        "individual_clips": True,
                        "files": clip_items,
                    }
                else:
                    st.session_state["_ai_video_output"] = {
                        "base_slug": ai_slug,
                        "individual_clips": False,
                        "reel_path": os.path.join(ai_out_dir, ai_output_name),
                        "download_name": ai_output_name,
                    }

    if st.session_state.get("ai_last_filters"):
        _filters_display = st.session_state["ai_last_filters"]
        st.markdown("**AI interpreted your request as:**")
        st.markdown(f'<div class="cm-ai-box">{_filters_display.get("explanation", "No explanation.")}</div>', unsafe_allow_html=True)
        if st.checkbox(theme.ui("[DEBUG] Show debug config"), key="ai_debug_config", value=False):
            st.json({k: v for k, v in _filters_display.items() if k != "explanation"})

    _render_ai_video_output()

theme.render_support_footer("Filtering")
