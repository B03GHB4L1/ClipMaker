import sys
import os
import re
import subprocess
import tempfile
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme
from smp_component import shot_map, pass_map, defensive_map, dribble_carry_map, goalkeeper_map, build_up_map
from clipmaker_core import (
    to_seconds, _effective_pitch_zone_series,
    detect_progressive_chains, get_chain_actions,
)

try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PLOTLY_AVAILABLE = True
except ImportError:
    _PLOTLY_AVAILABLE = False

def _h(s):
    import re as _re
    return _re.sub(r'\s{2,}', ' ', s.replace('\n', ' ')).strip()

st.set_page_config(
    page_title="The Analyst's Room",
    page_icon="../ClipMaker_logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# STYLING
# =============================================================================
theme.inject(
    logo_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ClipMaker_logo.png")
)
theme.init_shared_state()
theme.render_top_nav("analyst")
# =============================================================================
# CONSTANTS
# =============================================================================
SHOT_TYPES = {"SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost",
              "BlockedShot", "AttemptSaved", "Attempt"}

PERIOD_MAP = {
    "FirstHalf": 1, "SecondHalf": 2,
    "FirstPeriodOfExtraTime": 3, "SecondPeriodOfExtraTime": 4,
    "PenaltyShootout": 5,
    1: 1, 2: 2, 3: 3, 4: 4, 5: 5,
}

DEF_ACTIONS = {"Tackle", "Interception", "Clearance", "Aerial", "Block",
               "Challenge", "Dispossessed"}

GK_ACTIONS = {"Punch", "Claim", "KeeperSweeper", "KeeperPickup", "PenaltyFaced"}

# Tier base scores for "Top 5 Moments" — xT adds up to ~20 pts on top
_MOMENT_TIERS = {
    "attacker": [
        ({"Goal"},                                      100),
        ({"SavedShot", "AttemptSaved"},                  80),
        ({"GoodSkill"},                                  80),
        (None, "is_key_pass", 60),                   # key pass qualifier
        ({"TakeOn"}, "successful", 40),              # successful takeon
        ({"ShotOnPost", "MissedShot", "MissedShots", "BlockedShot"}, 25),
    ],
    "midfielder": [
        ({"Goal"},                                      100),
        (None, "is_key_pass", 80),                   # key pass qualifier
        ({"GoodSkill"},                                  80),
        ({"Tackle", "Interception"}, "successful", 65),
        (None, "is_long_ball_successful", 55),        # progressive long ball
        ({"TakeOn"}, "successful", 40),
        ({"Clearance", "Block"},                         25),
    ],
    "defender": [
        ({"Tackle"}, "successful", 100),
        ({"Block"},                                      90),
        ({"Interception"},                               75),
        ({"GoodSkill"},                                  75),
        ({"Clearance"},                                  60),
        ({"Aerial"}, "successful", 45),
    ],
}

OUTCOME_ICON  = {"Goal": "●", "SavedShot": "◉", "ShotOnPost": "◎",
                 "BlockedShot": "■", "MissedShot": "✕"}
OUTCOME_LABEL = {"Goal": "[GOAL] GOAL", "SavedShot": "[SAVE] SAVED", "ShotOnPost": "[POST] POST",
                 "BlockedShot": "[DEF] BLOCKED", "MissedShot": "[ERR] MISSED"}
OUTCOME_CLASS = {"Goal": "badge badge-goal", "SavedShot": "badge badge-saved",
                 "ShotOnPost": "badge badge-post", "BlockedShot": "badge badge-blocked",
                 "MissedShot": "badge badge-missed"}

DEF_LABEL = {
    "Tackle": "[TKL] TACKLE", "Interception": "[INT] INTERCEPTION",
    "Clearance": "[CLR] CLEARANCE", "Aerial": "[AER] AERIAL",
    "Block": "[BLK] BLOCK", "Challenge": "[CHL] CHALLENGE",
    "Dispossessed": "[DIS] DISPOSSESSED",
}
DEF_CLASS = {
    "Tackle": "badge badge-tackle", "Interception": "badge badge-interc",
    "Clearance": "badge badge-clear", "Aerial": "badge badge-aerial",
    "Block": "badge badge-block", "Challenge": "badge badge-challenge",
    "Dispossessed": "badge badge-disp",
}

HOME_COLOR = "#7ab4ff"
AWAY_COLOR = "#ff7351"

# =============================================================================
# SESSION STATE
# =============================================================================
def _ss(key, default=""):
    return st.session_state.get(key, default)

csv_path    = _ss("csv_path") or _ss("scraped_csv_path")
video_path  = _ss("video_path")
video2_path = _ss("video2_path")
split_video = _ss("split_video", False)
half1_time  = _ss("half1_time")
half2_time  = _ss("half2_time")
half3_time  = _ss("half3_time")
half4_time  = _ss("half4_time")
half5_time  = _ss("half5_time")
home_team   = _ss("scraper_home_team")
away_team   = _ss("scraper_away_team")

data_loaded = bool(csv_path and os.path.exists(csv_path))

for _k, _v in [
    ("smp_selected_idx", None), ("smp_last_click_ts", None),
    ("smp_clip_path", None), ("smp_clip_key", None), ("smp_clip_error", None),
    ("smp_pso_mode", False), ("smp_pso_selected_idx", None),
    ("pm_selected_idx", None), ("pm_last_click_ts", None),
    ("pm_clip_path", None), ("pm_clip_key", None), ("pm_clip_error", None),
    ("dm_selected_idx", None), ("dm_last_click_ts", None),
    ("dm_clip_path", None), ("dm_clip_key", None), ("dm_clip_error", None),
    ("dcm_selected_idx", None), ("dcm_last_click_ts", None),
    ("dcm_clip_path", None), ("dcm_clip_key", None), ("dcm_clip_error", None),
    ("gk_selected_idx", None), ("gk_last_click_ts", None),
    ("gk_clip_path", None), ("gk_clip_key", None), ("gk_clip_error", None),
    ("bu_selected_chain_idx", None), ("bu_clip_path", None), ("bu_clip_key", None), ("bu_clip_error", None),
    ("comp_p1_reel_path", None), ("comp_p1_reel_key", None), ("comp_p1_reel_error", None),
    ("comp_p2_reel_path", None), ("comp_p2_reel_key", None), ("comp_p2_reel_error", None),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# =============================================================================
# DATA LOADING
# =============================================================================
df_all           = None
shots_df         = None
pso_shots_df     = None
passes_df        = None
def_df           = None
dribble_carry_df = None
gk_df            = None

if data_loaded:
    try:
        df_all           = pd.read_csv(csv_path)
        pso_shots_df     = df_all[df_all["period"] == "PenaltyShootout"].copy()
        pso_shots_df     = pso_shots_df[pso_shots_df["type"].isin(SHOT_TYPES)].copy().reset_index(drop=True)
        if "period" in df_all.columns:
            df_all = df_all[df_all["period"] != "PenaltyShootout"].copy()
        shots_df         = df_all[df_all["type"].isin(SHOT_TYPES)].copy().reset_index(drop=True)
        passes_df        = df_all[df_all["type"] == "Pass"].copy().reset_index(drop=True)
        def_df           = df_all[df_all["type"].isin(DEF_ACTIONS)].copy().reset_index(drop=True)
        dribble_carry_df = df_all[df_all["type"].isin({"TakeOn", "Carry"})].copy().reset_index(drop=True)
        gk_df            = df_all[df_all["type"].isin(GK_ACTIONS)].copy().reset_index(drop=True)
        # Re-attribute own goals to the benefiting team so all filtering/display is correct
        if "is_own_goal" in shots_df.columns and home_team and away_team:
            og = shots_df["is_own_goal"].astype(bool)
            home_og = og & (shots_df["team"] == home_team)
            away_og = og & (shots_df["team"] == away_team)
            shots_df.loc[home_og, "team"] = away_team
            shots_df.loc[away_og, "team"] = home_team
        if "is_own_goal" in pso_shots_df.columns and home_team and away_team:
            og = pso_shots_df["is_own_goal"].astype(bool)
            home_og = og & (pso_shots_df["team"] == home_team)
            away_og = og & (pso_shots_df["team"] == away_team)
            pso_shots_df.loc[home_og, "team"] = away_team
            pso_shots_df.loc[away_og, "team"] = home_team
    except Exception as e:
        st.error(f"Could not load match data: {e}")

# =============================================================================
# HELPERS
# =============================================================================
def safe_float(v):
    try:
        out = float(v)
        if pd.isna(out) or out == float("inf") or out == float("-inf"):
            return None
        return out
    except:
        return None

def safe_bool(v):
    if isinstance(v, bool): return v
    if isinstance(v, str):  return v.strip().lower() in ("true","1","yes")
    try: return bool(int(v))
    except: return False

def reclassify_shot(row):
    t = row.get("type", "")
    if t == "AttemptSaved": return "SavedShot"
    if t in ("MissedShots", "Attempt"): return "MissedShot"
    return t

def fmt_time(minute, second, period):
    p = PERIOD_MAP.get(period, 1)
    label = {1:"1H",2:"2H",3:"ET1",4:"ET2",5:"PSO"}.get(p,"UNK")
    return f"{minute}'{int(second):02d}\" {label}"

def get_ffmpeg():
    import shutil
    cmd = shutil.which("ffmpeg")
    if cmd: return cmd
    try:
        from moviepy.config import FFMPEG_BINARY
        if os.path.exists(FFMPEG_BINARY): return FFMPEG_BINARY
    except Exception: pass
    raise ValueError("FFmpeg not found — please install FFmpeg.")

def _analysts_room_buffers():
    return (
        int(st.session_state.get("before_buffer", 5)),
        int(st.session_state.get("after_buffer", 8)),
    )


def cut_clip(minute, second, period_str, before=None, after=None):
    if not video_path:
        raise ValueError("No video file loaded. Go to Home and set a video path.")
    if before is None or after is None:
        default_before, default_after = _analysts_room_buffers()
        if before is None:
            before = default_before
        if after is None:
            after = default_after
    period_int = PERIOD_MAP.get(period_str, 1)
    period_offset = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0), 5: (120, 0)}
    period_start = {}
    if half1_time: period_start[1] = to_seconds(half1_time)
    if half2_time: period_start[2] = to_seconds(half2_time)
    if half3_time: period_start[3] = to_seconds(half3_time)
    if half4_time: period_start[4] = to_seconds(half4_time)
    if half5_time: period_start[5] = to_seconds(half5_time)
    if period_int not in period_start:
        raise ValueError(f"No kick-off time set for period {period_int}.")
    off_min, off_sec = period_offset.get(period_int, (0, 0))
    elapsed  = max(0, int(minute)*60 + int(second) - (off_min*60 + off_sec))
    video_ts = period_start[period_int] + elapsed
    start_ts = max(0.0, video_ts - before)
    duration = (video_ts + after) - start_ts
    src = (video2_path if split_video and period_int >= 2 and video2_path else video_path)
    ffmpeg = get_ffmpeg()
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    out = tmp.name; tmp.close()
    r = subprocess.run([
        ffmpeg, "-y", "-ss", str(start_ts), "-i", src,
        "-t", str(duration), "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "0",
        "-c:a", "aac", "-avoid_negative_ts", "make_zero", out
    ], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(f"FFmpeg error: {r.stderr[-400:]}")
    return out

# =============================================================================
# STATS BARS
# =============================================================================
def render_shot_stats():
    if shots_df is None: return
    hs  = shots_df[shots_df["team"] == home_team] if home_team else pd.DataFrame()
    as_ = shots_df[shots_df["team"] == away_team] if away_team else pd.DataFrame()
    sot = {"SavedShot", "Goal", "ShotOnPost"}
    th, ta = len(hs), len(as_); tot = th + ta
    sh = len(hs[hs["type"].isin(sot)]); sa = len(as_[as_["type"].isin(sot)])
    gh = len(hs[hs["type"] == "Goal"]); ga = len(as_[as_["type"] == "Goal"])
    share = ""
    if tot > 0:
        hp = round(th/tot*100); ap = 100 - hp
        share = f"""<div class="cm-stats-cell" style="min-width:180px"><div class="cm-stats-label">Shot share</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:6px">
            <span class="cm-stats-home" style="font-size:13px;min-width:28px">{hp}%</span>
            <div style="flex:1;height:8px;background:#2c2c2c;border-radius:4px;overflow:hidden">
            <div style="width:{hp}%;height:100%;background:{HOME_COLOR};border-radius:4px"></div></div>
            <span class="cm-stats-away" style="font-size:13px;min-width:28px">{ap}%</span></div></div>"""
    html = f"""<div class="cm-stats-bar">{share}
        <div class="cm-stats-cell"><div class="cm-stats-label">Shots</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{th}</span><span style="color:#2c2c2c;font-size:18px">—</span><span class="cm-stats-away">{ta}</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">On Target</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{sh}</span><span style="color:#2c2c2c;font-size:18px">—</span><span class="cm-stats-away">{sa}</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">Goals</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{gh}</span><span style="color:#2c2c2c;font-size:18px">—</span><span class="cm-stats-away">{ga}</span></div></div>
    </div>"""
    st.markdown(_h(html), unsafe_allow_html=True)

def render_pass_stats(df):
    if df is None or df.empty: return
    tot   = len(df)
    succ  = len(df[df["outcomeType"] == "Successful"]) if "outcomeType" in df.columns else 0
    acc   = round(succ / tot * 100) if tot > 0 else 0
    kp    = int(df["is_key_pass"].sum()) if "is_key_pass" in df.columns else 0
    cross = int(df["is_cross"].sum())    if "is_cross"    in df.columns else 0
    html  = f"""<div class="cm-stats-bar">
        <div class="cm-stats-cell"><div class="cm-stats-label">Passes</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{tot}</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">Accuracy</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{acc}%</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">Key Passes</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{kp}</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">Crosses</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{cross}</span></div></div>
    </div>"""
    st.markdown(_h(html), unsafe_allow_html=True)

def render_def_stats(df):
    if df is None or df.empty: return
    counts = df["type"].value_counts()
    cells  = "".join(
        f'<div class="cm-stats-cell"><div class="cm-stats-label">{t}</div>'
        f'<div class="cm-stats-split"><span class="cm-stats-home">{counts.get(t, 0)}</span></div></div>'
        for t in ["Tackle", "Interception", "Clearance", "Aerial", "Block", "Challenge", "Dispossessed"]
        if counts.get(t, 0) > 0
    )
    st.markdown(_h(f'<div class="cm-stats-bar">{cells}</div>'), unsafe_allow_html=True)


def _filter_by_pitch_zone(df, selected_zone):
    if df is None or df.empty or not selected_zone:
        return df
    zone_series = _effective_pitch_zone_series(df)
    combined_pitch_zones = {
        "Entire Left Side": ["Left Wing", "Left Half Space"],
        "Entire Right Side": ["Right Wing", "Right Half Space"],
    }
    if selected_zone in combined_pitch_zones:
        return df[zone_series.isin(combined_pitch_zones[selected_zone])]
    return df[zone_series == selected_zone]


# =============================================================================
# WATCH PANEL
# =============================================================================
def render_watch_panel(row, prefix, label_fn):
    minute_val = row.get("minute", 0)
    second_val = row.get("second", 0)
    period_val = row.get("period", "FirstHalf")
    player_val = row.get("playerName", "")
    event_key  = f"{minute_val}_{second_val}_{period_val}_{player_val}"
    clip_label = theme.ui_html(f"[CLIP]  {player_val} · {fmt_time(minute_val, second_val, period_val)}")

    existing_clip = st.session_state.get(f"{prefix}_clip_path")
    existing_key  = st.session_state.get(f"{prefix}_clip_key")
    clip_error    = st.session_state.get(f"{prefix}_clip_error")

    st.markdown(f"<div><strong>{clip_label}</strong></div>", unsafe_allow_html=True)

    if existing_key == event_key and existing_clip and os.path.exists(existing_clip):
        with open(existing_clip, "rb") as _vf:
            st.video(_vf.read())
        with open(existing_clip, "rb") as _dl:
            safe_name = re.sub(r"[^\w\-.]", "_", f"{player_val}_{minute_val}.mp4")
            st.download_button("Download clip", data=_dl.read(),
                               file_name=safe_name, mime="video/mp4",
                               use_container_width=True,
                               icon=theme.icon_shortcode("[DL]"))
    elif clip_error and existing_key == event_key:
        st.error(f"Could not cut clip: {clip_error}")
        if st.button("Retry", use_container_width=True, key=f"{prefix}_retry", icon=theme.icon_shortcode("[RETRY]")):
            st.session_state[f"{prefix}_clip_error"] = None
            st.session_state[f"{prefix}_clip_key"]   = None
            st.rerun()
    else:
        if st.button("Watch", type="primary", use_container_width=True, key=f"{prefix}_watch", icon=theme.icon_shortcode("[RUN]")):
            with st.spinner("Cutting clip…"):
                try:
                    path = cut_clip(minute_val, second_val, period_val)
                    st.session_state[f"{prefix}_clip_path"]  = path
                    st.session_state[f"{prefix}_clip_key"]   = event_key
                    st.session_state[f"{prefix}_clip_error"] = None
                    st.rerun()
                except Exception as e:
                    st.session_state[f"{prefix}_clip_error"] = str(e)
                    st.session_state[f"{prefix}_clip_key"]   = event_key
                    st.rerun()

# handle_click: only updates state, no rerun — fragment handles re-execution
def handle_click(raw_click, prefix):
    clicked_idx = None
    click_ts    = None
    if isinstance(raw_click, (list, tuple)) and len(raw_click) >= 2:
        clicked_idx, click_ts = raw_click[0], raw_click[1]
    elif isinstance(raw_click, (int, float)) and raw_click is not None:
        clicked_idx, click_ts = int(raw_click), 0
    last_ts = st.session_state.get(f"{prefix}_last_click_ts")
    if clicked_idx is not None and click_ts != last_ts:
        st.session_state[f"{prefix}_last_click_ts"]  = click_ts
        st.session_state[f"{prefix}_selected_idx"]   = clicked_idx
        st.session_state["smp_clip_path"]            = None
        st.session_state["smp_clip_key"]             = None
        st.session_state["smp_clip_error"]           = None
        st.rerun()

# =============================================================================
# HEADER
# =============================================================================
_logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ClipMaker_logo.png")
_b64 = theme.load_logo_b64(_logo_path)
st.markdown(theme.logo_header("The Analyst's Room", "Visualise match events as interactive charts and maps", _b64 or None), unsafe_allow_html=True)

st.divider()

if not data_loaded:
    st.markdown("""<div class="cm-no-data-msg">
        <div style="font-size:40px;margin-bottom:16px">{}</div>
        <b style="color:#ccc;font-size:17px">No match data loaded</b><br><br>
        Go to <b>Home</b> and scrape a match first.
    </div>""".format(theme.icon_span("[SEARCH]", color="#ccc", size=40)), unsafe_allow_html=True)
    st.stop()

# =============================================================================
# TABS
# =============================================================================
tab_shot, tab_pass, tab_def, tab_dc, tab_gk, tab_bu, tab_comp = st.tabs([
    "◉ Shot Map",
    "◎ Pass Map",
    "■ Defensive Actions",
    "◈ Dribbles & Carries",
    "⊞ Goalkeeper",
    "↗ Build-Up",
    "⇄ Comparison",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — SHOT MAP
# ─────────────────────────────────────────────────────────────────────────────
@st.fragment
def render_shot_tab():
    if shots_df is None or shots_df.empty:
        st.info("No shot data found in the loaded CSV.")
        return

    has_pso = pso_shots_df is not None and not pso_shots_df.empty

    if has_pso:
        mode = st.radio("Mode", ["Normal", "Penalty Shootout"], horizontal=True,
                       key="smp_mode_radio", label_visibility="collapsed")
    else:
        mode = st.radio("Mode", ["Normal"], horizontal=True, disabled=True,
                       key="smp_mode_radio", label_visibility="collapsed")
        st.caption("⊘ No penalty shootout data in this match")

    if mode == "Penalty Shootout":
        pso_shots = pso_shots_df.copy()
        
        if pso_shots.empty:
            st.info("No penalty shootout shots found.")
            return

        render_shot_stats()

        def shot_to_dict(idx, row):
            return {
                "df_idx": int(idx), "is_home": bool(row.get("team", "") == home_team),
                "team": str(row.get("team", "")), "playerName": str(row.get("playerName", "")),
                "minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
                "period": str(row.get("period", "")), "type": reclassify_shot(row),
                "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
                "goal_mouth_y": safe_float(row.get("goal_mouth_y")),
                "goal_mouth_z": safe_float(row.get("goal_mouth_z")),
            }

        shots_for_comp = [shot_to_dict(idx, row) for idx, row in pso_shots.iterrows()]
        pso_sel_idx = st.session_state.get("smp_pso_selected_idx")

        if pso_sel_idx is not None:
            if st.button("Clear selection", key="smp_pso_clear_sel"):
                st.session_state["smp_pso_selected_idx"] = None
                st.session_state["smp_clip_path"]        = None
                st.session_state["smp_clip_key"]         = None
                st.session_state["smp_clip_error"]       = None
                st.rerun()

        if pso_sel_idx is not None and pso_sel_idx in pso_shots.index:
            sel_row = pso_shots.loc[pso_sel_idx]
            shot_map([shot_to_dict(pso_sel_idx, sel_row)], home_team=home_team or "",
                     away_team=away_team or "", selected_idx=pso_sel_idx,
                     view="goalframe", key="smp_pso_gf")

        raw_click = shot_map(shots_for_comp, home_team=home_team or "",
                            away_team=away_team or "", selected_idx=pso_sel_idx,
                            view="halfpitch_vert", key="smp_pso_pitch")
        handle_click(raw_click, "smp_pso")

        st.markdown(
            "<div style='font-size:11px;color:#767575;margin-top:-4px'>"
            f"● Goal &nbsp;◯ Saved / Post &nbsp;{theme.icon_span('[X]', color='#ff7351', size=12)} Missed &nbsp;·&nbsp;"
            "Click a penalty to inspect it</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        def shot_label(row):
            icon   = OUTCOME_ICON.get(reclassify_shot(row), "✕")
            period = row.get("period", "")
            et     = " ET" if "ExtraTime" in str(period) else ""
            return f"{icon}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"{et}  {row.get('playerName','Unknown')}  ({row.get('team','')})"

        pso_indices = list(pso_shots.index)
        labels = ["— Select a penalty to inspect —"] + [shot_label(r) for _, r in pso_shots.iterrows()]
        cur_idx = st.session_state.get("smp_pso_selected_idx")
        sel_pos = pso_indices.index(cur_idx) + 1 if cur_idx in pso_indices else 0
        chosen  = st.selectbox("Select a penalty", labels, index=sel_pos, key="smp_pso_shot_sel")
        if chosen != "— Select a penalty to inspect —":
            new_idx = pso_indices[labels.index(chosen) - 1]
            if new_idx != st.session_state.get("smp_pso_selected_idx"):
                st.session_state["smp_pso_selected_idx"] = new_idx
                st.session_state["smp_clip_path"]        = None
                st.session_state["smp_clip_key"]         = None
                st.session_state["smp_clip_error"]       = None
                st.rerun()

        pso_sel = st.session_state.get("smp_pso_selected_idx")
        if pso_sel is not None and pso_sel in pso_shots_df.index:
            row        = pso_shots_df.loc[pso_sel].to_dict()
            s_type     = reclassify_shot(row)
            team       = row.get("team", "")
            accent     = HOME_COLOR if team == home_team else AWAY_COLOR
            is_head     = safe_bool(row.get("is_header", ""))
            is_bc       = safe_bool(row.get("is_big_chance_shot", ""))
            is_penalty  = safe_bool(row.get("is_penalty", ""))
            is_volley   = safe_bool(row.get("is_volley", ""))
            is_chipped  = safe_bool(row.get("is_chipped", ""))
            is_dcfc     = safe_bool(row.get("is_direct_from_corner", ""))
            is_lfoot    = safe_bool(row.get("is_left_foot", ""))
            is_rfoot    = safe_bool(row.get("is_right_foot", ""))
            is_fb       = safe_bool(row.get("is_fast_break", ""))
            extras      = " · ".join(x for x in [
                "Header"            if is_head    else "",
                "Big Chance"        if is_bc      else "",
                "Penalty"           if is_penalty else "",
                "Volley"            if is_volley  else "",
                "Chipped"           if is_chipped else "",
                "Direct from Corner" if is_dcfc   else "",
                "Left Foot"         if is_lfoot   else "",
                "Right Foot"        if is_rfoot   else "",
                "Fast Break"        if is_fb      else "",
            ] if x) or "—"
            badge_cls  = OUTCOME_CLASS.get(s_type, "badge badge-missed")
            badge_lbl  = theme.ui_html(OUTCOME_LABEL.get(s_type, "[ERR] MISSED"))
            minute_v   = row.get("minute", 0); second_v = row.get("second", 0); period_v = row.get("period", "")

            st.divider()
            dc, vc = st.columns([1, 1], gap="large")
            with dc:
                st.markdown(_h(f"""<div class="cm-shot-panel">
                    <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','Unknown')}</div>
                    <div class="cm-panel-sub">{team} · {fmt_time(minute_v, second_v, period_v)}</div>
                    <span class="{badge_cls}">{badge_lbl}</span>
                    <div style="margin-top:12px">
                        <div class="cm-detail-label">Qualifier</div>
                        <div class="cm-detail-value">{extras}</div>
                    </div>
                </div>"""), unsafe_allow_html=True)
            with vc:
                render_watch_panel(row, "smp", shot_label)
        return

    radio_opts = []
    if home_team: radio_opts.append(home_team)
    if away_team: radio_opts.append(away_team)
    if not radio_opts:
        radio_opts = sorted(shots_df["team"].dropna().unique().tolist())[:2]

    team_sel = st.radio("Team", radio_opts, horizontal=True, key="smp_team_radio",
                        label_visibility="collapsed")

    all_shot_players  = sorted(shots_df["playerName"].dropna().unique()) if "playerName" in shots_df.columns else []
    team_shot_players = [p for p in all_shot_players
                         if p in shots_df[shots_df["team"] == team_sel]["playerName"].values]
    player_filter_shot = st.selectbox("Player", ["All players"] + team_shot_players,
                                      label_visibility="collapsed", key="smp_player_sel")

    smp_pitch_zone = st.selectbox(
        "Pitch Zone",
        options=["", "Entire Left Side", "Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing", "Entire Right Side"],
        format_func=lambda x: "Any pitch zone" if x == "" else x,
        key="smp_pitch_zone_sel",
        label_visibility="collapsed",
    )

    _smp_fkey = f"{team_sel}|{player_filter_shot}|{smp_pitch_zone}"
    if st.session_state.get("_smp_last_filter") != _smp_fkey:
        st.session_state["_smp_last_filter"] = _smp_fkey
        st.session_state["smp_selected_idx"] = None
        st.session_state["smp_clip_path"]    = None
        st.session_state["smp_clip_key"]     = None
        st.session_state["smp_clip_error"]   = None

    render_shot_stats()

    disp_shots = shots_df[shots_df["team"] == team_sel].copy()
    if player_filter_shot != "All players":
        disp_shots = disp_shots[disp_shots["playerName"] == player_filter_shot]
    disp_shots = _filter_by_pitch_zone(disp_shots, smp_pitch_zone)

    if disp_shots.empty:
        st.info("No shots match the current filter.")
        return

    def shot_to_dict(idx, row):
        return {
            "df_idx": int(idx), "is_home": bool(row.get("team", "") == home_team),
            "team": str(row.get("team", "")), "playerName": str(row.get("playerName", "")),
            "minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
            "period": str(row.get("period", "")), "type": reclassify_shot(row),
            "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
            "goal_mouth_y": safe_float(row.get("goal_mouth_y")),
            "goal_mouth_z": safe_float(row.get("goal_mouth_z")),
        }

    shots_for_comp = [shot_to_dict(idx, row) for idx, row in disp_shots.iterrows()]
    sel_idx = st.session_state.get("smp_selected_idx")

    if sel_idx is not None:
        if st.button("Clear selection", key="smp_clear_sel"):
            st.session_state["smp_selected_idx"] = None
            st.session_state["smp_clip_path"]    = None
            st.session_state["smp_clip_key"]     = None
            st.session_state["smp_clip_error"]   = None
            st.rerun()

    if sel_idx is not None and sel_idx in disp_shots.index:
        sel_row  = disp_shots.loc[sel_idx]
        shot_map([shot_to_dict(sel_idx, sel_row)], home_team=home_team or "",
                 away_team=away_team or "", selected_idx=sel_idx,
                 view="goalframe", key="smp_gf")

    raw_click = shot_map(shots_for_comp, home_team=home_team or "",
                         away_team=away_team or "", selected_idx=sel_idx,
                         view="halfpitch_vert", key="smp_pitch")
    handle_click(raw_click, "smp")

    st.markdown(
        "<div style='font-size:11px;color:#767575;margin-top:-4px'>"
        f"● Goal &nbsp;◯ Saved / Post &nbsp;{theme.icon_span('[X]', color='#ff7351', size=12)} Missed &nbsp;·&nbsp;"
        "Click a shot to inspect it</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    def shot_label(row):
        icon   = OUTCOME_ICON.get(reclassify_shot(row), "✕")
        period = row.get("period", "")
        et     = " ET" if "ExtraTime" in str(period) else ""
        return f"{icon}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"{et}  {row.get('playerName','Unknown')}  ({row.get('team','')})"

    disp_indices = list(disp_shots.index)
    labels = ["— Select a shot to inspect —"] + [shot_label(r) for _, r in disp_shots.iterrows()]
    cur_idx = st.session_state.get("smp_selected_idx")
    sel_pos = disp_indices.index(cur_idx) + 1 if cur_idx in disp_indices else 0
    chosen  = st.selectbox("Select a shot", labels, index=sel_pos, key="smp_shot_sel")
    if chosen != "— Select a shot to inspect —":
        new_idx = disp_indices[labels.index(chosen) - 1]
        if new_idx != st.session_state.get("smp_selected_idx"):
            st.session_state["smp_selected_idx"] = new_idx
            st.session_state["smp_clip_path"]    = None
            st.session_state["smp_clip_key"]     = None
            st.session_state["smp_clip_error"]   = None
            st.rerun()

    sel_idx = st.session_state.get("smp_selected_idx")
    if sel_idx is not None and sel_idx in shots_df.index:
        row        = shots_df.loc[sel_idx].to_dict()
        s_type     = reclassify_shot(row)
        team       = row.get("team", "")
        accent     = HOME_COLOR if team == home_team else AWAY_COLOR
        is_head     = safe_bool(row.get("is_header", ""))
        is_bc       = safe_bool(row.get("is_big_chance_shot", ""))
        is_penalty  = safe_bool(row.get("is_penalty", ""))
        is_volley   = safe_bool(row.get("is_volley", ""))
        is_chipped  = safe_bool(row.get("is_chipped", ""))
        is_dcfc     = safe_bool(row.get("is_direct_from_corner", ""))
        is_lfoot    = safe_bool(row.get("is_left_foot", ""))
        is_rfoot    = safe_bool(row.get("is_right_foot", ""))
        is_fb       = safe_bool(row.get("is_fast_break", ""))
        extras      = " · ".join(x for x in [
            "Header"            if is_head    else "",
            "Big Chance"        if is_bc      else "",
            "Penalty"           if is_penalty else "",
            "Volley"            if is_volley  else "",
            "Chipped"           if is_chipped else "",
            "Direct from Corner" if is_dcfc   else "",
            "Left Foot"         if is_lfoot   else "",
            "Right Foot"        if is_rfoot   else "",
            "Fast Break"        if is_fb      else "",
        ] if x) or "—"
        badge_cls  = OUTCOME_CLASS.get(s_type, "badge badge-missed")
        badge_lbl  = theme.ui_html(OUTCOME_LABEL.get(s_type, "[ERR] MISSED"))
        minute_v   = row.get("minute", 0); second_v = row.get("second", 0); period_v = row.get("period", "")

        st.divider()
        dc, vc = st.columns([1, 1], gap="large")
        with dc:
            st.markdown(_h(f"""<div class="cm-shot-panel">
                <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','Unknown')}</div>
                <div class="cm-panel-sub">{team} · {fmt_time(minute_v, second_v, period_v)}</div>
                <span class="{badge_cls}">{badge_lbl}</span>
                <div style="margin-top:12px">
                    <div class="cm-detail-label">Qualifier</div>
                    <div class="cm-detail-value">{extras}</div>
                </div>
            </div>"""), unsafe_allow_html=True)
        with vc:
            render_watch_panel(row, "smp", shot_label)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — PASS MAP
# ─────────────────────────────────────────────────────────────────────────────
@st.fragment
def render_pass_tab():
    if passes_df is None or passes_df.empty:
        st.info("No pass data found in the loaded CSV.")
        return

    PASS_NETWORK = "Pass Network"
    radio_pass_opts = [PASS_NETWORK]
    if home_team: radio_pass_opts.append(home_team)
    if away_team: radio_pass_opts.append(away_team)

    view_sel = st.radio("View", radio_pass_opts, horizontal=True,
                        key="pm_view_radio", label_visibility="collapsed")

    if view_sel == PASS_NETWORK:
        subs_on = set()
        if df_all is not None and "type" in df_all.columns:
            subs_on = set(df_all[df_all["type"] == "SubstitutionOn"]["playerName"].dropna().unique())

        all_net_passes = []
        for idx, row in passes_df.iterrows():
            if pd.isna(safe_float(row.get("x"))) or pd.isna(safe_float(row.get("endX"))):
                continue
            pname = str(row.get("playerName", ""))
            all_net_passes.append({
                "df_idx": int(idx),
                "playerName": pname,
                "team": str(row.get("team", "")),
                "is_home": bool(row.get("team", "") == home_team),
                "is_starter": pname not in subs_on,
                "minute": int(row.get("minute", 0)),
                "second": int(row.get("second", 0)),
                "period": str(row.get("period", "")),
                "x": safe_float(row.get("x")),
                "y": safe_float(row.get("y")),
                "endX": safe_float(row.get("endX")),
                "endY": safe_float(row.get("endY")),
                "successful": str(row.get("outcomeType", "")).lower() == "successful",
                "is_key_pass": safe_bool(row.get("is_key_pass", False)),
                "mode": "network",
            })

        ht = passes_df[passes_df["team"] == home_team] if home_team else pd.DataFrame()
        at = passes_df[passes_df["team"] == away_team] if away_team else pd.DataFrame()

        def pass_acc(df):
            if df.empty: return "—"
            s = len(df[df["outcomeType"] == "Successful"]) if "outcomeType" in df.columns else 0
            return f"{round(s/len(df)*100)}%"

        html = f"""<div class="cm-stats-bar">
            <div class="cm-stats-cell"><div class="cm-stats-label">Passes</div>
                <div class="cm-stats-split">
                    <span class="cm-stats-home">{len(ht)}</span>
                    <span style="color:#2c2c2c;font-size:18px">—</span>
                    <span class="cm-stats-away">{len(at)}</span>
                </div></div>
            <div class="cm-stats-cell"><div class="cm-stats-label">Accuracy</div>
                <div class="cm-stats-split">
                    <span class="cm-stats-home">{pass_acc(ht)}</span>
                    <span style="color:#2c2c2c;font-size:18px">—</span>
                    <span class="cm-stats-away">{pass_acc(at)}</span>
                </div></div>
            <div class="cm-stats-cell"><div class="cm-stats-label">Key Passes</div>
                <div class="cm-stats-split">
                    <span class="cm-stats-home">{int(ht['is_key_pass'].sum()) if 'is_key_pass' in ht.columns else 0}</span>
                    <span style="color:#2c2c2c;font-size:18px">—</span>
                    <span class="cm-stats-away">{int(at['is_key_pass'].sum()) if 'is_key_pass' in at.columns else 0}</span>
                </div></div>
        </div>"""
        st.markdown(_h(html), unsafe_allow_html=True)

        pass_map(passes=all_net_passes, home_team=home_team or "",
                 away_team=away_team or "", selected_idx=None,
                 mode="network", key="pm_network")

        st.markdown("<div style='font-size:11px;color:#767575;margin-top:4px'>"
                    "Node colour intensity = pass volume · "
                    "Line colour intensity = connection frequency</div>",
                    unsafe_allow_html=True)

    else:
        team_passes       = passes_df[passes_df["team"] == view_sel].copy()
        team_pass_players = sorted(team_passes["playerName"].dropna().unique().tolist()) if "playerName" in team_passes.columns else []

        player_sel = st.selectbox("Player", ["— Select a player —"] + team_pass_players,
                                  label_visibility="collapsed", key="pm_player_sel")

        pass_type_opts = ["All passes"]
        bool_cols_present = {
            "Key passes":          "is_key_pass",
            "Crosses":             "is_cross",
            "Long balls":          "is_long_ball",
            "Switches of play":    "is_switch_of_play",
            "Diagonals":           "is_diagonal_long_ball",
            "Through balls":       "is_through_ball",
            "Deep completions":    "is_deep_completion",
            "Box entry passes":    "is_box_entry_pass",
            "Final 3rd entries":   "is_final_third_entry_pass",
            "Big chances created": "is_big_chance",
            "Assist (thru ball)":  "is_assist_throughball",
            "Assist (cross)":      "is_assist_cross",
            "Assist (corner)":     "is_assist_corner",
            "Assist (free kick)":  "is_assist_freekick",
            "Touch in box":        "is_touch_in_box",
        }
        available_pass_types = {k: v for k, v in bool_cols_present.items() if v in passes_df.columns}
        pass_type_sel = st.radio("Pass type", ["All passes"] + list(available_pass_types.keys()),
                                 horizontal=True, key="pm_type_radio", label_visibility="collapsed")

        _pm_z1, _pm_z2 = st.columns(2)
        with _pm_z1:
            pm_pitch_zone = st.selectbox(
                "Pitch Zone",
                options=["", "Entire Left Side", "Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing", "Entire Right Side"],
                format_func=lambda x: "Any pitch zone" if x == "" else x,
                key="pm_pitch_zone_sel",
                label_visibility="collapsed",
            )
        with _pm_z2:
            pm_depth_zone = st.selectbox(
                "Depth Zone",
                options=["", "Defensive Third", "Middle Third", "Attacking Third"],
                format_func=lambda x: "Any depth zone" if x == "" else x,
                key="pm_depth_zone_sel",
                label_visibility="collapsed",
            )

        _pm_fkey = f"{view_sel}|{player_sel}|{pass_type_sel}|{pm_pitch_zone}|{pm_depth_zone}"
        if st.session_state.get("_pm_last_filter") != _pm_fkey:
            st.session_state["_pm_last_filter"] = _pm_fkey
            st.session_state["pm_selected_idx"] = None
            st.session_state["pm_clip_path"]    = None
            st.session_state["pm_clip_key"]     = None
            st.session_state["pm_clip_error"]   = None

        if player_sel == "— Select a player —":
            st.markdown("""<div class="cm-no-data-msg" style="padding:40px 20px">
                <div style="font-size:32px;margin-bottom:12px">{}</div>
                Select a player above to view their pass map
            </div>""".format(theme.icon_span("[PASS]", color="#ccc", size=32)), unsafe_allow_html=True)
        else:
            player_passes = team_passes[team_passes["playerName"] == player_sel].copy()
            if pass_type_sel != "All passes" and pass_type_sel in available_pass_types:
                col = available_pass_types[pass_type_sel]
                player_passes = player_passes[player_passes[col] == True]
            player_passes = _filter_by_pitch_zone(player_passes, pm_pitch_zone)
            if pm_depth_zone and "depth_zone" in player_passes.columns:
                player_passes = player_passes[player_passes["depth_zone"] == pm_depth_zone]
            player_passes = player_passes.dropna(subset=["x", "endX"])

            render_pass_stats(player_passes)

            if player_passes.empty:
                st.info("No passes match the current filter.")
                return

            passes_for_comp = []
            for idx, row in player_passes.iterrows():
                passes_for_comp.append({
                    "df_idx": int(idx),
                    "playerName": str(row.get("playerName", "")),
                    "team": str(row.get("team", "")),
                    "is_home": bool(row.get("team", "") == home_team),
                    "minute": int(row.get("minute", 0)),
                    "second": int(row.get("second", 0)),
                    "period": str(row.get("period", "")),
                    "x": safe_float(row.get("x")),
                    "y": safe_float(row.get("y")),
                    "endX": safe_float(row.get("endX")),
                    "endY": safe_float(row.get("endY")),
                    "successful": str(row.get("outcomeType", "")).lower() == "successful",
                    "is_key_pass":           safe_bool(row.get("is_key_pass", False)),
                    "is_cross":              safe_bool(row.get("is_cross", False)),
                    "is_long_ball":          safe_bool(row.get("is_long_ball", False)),
                    "is_switch_of_play":     safe_bool(row.get("is_switch_of_play", False)),
                    "is_diagonal_long_ball": safe_bool(row.get("is_diagonal_long_ball", False)),
                    "is_through_ball":       safe_bool(row.get("is_through_ball", False)),
                    "is_big_chance":         safe_bool(row.get("is_big_chance", False)),
                    "is_assist_throughball": safe_bool(row.get("is_assist_throughball", False)),
                    "is_assist_cross":       safe_bool(row.get("is_assist_cross", False)),
                    "is_assist_corner":      safe_bool(row.get("is_assist_corner", False)),
                    "is_assist_freekick":    safe_bool(row.get("is_assist_freekick", False)),
                    "is_intentional_assist": safe_bool(row.get("is_intentional_assist", False)),
                    "is_fast_break":         safe_bool(row.get("is_fast_break", False)),
                    "is_touch_in_box":       safe_bool(row.get("is_touch_in_box", False)),
                    "mode": "player",
                })

            pm_sel_idx = st.session_state.get("pm_selected_idx")
            if pm_sel_idx is not None:
                if st.button("Clear selection", key="pm_clear_sel"):
                    st.session_state["pm_selected_idx"] = None
                    st.session_state["pm_clip_path"]    = None
                    st.session_state["pm_clip_key"]     = None
                    st.session_state["pm_clip_error"]   = None
                    st.rerun()

            raw_pm = pass_map(passes=passes_for_comp, home_team=home_team or "",
                              away_team=away_team or "", selected_idx=pm_sel_idx,
                              mode="player", key="pm_player")
            handle_click(raw_pm, "pm")

            st.markdown("<div style='font-size:11px;color:#767575;margin-top:-4px'>"
                        "<span style='color:#7ab4ff'>●</span> Successful &nbsp;"
                        "<span style='color:#ff7351'>●</span> Unsuccessful &nbsp;·&nbsp;"
                        "Click a pass endpoint to inspect it</div>",
                        unsafe_allow_html=True)

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            def pass_label(row):
                outcome = "✓" if str(row.get("outcomeType", "")).lower() == "successful" else "✕"
                kp = " ◆" if safe_bool(row.get("is_key_pass", False)) else ""
                return f"{outcome}{kp}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"  {row.get('playerName','Unknown')}"

            pm_indices = list(player_passes.index)
            pm_labels  = ["— Select a pass to inspect —"] + [pass_label(r) for _, r in player_passes.iterrows()]
            cur_pm     = st.session_state.get("pm_selected_idx")
            pm_pos     = pm_indices.index(cur_pm) + 1 if cur_pm in pm_indices else 0
            pm_chosen  = st.selectbox("Select a pass", pm_labels, index=pm_pos, key="pm_pass_sel")

            if pm_chosen != "— Select a pass to inspect —":
                new_pm_idx = pm_indices[pm_labels.index(pm_chosen) - 1]
                if new_pm_idx != st.session_state.get("pm_selected_idx"):
                    st.session_state["pm_selected_idx"] = new_pm_idx
                    st.session_state["pm_clip_path"]    = None
                    st.session_state["pm_clip_key"]     = None
                    st.session_state["pm_clip_error"]   = None
                    st.rerun()

            pm_sel = st.session_state.get("pm_selected_idx")
            if pm_sel is not None and pm_sel in passes_df.index:
                row      = passes_df.loc[pm_sel].to_dict()
                team     = row.get("team", "")
                accent   = HOME_COLOR if team == home_team else AWAY_COLOR
                outcome  = row.get("outcomeType", "")
                badge_c  = "badge badge-success" if outcome == "Successful" else "badge badge-fail"
                badge_l  = theme.ui_html("[OK] SUCCESSFUL" if outcome == "Successful" else "[ERR] UNSUCCESSFUL")
                tags     = " · ".join(x for x in [
                    "Key Pass"            if safe_bool(row.get("is_key_pass"))            else "",
                    "Cross"               if safe_bool(row.get("is_cross"))               else "",
                    "Long Ball"           if safe_bool(row.get("is_long_ball"))           else "",
                    "Switch of Play"      if safe_bool(row.get("is_switch_of_play"))      else "",
                    "Diagonal"            if safe_bool(row.get("is_diagonal_long_ball"))  else "",
                    "Through Ball"        if safe_bool(row.get("is_through_ball"))        else "",
                    "Big Chance Created"  if safe_bool(row.get("is_big_chance"))          else "",
                    "Assist (Through Ball)" if safe_bool(row.get("is_assist_throughball")) else "",
                    "Assist (Cross)"      if safe_bool(row.get("is_assist_cross"))        else "",
                    "Assist (Corner)"     if safe_bool(row.get("is_assist_corner"))       else "",
                    "Assist (Free Kick)"  if safe_bool(row.get("is_assist_freekick"))     else "",
                    "Intentional Assist"  if safe_bool(row.get("is_intentional_assist"))  else "",
                    "Fast Break"          if safe_bool(row.get("is_fast_break"))          else "",
                    "Touch in Box"        if safe_bool(row.get("is_touch_in_box"))        else "",
                ] if x) or "—"

                st.divider()
                dc, vc = st.columns([1, 1], gap="large")
                with dc:
                    st.markdown(_h(f"""<div class="cm-event-panel">
                        <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','Unknown')}</div>
                        <div class="cm-panel-sub">{team} · {fmt_time(row.get('minute',0), row.get('second',0), row.get('period',''))}</div>
                        <span class="{badge_c}">{badge_l}</span>
                        <div style="margin-top:12px">
                            <div class="cm-detail-label">Qualifiers</div>
                            <div class="cm-detail-value">{tags}</div>
                        </div>
                    </div>"""), unsafe_allow_html=True)
                with vc:
                    render_watch_panel(row, "pm", pass_label)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — DEFENSIVE ACTIONS
# ─────────────────────────────────────────────────────────────────────────────
@st.fragment
def render_def_tab():
    if def_df is None or def_df.empty:
        st.info("No defensive action data found in the loaded CSV.")
        return

    radio_def_opts = []
    if home_team: radio_def_opts.append(home_team)
    if away_team: radio_def_opts.append(away_team)
    if not radio_def_opts:
        radio_def_opts = sorted(def_df["team"].dropna().unique().tolist())[:2]

    def_team_sel = st.radio("Team", radio_def_opts, horizontal=True,
                            key="dm_team_radio", label_visibility="collapsed")

    team_def       = def_df[def_df["team"] == def_team_sel].copy()
    def_players    = sorted(team_def["playerName"].dropna().unique().tolist()) if "playerName" in team_def.columns else []
    def_player_sel = st.selectbox("Player", ["— Select a player —"] + def_players,
                                  label_visibility="collapsed", key="dm_player_sel")

    _dm_z1, _dm_z2 = st.columns(2)
    with _dm_z1:
        dm_pitch_zone = st.selectbox(
            "Pitch Zone",
            options=["", "Entire Left Side", "Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing", "Entire Right Side"],
            format_func=lambda x: "Any pitch zone" if x == "" else x,
            key="dm_pitch_zone_sel",
            label_visibility="collapsed",
        )
    with _dm_z2:
        dm_depth_zone = st.selectbox(
            "Depth Zone",
            options=["", "Defensive Third", "Middle Third", "Attacking Third"],
            format_func=lambda x: "Any depth zone" if x == "" else x,
            key="dm_depth_zone_sel",
            label_visibility="collapsed",
        )

    _dm_fkey = f"{def_team_sel}|{def_player_sel}|{dm_pitch_zone}|{dm_depth_zone}"
    if st.session_state.get("_dm_last_filter") != _dm_fkey:
        st.session_state["_dm_last_filter"] = _dm_fkey
        st.session_state["dm_selected_idx"] = None
        st.session_state["dm_clip_path"]    = None
        st.session_state["dm_clip_key"]     = None
        st.session_state["dm_clip_error"]   = None

    if def_player_sel == "— Select a player —":
        render_def_stats(team_def)
        st.markdown("""<div class="cm-no-data-msg" style="padding:40px 20px">
            <div style="font-size:32px;margin-bottom:12px">{}</div>
            Select a player above to view their defensive actions
        </div>""".format(theme.icon_span("[DEF]", color="#ccc", size=32)), unsafe_allow_html=True)
        return

    player_def = team_def[team_def["playerName"] == def_player_sel].copy()
    player_def = _filter_by_pitch_zone(player_def, dm_pitch_zone)
    if dm_depth_zone and "depth_zone" in player_def.columns:
        player_def = player_def[player_def["depth_zone"] == dm_depth_zone]
    render_def_stats(player_def)

    if player_def.empty:
        st.info("No defensive actions found for this player.")
        return

    def_for_comp = []
    for idx, row in player_def.iterrows():
        def_for_comp.append({
            "df_idx": int(idx),
            "playerName": str(row.get("playerName", "")),
            "team": str(row.get("team", "")),
            "is_home": bool(row.get("team", "") == home_team),
            "minute": int(row.get("minute", 0)),
            "second": int(row.get("second", 0)),
            "period": str(row.get("period", "")),
            "type": str(row.get("type", "")),
            "outcomeType": str(row.get("outcomeType", "")),
            "x": safe_float(row.get("x")),
            "y": safe_float(row.get("y")),
        })

    dm_sel_idx = st.session_state.get("dm_selected_idx")
    if dm_sel_idx is not None:
        if st.button("Clear selection", key="dm_clear_sel"):
            st.session_state["dm_selected_idx"] = None
            st.session_state["dm_clip_path"]    = None
            st.session_state["dm_clip_key"]     = None
            st.session_state["dm_clip_error"]   = None
            st.rerun()

    raw_dm = defensive_map(actions=def_for_comp, home_team=home_team or "",
                           away_team=away_team or "", selected_idx=dm_sel_idx,
                           key="dm_player")
    handle_click(raw_dm, "dm")

    legend_items = " &nbsp;".join(
        f"<span style='font-size:13px'>{icon}</span> <span style='color:#adaaaa;font-size:11px'>{label}</span>"
        for label, icon in [
            ("Tackle", theme.icon_span("[TKL]", size=14)), ("Interception", theme.icon_span("[INT]", size=14)), ("Clearance", theme.icon_span("[CLR]", size=14)),
            ("Aerial", theme.icon_span("[AER]", size=14)), ("Block", theme.icon_span("[BLK]", size=14)), ("Challenge", theme.icon_span("[CHL]", size=14)), ("Dispossessed", theme.icon_span("[DIS]", size=14)),
        ]
        if label in player_def["type"].values
    )
    st.markdown(f"<div style='margin-top:-4px;margin-bottom:8px'>{legend_items}</div>",
                unsafe_allow_html=True)

    def def_label(row):
        icon = {"Tackle": "Ⓣ", "Interception": "Ⓘ", "Clearance": "Ⓒ",
            "Aerial": "Ⓐ", "Block": "Ⓑ", "Challenge": "Ⓗ",
            "Dispossessed": "Ⓓ"}.get(row.get("type", ""), "●")
        return f"{icon}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"  {row.get('type','')}  ({row.get('outcomeType','')})"

    dm_indices = list(player_def.index)
    dm_labels  = ["— Select an action to inspect —"] + [def_label(r) for _, r in player_def.iterrows()]
    cur_dm     = st.session_state.get("dm_selected_idx")
    dm_pos     = dm_indices.index(cur_dm) + 1 if cur_dm in dm_indices else 0
    dm_chosen  = st.selectbox("Select an action", dm_labels, index=dm_pos, key="dm_action_sel")

    if dm_chosen != "— Select an action to inspect —":
        new_dm_idx = dm_indices[dm_labels.index(dm_chosen) - 1]
        if new_dm_idx != st.session_state.get("dm_selected_idx"):
            st.session_state["dm_selected_idx"] = new_dm_idx
            st.session_state["dm_clip_path"]    = None
            st.session_state["dm_clip_key"]     = None
            st.session_state["dm_clip_error"]   = None
            st.rerun()

    dm_sel = st.session_state.get("dm_selected_idx")
    if dm_sel is not None and dm_sel in def_df.index:
        row    = def_df.loc[dm_sel].to_dict()
        team   = row.get("team", "")
        accent = HOME_COLOR if team == home_team else AWAY_COLOR
        atype  = row.get("type", "")
        badge_c = DEF_CLASS.get(atype, "badge badge-clear")
        badge_l = theme.ui_html(DEF_LABEL.get(atype, atype.upper()))

        st.divider()
        dc, vc = st.columns([1, 1], gap="large")
        with dc:
            st.markdown(_h(f"""<div class="cm-event-panel">
                <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','Unknown')}</div>
                <div class="cm-panel-sub">{team} · {fmt_time(row.get('minute',0), row.get('second',0), row.get('period',''))}</div>
                <span class="{badge_c}">{badge_l}</span>
                <div style="margin-top:12px">
                    <div class="cm-detail-label">Outcome</div>
                    <div class="cm-detail-value">{row.get('outcomeType','—')}</div>
                </div>
            </div>"""), unsafe_allow_html=True)
        with vc:
            render_watch_panel(row, "dm", def_label)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — DRIBBLES & CARRIES
# ─────────────────────────────────────────────────────────────────────────────
@st.fragment
def render_dc_tab():
    if dribble_carry_df is None or dribble_carry_df.empty:
        st.info("No dribble or carry data found in the loaded CSV.")
        return

    radio_dc_opts = []
    if home_team: radio_dc_opts.append(home_team)
    if away_team: radio_dc_opts.append(away_team)
    if not radio_dc_opts:
        radio_dc_opts = sorted(dribble_carry_df["team"].dropna().unique().tolist())[:2]

    dc_team_sel = st.radio("Team", radio_dc_opts, horizontal=True,
                           key="dcm_team_radio", label_visibility="collapsed")

    team_dc      = dribble_carry_df[dribble_carry_df["team"] == dc_team_sel].copy()
    dc_players   = sorted(team_dc["playerName"].dropna().unique().tolist()) if "playerName" in team_dc.columns else []
    dc_player_sel = st.selectbox("Player", ["— Select a player —"] + dc_players,
                                 label_visibility="collapsed", key="dcm_player_sel")

    _dc_z1, _dc_z2 = st.columns(2)
    with _dc_z1:
        dcm_pitch_zone = st.selectbox(
            "Pitch Zone",
            options=["", "Entire Left Side", "Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing", "Entire Right Side"],
            format_func=lambda x: "Any pitch zone" if x == "" else x,
            key="dcm_pitch_zone_sel",
            label_visibility="collapsed",
        )
    with _dc_z2:
        dcm_depth_zone = st.selectbox(
            "Depth Zone",
            options=["", "Defensive Third", "Middle Third", "Attacking Third"],
            format_func=lambda x: "Any depth zone" if x == "" else x,
            key="dcm_depth_zone_sel",
            label_visibility="collapsed",
        )

    _dcm_fkey = f"{dc_team_sel}|{dc_player_sel}|{dcm_pitch_zone}|{dcm_depth_zone}"
    if st.session_state.get("_dcm_last_filter") != _dcm_fkey:
        st.session_state["_dcm_last_filter"] = _dcm_fkey
        st.session_state["dcm_selected_idx"] = None
        st.session_state["dcm_clip_path"]    = None
        st.session_state["dcm_clip_key"]     = None
        st.session_state["dcm_clip_error"]   = None

    if dc_player_sel == "— Select a player —":
        st.markdown("""<div class="cm-no-data-msg" style="padding:40px 20px">
            <div style="font-size:32px;margin-bottom:12px">{}</div>
            Select a player above to view their dribbles and carries
        </div>""".format(theme.icon_span("[RUN]", color="#ccc", size=32)), unsafe_allow_html=True)
        return

    player_dc = team_dc[team_dc["playerName"] == dc_player_sel].copy()
    player_dc = _filter_by_pitch_zone(player_dc, dcm_pitch_zone)
    if dcm_depth_zone and "depth_zone" in player_dc.columns:
        player_dc = player_dc[player_dc["depth_zone"] == dcm_depth_zone]
    player_dc = player_dc.dropna(subset=["x", "y"])

    # Stats bar
    carries_dc   = player_dc[player_dc["type"] == "Carry"]
    dribbles_dc  = player_dc[player_dc["type"] == "TakeOn"]
    succ_drib    = dribbles_dc[dribbles_dc["outcomeType"] == "Successful"] if "outcomeType" in dribbles_dc.columns else pd.DataFrame()
    drib_pct     = f"{round(len(succ_drib)/len(dribbles_dc)*100)}%" if len(dribbles_dc) > 0 else "—"
    html_stats = f"""<div class="cm-stats-bar">
        <div class="cm-stats-cell"><div class="cm-stats-label">Carries</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{len(carries_dc)}</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">Dribble Attempts</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{len(dribbles_dc)}</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">Successful</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{len(succ_drib)}</span></div></div>
        <div class="cm-stats-cell"><div class="cm-stats-label">Dribble %</div>
            <div class="cm-stats-split"><span class="cm-stats-home">{drib_pct}</span></div></div>
    </div>"""
    st.markdown(_h(html_stats), unsafe_allow_html=True)

    if player_dc.empty:
        st.info("No dribbles or carries match the current filter.")
        return

    dc_for_comp = []
    for idx, row in player_dc.iterrows():
        entry = {
            "df_idx":     int(idx),
            "type":       str(row.get("type", "")),
            "playerName": str(row.get("playerName", "")),
            "team":       str(row.get("team", "")),
            "is_home":    bool(row.get("team", "") == home_team),
            "minute":     int(row.get("minute", 0)),
            "second":     int(row.get("second", 0)),
            "period":     str(row.get("period", "")),
            "x":          safe_float(row.get("x")),
            "y":          safe_float(row.get("y")),
            "outcomeType": str(row.get("outcomeType", "")),
        }
        if str(row.get("type", "")) == "Carry":
            entry["endX"] = safe_float(row.get("endX"))
            entry["endY"] = safe_float(row.get("endY"))
        dc_for_comp.append(entry)

    dcm_sel_idx = st.session_state.get("dcm_selected_idx")
    if dcm_sel_idx is not None:
        if st.button("Clear selection", key="dcm_clear_sel"):
            st.session_state["dcm_selected_idx"] = None
            st.session_state["dcm_clip_path"]    = None
            st.session_state["dcm_clip_key"]     = None
            st.session_state["dcm_clip_error"]   = None
            st.rerun()

    raw_dcm = dribble_carry_map(actions=dc_for_comp, home_team=home_team or "",
                                away_team=away_team or "", selected_idx=dcm_sel_idx,
                                key="dcm_player")
    handle_click(raw_dcm, "dcm")

    st.markdown(
        "<div style='font-size:11px;color:#767575;margin-top:-4px'>"
        "<span style='color:#27ae60'>●</span> Succ. dribble &nbsp;"
        "<span style='color:#e74c3c'>●</span> Unsucc. dribble &nbsp;"
        "<span style='color:#e0c860'>——</span> Carry &nbsp;·&nbsp;"
        "Click to inspect</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    def dc_label(row):
        atype = row.get("type", "")
        outcome = row.get("outcomeType", "")
        if atype == "Carry":
            icon = "▶"
        elif outcome == "Successful":
            icon = "✓"
        else:
            icon = "✕"
        return f"{icon}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"  {atype}  ({outcome})"

    dcm_indices = list(player_dc.index)
    dcm_labels  = ["— Select an action to inspect —"] + [dc_label(r) for _, r in player_dc.iterrows()]
    cur_dcm     = st.session_state.get("dcm_selected_idx")
    dcm_pos     = dcm_indices.index(cur_dcm) + 1 if cur_dcm in dcm_indices else 0
    dcm_chosen  = st.selectbox("Select an action", dcm_labels, index=dcm_pos, key="dcm_action_sel")

    if dcm_chosen != "— Select an action to inspect —":
        new_dcm_idx = dcm_indices[dcm_labels.index(dcm_chosen) - 1]
        if new_dcm_idx != st.session_state.get("dcm_selected_idx"):
            st.session_state["dcm_selected_idx"] = new_dcm_idx
            st.session_state["dcm_clip_path"]    = None
            st.session_state["dcm_clip_key"]     = None
            st.session_state["dcm_clip_error"]   = None
            st.rerun()

    dcm_sel = st.session_state.get("dcm_selected_idx")
    if dcm_sel is not None and dcm_sel in dribble_carry_df.index:
        row    = dribble_carry_df.loc[dcm_sel].to_dict()
        team   = row.get("team", "")
        accent = HOME_COLOR if team == home_team else AWAY_COLOR
        atype  = row.get("type", "")
        outcome = row.get("outcomeType", "")
        if atype == "Carry":
            badge_c = "badge badge-block"
            badge_l = "CARRY"
        elif outcome == "Successful":
            badge_c = "badge badge-success"
            badge_l = theme.ui_html("[OK] DRIBBLE SUCCESSFUL")
        else:
            badge_c = "badge badge-fail"
            badge_l = theme.ui_html("[ERR] DRIBBLE UNSUCCESSFUL")

        st.divider()
        dc, vc = st.columns([1, 1], gap="large")
        with dc:
            st.markdown(_h(f"""<div class="cm-event-panel">
                <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','Unknown')}</div>
                <div class="cm-panel-sub">{team} · {fmt_time(row.get('minute',0), row.get('second',0), row.get('period',''))}</div>
                <span class="{badge_c}">{badge_l}</span>
                <div style="margin-top:12px">
                    <div class="cm-detail-label">Outcome</div>
                    <div class="cm-detail-value">{outcome or '—'}</div>
                </div>
            </div>"""), unsafe_allow_html=True)
        with vc:
            render_watch_panel(row, "dcm", dc_label)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — GOALKEEPER ACTIONS
# ─────────────────────────────────────────────────────────────────────────────
@st.fragment
def render_gk_tab():
    if gk_df is None or gk_df.empty:
        st.info("No goalkeeper action data found in the loaded CSV.")
        return

    radio_gk_opts = []
    if home_team: radio_gk_opts.append(home_team)
    if away_team: radio_gk_opts.append(away_team)
    if not radio_gk_opts:
        radio_gk_opts = sorted(gk_df["team"].dropna().unique().tolist())[:2]

    gk_team_sel = st.radio("Team", radio_gk_opts, horizontal=True,
                           key="gk_team_radio", label_visibility="collapsed")

    team_gk      = gk_df[gk_df["team"] == gk_team_sel].copy()
    gk_players   = sorted(team_gk["playerName"].dropna().unique().tolist()) if "playerName" in team_gk.columns else []
    gk_player_sel = st.selectbox("Player", ["— Select a goalkeeper —"] + gk_players,
                                 label_visibility="collapsed", key="gk_player_sel")

    gk_mode = st.radio(
        "Mode", ["GK Actions", "Shots Faced"],
        horizontal=True, key="gk_mode_radio", label_visibility="collapsed",
    )

    _gk_z1, _gk_z2 = st.columns(2)
    with _gk_z1:
        gk_pitch_zone = st.selectbox(
            "Pitch Zone",
            options=["", "Entire Left Side", "Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing", "Entire Right Side"],
            format_func=lambda x: "Any pitch zone" if x == "" else x,
            key="gk_pitch_zone_sel",
            label_visibility="collapsed",
        )
    with _gk_z2:
        gk_depth_zone = st.selectbox(
            "Depth Zone",
            options=["", "Defensive Third", "Middle Third", "Attacking Third"],
            format_func=lambda x: "Any depth zone" if x == "" else x,
            key="gk_depth_zone_sel",
            label_visibility="collapsed",
        )

    _gk_fkey = f"{gk_team_sel}|{gk_player_sel}|{gk_pitch_zone}|{gk_depth_zone}|{gk_mode}"
    if st.session_state.get("_gk_last_filter") != _gk_fkey:
        st.session_state["_gk_last_filter"] = _gk_fkey
        st.session_state["gk_selected_idx"] = None
        st.session_state["gk_clip_path"]    = None
        st.session_state["gk_clip_key"]     = None
        st.session_state["gk_clip_error"]   = None

    if gk_player_sel == "— Select a goalkeeper —":
        st.markdown("""<div class="cm-no-data-msg" style="padding:40px 20px">
            <div style="font-size:32px;margin-bottom:12px">{}</div>
            Select a goalkeeper above to view their actions
        </div>""".format(theme.icon_span("[GK]", color="#ccc", size=32)), unsafe_allow_html=True)
        return

    # ── SHOTS FACED MODE ──────────────────────────────────────────────────────
    if gk_mode == "Shots Faced":
        if shots_df is None or shots_df.empty:
            st.info("No shot data available.")
            return

        # On-target shots by the opposing team
        opp_team = away_team if gk_team_sel == home_team else home_team
        ON_TARGET = {"SavedShot", "AttemptSaved", "Goal"}
        opp_shots = shots_df[
            (shots_df["team"] == opp_team) &
            (shots_df["type"].isin(ON_TARGET))
        ].copy()

        opp_shots = _filter_by_pitch_zone(opp_shots, gk_pitch_zone)
        if gk_depth_zone and "depth_zone" in opp_shots.columns:
            opp_shots  = opp_shots[opp_shots["depth_zone"] == gk_depth_zone]
        opp_shots = opp_shots.dropna(subset=["x", "y"])

        # Stats bar
        sf_saved = sum(1 for _, r in opp_shots.iterrows() if reclassify_shot(r) in {"SavedShot"})
        sf_goals = sum(1 for _, r in opp_shots.iterrows() if reclassify_shot(r) == "Goal")
        sf_cells = (
            f'<div class="cm-stats-cell"><div class="cm-stats-label">Saved</div>'
            f'<div class="cm-stats-split"><span class="cm-stats-home">{sf_saved}</span></div></div>'
            f'<div class="cm-stats-cell"><div class="cm-stats-label">Goals Conceded</div>'
            f'<div class="cm-stats-split"><span class="cm-stats-home">{sf_goals}</span></div></div>'
        )
        st.markdown(_h(f'<div class="cm-stats-bar">{sf_cells}</div>'), unsafe_allow_html=True)

        if opp_shots.empty:
            st.info("No on-target shots match the current filter.")
            return

        def sf_shot_to_dict(idx, row):
            return {
                "df_idx":       int(idx),
                "type":         reclassify_shot(row),
                "playerName":   str(row.get("playerName", "")),
                "team":         str(row.get("team", "")),
                "is_home":      bool(row.get("team", "") == home_team),
                "minute":       int(row.get("minute", 0)),
                "second":       int(row.get("second", 0)),
                "period":       str(row.get("period", "")),
                "x":            safe_float(row.get("x")),
                "y":            safe_float(row.get("y")),
                "goal_mouth_y": safe_float(row.get("goal_mouth_y")),
                "goal_mouth_z": safe_float(row.get("goal_mouth_z")),
            }

        sf_for_comp = [sf_shot_to_dict(idx, row) for idx, row in opp_shots.iterrows()]
        gk_sel_idx  = st.session_state.get("gk_selected_idx")

        if gk_sel_idx is not None:
            if st.button("Clear selection", key="gk_clear_sel"):
                st.session_state["gk_selected_idx"] = None
                st.session_state["gk_clip_path"]    = None
                st.session_state["gk_clip_key"]     = None
                st.session_state["gk_clip_error"]   = None
                st.rerun()

        # Goal frame preview above the pitch map
        if gk_sel_idx is not None and gk_sel_idx in opp_shots.index:
            sel_row = opp_shots.loc[gk_sel_idx]
            shot_map([sf_shot_to_dict(gk_sel_idx, sel_row)],
                     home_team=home_team or "", away_team=away_team or "",
                     selected_idx=gk_sel_idx, view="goalframe", key="gk_sf_gf")

        raw_sf = goalkeeper_map(actions=sf_for_comp, home_team=home_team or "",
                                away_team=away_team or "", selected_idx=gk_sel_idx,
                                shots_faced=True, key="gk_sf_map")
        handle_click(raw_sf, "gk")

        st.markdown(
            "<div style='font-size:11px;color:#767575;margin-top:-4px'>"
            "● Saved &nbsp;✕ Goal &nbsp;·&nbsp;Click to inspect</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        def sf_label(row):
            icon = "●" if reclassify_shot(row) == "SavedShot" else "✕"
            return f"{icon}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"  {row.get('playerName','Unknown')}  ({row.get('team','')})"

        sf_indices = list(opp_shots.index)
        sf_labels  = ["— Select a shot to inspect —"] + [sf_label(r) for _, r in opp_shots.iterrows()]
        cur_sf     = st.session_state.get("gk_selected_idx")
        sf_pos     = sf_indices.index(cur_sf) + 1 if cur_sf in sf_indices else 0
        sf_chosen  = st.selectbox("Select a shot", sf_labels, index=sf_pos, key="gk_sf_sel")

        if sf_chosen != "— Select a shot to inspect —":
            new_sf_idx = sf_indices[sf_labels.index(sf_chosen) - 1]
            if new_sf_idx != st.session_state.get("gk_selected_idx"):
                st.session_state["gk_selected_idx"] = new_sf_idx
                st.session_state["gk_clip_path"]    = None
                st.session_state["gk_clip_key"]     = None
                st.session_state["gk_clip_error"]   = None
                st.rerun()

        gk_sel = st.session_state.get("gk_selected_idx")
        if gk_sel is not None and gk_sel in shots_df.index:
            row    = shots_df.loc[gk_sel].to_dict()
            s_type = reclassify_shot(row)
            team   = row.get("team", "")
            accent = HOME_COLOR if team == home_team else AWAY_COLOR
            badge_l = theme.ui_html("GOAL") if s_type == "Goal" else theme.ui_html("SAVED")

            st.divider()
            gc, vc = st.columns([1, 1], gap="large")
            with gc:
                st.markdown(_h(f"""<div class="cm-event-panel">
                    <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','Unknown')}</div>
                    <div class="cm-panel-sub">{team} · {fmt_time(row.get('minute',0), row.get('second',0), row.get('period',''))}</div>
                    <span class="badge badge-clear">{badge_l}</span>
                    <div style="margin-top:12px">
                        <div class="cm-detail-label">Type</div>
                        <div class="cm-detail-value">{s_type}</div>
                    </div>
                </div>"""), unsafe_allow_html=True)
            with vc:
                render_watch_panel(row, "gk", sf_label)
        return

    # ── GK ACTIONS MODE ───────────────────────────────────────────────────────
    player_gk = team_gk[team_gk["playerName"] == gk_player_sel].copy()
    player_gk = _filter_by_pitch_zone(player_gk, gk_pitch_zone)
    if gk_depth_zone and "depth_zone" in player_gk.columns:
        player_gk = player_gk[player_gk["depth_zone"] == gk_depth_zone]
    player_gk = player_gk.dropna(subset=["x", "y"])

    # Stats bar
    action_counts = player_gk["type"].value_counts()
    cells = "".join(
        f'<div class="cm-stats-cell"><div class="cm-stats-label">{t}</div>'
        f'<div class="cm-stats-split"><span class="cm-stats-home">{action_counts.get(t, 0)}</span></div></div>'
        for t in ["Punch", "Claim", "KeeperSweeper", "KeeperPickup", "PenaltyFaced"]
        if action_counts.get(t, 0) > 0
    )
    st.markdown(_h(f'<div class="cm-stats-bar">{cells}</div>'), unsafe_allow_html=True)

    if player_gk.empty:
        st.info("No goalkeeper actions match the current filter.")
        return

    gk_for_comp = []
    for idx, row in player_gk.iterrows():
        gk_for_comp.append({
            "df_idx":     int(idx),
            "type":       str(row.get("type", "")),
            "playerName": str(row.get("playerName", "")),
            "team":       str(row.get("team", "")),
            "is_home":    bool(row.get("team", "") == home_team),
            "minute":     int(row.get("minute", 0)),
            "second":     int(row.get("second", 0)),
            "period":     str(row.get("period", "")),
            "x":          safe_float(row.get("x")),
            "y":          safe_float(row.get("y")),
            "outcomeType": str(row.get("outcomeType", "")),
        })

    gk_sel_idx = st.session_state.get("gk_selected_idx")
    if gk_sel_idx is not None:
        if st.button("Clear selection", key="gk_clear_sel"):
            st.session_state["gk_selected_idx"] = None
            st.session_state["gk_clip_path"]    = None
            st.session_state["gk_clip_key"]     = None
            st.session_state["gk_clip_error"]   = None
            st.rerun()

    raw_gk = goalkeeper_map(actions=gk_for_comp, home_team=home_team or "",
                            away_team=away_team or "", selected_idx=gk_sel_idx,
                            key="gk_player")
    handle_click(raw_gk, "gk")

    st.markdown(
        "<div style='font-size:11px;color:#767575;margin-top:-4px'>"
        "Punch (●) · Claim (●) · Sweep (●) · Pickup (●) · Penalty (●) · "
        "Click to inspect</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    def gk_label(row):
        return f"●  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"  {row.get('type','')}  ({row.get('outcomeType','')})"

    gk_indices = list(player_gk.index)
    gk_labels  = ["— Select an action to inspect —"] + [gk_label(r) for _, r in player_gk.iterrows()]
    cur_gk     = st.session_state.get("gk_selected_idx")
    gk_pos     = gk_indices.index(cur_gk) + 1 if cur_gk in gk_indices else 0
    gk_chosen  = st.selectbox("Select an action", gk_labels, index=gk_pos, key="gk_action_sel")

    if gk_chosen != "— Select an action to inspect —":
        new_gk_idx = gk_indices[gk_labels.index(gk_chosen) - 1]
        if new_gk_idx != st.session_state.get("gk_selected_idx"):
            st.session_state["gk_selected_idx"] = new_gk_idx
            st.session_state["gk_clip_path"]    = None
            st.session_state["gk_clip_key"]     = None
            st.session_state["gk_clip_error"]   = None
            st.rerun()

    gk_sel = st.session_state.get("gk_selected_idx")
    if gk_sel is not None and gk_sel in gk_df.index:
        row    = gk_df.loc[gk_sel].to_dict()
        team   = row.get("team", "")
        accent = HOME_COLOR if team == home_team else AWAY_COLOR
        atype  = row.get("type", "")
        outcome = row.get("outcomeType", "")
        badge_c = "badge badge-clear"
        badge_l = theme.ui_html(f"[GK] {atype.upper()}")

        st.divider()
        gc, vc = st.columns([1, 1], gap="large")
        with gc:
            st.markdown(_h(f"""<div class="cm-event-panel">
                <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','Unknown')}</div>
                <div class="cm-panel-sub">{team} · {fmt_time(row.get('minute',0), row.get('second',0), row.get('period',''))}</div>
                <span class="{badge_c}">{badge_l}</span>
                <div style="margin-top:12px">
                    <div class="cm-detail-label">Outcome</div>
                    <div class="cm-detail-value">{outcome or '—'}</div>
                </div>
            </div>"""), unsafe_allow_html=True)
        with vc:
            render_watch_panel(row, "gk", gk_label)

# =============================================================================
# TAB 6 — BUILD-UP SEQUENCES (D2)
# =============================================================================
@st.fragment
def render_build_up_tab():
    if df_all is None or df_all.empty:
        st.info("No match data loaded.")
        return

    has_prog = ("prog_pass" in df_all.columns) or ("prog_carry" in df_all.columns)
    if not has_prog:
        st.info("No progressive action columns (prog_pass / prog_carry) found in the data.")
        return

    radio_opts = []
    if home_team: radio_opts.append(home_team)
    if away_team: radio_opts.append(away_team)
    if not radio_opts:
        radio_opts = sorted(df_all["team"].dropna().unique().tolist())[:2]

    team_sel = st.radio("Team", radio_opts, horizontal=True, key="bu_team_radio",
                        label_visibility="collapsed")

    min_chain = st.slider("Min actions per sequence", min_value=2, max_value=6, value=3,
                          key="bu_min_chain")

    all_chains  = detect_progressive_chains(df_all, min_chain_length=min_chain)
    team_chains = [c for c in all_chains if c["team"] == team_sel]
    # Only show sequences that end with an attempt to enter the opponent's half
    entry_chains = [c for c in team_chains if c["reaches_opp_half"]]

    _bu_fkey = f"{team_sel}|{min_chain}"
    if st.session_state.get("_bu_last_filter") != _bu_fkey:
        st.session_state["_bu_last_filter"]       = _bu_fkey
        st.session_state["bu_selected_chain_idx"] = None
        st.session_state["bu_clip_path"]          = None
        st.session_state["bu_clip_key"]           = None
        st.session_state["bu_clip_error"]         = None

    if not entry_chains:
        st.info(f"No build-up sequences reaching the opponent's half ({min_chain}+ actions) found for {team_sel}.")
        return

    avg_actions  = sum(c["action_count"] for c in entry_chains) / len(entry_chains)
    direct_count = sum(1 for c in entry_chains if c["action_count"] <= 3)
    direct_pct   = direct_count / len(entry_chains) * 100

    m1, m2, m3 = st.columns(3)
    m1.metric("Half Entries", len(entry_chains),
              help="Sequences where the final progressive action crossed into the opponent's half")
    m2.metric("Avg Actions", f"{avg_actions:.1f}",
              help="Average number of consecutive progressive actions per entry sequence")
    m3.metric("Direct %", f"{direct_pct:.0f}%",
              help="% of entries achieved in 3 or fewer progressive actions — higher = more direct play")

    team_chains = entry_chains

    col_list, col_detail = st.columns([2, 3])

    with col_list:
        st.subheader("Sequences")
        with st.container(height=520):
            for ci, chain in enumerate(team_chains):
                period_label = {
                    "FirstHalf": "1H", "SecondHalf": "2H",
                    "FirstPeriodOfExtraTime": "ET1", "SecondPeriodOfExtraTime": "ET2",
                }.get(str(chain.get("start_period", "")), "")
                label = (f"{int(chain['start_minute'])}'{int(chain['start_second']):02d}\" "
                         f"→ {int(chain['end_minute'])}'{int(chain['end_second']):02d}\" "
                         f"{period_label}  ·  {chain['action_count']} actions")
                c_info, c_watch = st.columns([4, 1])
                with c_info:
                    if st.button(label, key=f"bu_chain_{ci}"):
                        st.session_state["bu_selected_chain_idx"] = ci
                        st.session_state["bu_clip_path"]          = None
                        st.session_state["bu_clip_key"]           = None
                        st.session_state["bu_clip_error"]         = None
                        st.rerun()
                with c_watch:
                    if st.button("▶", key=f"bu_watch_{ci}"):
                        _start = df_all.loc[chain["start_idx"]]
                        _clip_key = f"bu_{ci}_{chain['start_idx']}"
                        existing   = st.session_state.get("bu_clip_path")
                        existing_k = st.session_state.get("bu_clip_key")
                        if existing_k == _clip_key and existing and os.path.exists(existing):
                            pass  # already cached, detail column will render it
                        else:
                            with st.spinner("Cutting clip…"):
                                try:
                                    _before_buf, _after_buf = _analysts_room_buffers()
                                    _path = cut_clip(
                                        _start.get("minute", 0),
                                        _start.get("second", 0),
                                        _start.get("period", "FirstHalf"),
                                        before=_before_buf,
                                        after=_after_buf,
                                    )
                                    st.session_state["bu_clip_path"]          = _path
                                    st.session_state["bu_clip_key"]           = _clip_key
                                    st.session_state["bu_clip_error"]         = None
                                    st.session_state["bu_selected_chain_idx"] = ci
                                except Exception as _e:
                                    st.session_state["bu_clip_error"] = str(_e)
                                    st.session_state["bu_clip_key"]   = _clip_key
                        st.rerun()

    with col_detail:
        sel_idx  = st.session_state.get("bu_selected_chain_idx")
        _bu_clip = st.session_state.get("bu_clip_path")
        _bu_err  = st.session_state.get("bu_clip_error")

        if sel_idx is not None and sel_idx < len(team_chains):
            chain = team_chains[sel_idx]
            chain_actions = get_chain_actions(df_all, chain)
            st.subheader(f"Sequence Detail  ·  {int(chain['start_minute'])}' – {int(chain['end_minute'])}'")
            is_home_team = (team_sel == home_team)
            pitch_actions = []
            for step, (_, row) in enumerate(chain_actions.iterrows(), 1):
                pitch_actions.append({
                    "step":       step,
                    "type":       str(row.get("type", "")),
                    "playerName": str(row.get("playerName", "")),
                    "minute":     int(row.get("minute", 0)),
                    "second":     int(row.get("second", 0)),
                    "x":          float(row.get("x",    0) or 0),
                    "y":          float(row.get("y",    0) or 0),
                    "endX":       float(row.get("endX", 0) or 0),
                    "endY":       float(row.get("endY", 0) or 0),
                })
            build_up_map(pitch_actions, is_home_team, key=f"bu_map_{sel_idx}")

        if _bu_clip and os.path.exists(_bu_clip):
            st.divider()
            with open(_bu_clip, "rb") as _vf:
                st.video(_vf.read())
        elif _bu_err:
            st.error(f"Could not cut clip: {_bu_err}")

        if sel_idx is None and not _bu_clip and not _bu_err:
            st.caption("Select a sequence on the left to inspect it, or press ▶ to cut a clip.")


# =============================================================================
# PLAYER COMPARISON — RADAR INDEX HELPERS
# =============================================================================

def _is_gk(ev):
    if ev.empty:
        return False
    if ev["type"].isin(GK_ACTIONS).any():
        return True
    if "is_gk_save" in ev.columns:
        try:
            return bool(pd.to_numeric(ev["is_gk_save"], errors="coerce").fillna(0).any())
        except Exception:
            return ev["is_gk_save"].astype(bool).any()
    return False


def _bool_col(ev, col):
    """Return boolean series for a flag column, defaulting to False if absent."""
    if col not in ev.columns:
        return pd.Series(False, index=ev.index)
    return pd.to_numeric(ev[col], errors="coerce").fillna(0).astype(bool)


def _score_moments(ev, role):
    """Score each event row for the Top 5 Moments widget.

    Returns a copy of ev with a 'moment_score' column. Rows with score 0
    and no positive xT are effectively excluded from the top 5.
    """
    if ev.empty:
        return ev.assign(moment_score=0.0)

    df = ev.copy()
    df["moment_score"] = 0.0

    outcome_ok = pd.Series(False, index=df.index)
    if "outcomeType" in df.columns:
        outcome_ok = df["outcomeType"] == "Successful"

    xT_vals = pd.to_numeric(df.get("xT", 0), errors="coerce").fillna(0).clip(lower=0)

    tiers = _MOMENT_TIERS.get(role, _MOMENT_TIERS["midfielder"])

    for tier in tiers:
        if len(tier) == 2:
            # (type_set, base_score) — no outcome filter
            type_set, base = tier
            if type_set is not None:
                mask = df["type"].isin(type_set)
                df.loc[mask, "moment_score"] = df.loc[mask, "moment_score"].clip(lower=base)

        elif len(tier) == 3:
            type_set_or_none, qualifier, base = tier

            if qualifier == "successful":
                # (type_set, "successful", base_score)
                mask = df["type"].isin(type_set_or_none) & outcome_ok
                df.loc[mask, "moment_score"] = df.loc[mask, "moment_score"].clip(lower=base)

            elif qualifier == "is_key_pass":
                mask = _bool_col(df, "is_key_pass")
                df.loc[mask, "moment_score"] = df.loc[mask, "moment_score"].clip(lower=base)

            elif qualifier == "is_long_ball_successful":
                mask = _bool_col(df, "is_long_ball") & outcome_ok & (df["type"] == "Pass")
                df.loc[mask, "moment_score"] = df.loc[mask, "moment_score"].clip(lower=base)

    # xT booster: scale 0–1 xT range to 0–20 pts, added on top
    df["moment_score"] = df["moment_score"] + (xT_vals * 20).clip(upper=20)

    return df


def _score_gk_moments(ev):
    """Score goalkeeper events for the comparison Top 5 Moments widget."""
    if ev.empty:
        return ev.assign(moment_score=0.0)

    df = ev.copy()
    df["moment_score"] = 0.0

    outcome_ok = pd.Series(False, index=df.index)
    if "outcomeType" in df.columns:
        outcome_ok = df["outcomeType"] == "Successful"

    prog_pass_vals = pd.to_numeric(df.get("prog_pass", 0), errors="coerce").fillna(0).clip(lower=0)

    # Priority order:
    # Save > KeeperSweeper > accurate long balls (with progression) > Claim > Punch > KeeperPickup
    df.loc[df["type"] == "Save", "moment_score"] = 100.0
    df.loc[(df["type"] == "KeeperSweeper") & outcome_ok, "moment_score"] = df.loc[
        (df["type"] == "KeeperSweeper") & outcome_ok, "moment_score"
    ].clip(lower=90.0)
    df.loc[(df["type"] == "Claim") & outcome_ok, "moment_score"] = df.loc[
        (df["type"] == "Claim") & outcome_ok, "moment_score"
    ].clip(lower=70.0)
    df.loc[(df["type"] == "Punch") & outcome_ok, "moment_score"] = df.loc[
        (df["type"] == "Punch") & outcome_ok, "moment_score"
    ].clip(lower=60.0)
    df.loc[(df["type"] == "KeeperPickup") & outcome_ok, "moment_score"] = df.loc[
        (df["type"] == "KeeperPickup") & outcome_ok, "moment_score"
    ].clip(lower=50.0)
    df.loc[(df["type"] == "Clearance") & outcome_ok, "moment_score"] = df.loc[
        (df["type"] == "Clearance") & outcome_ok, "moment_score"
    ].clip(lower=45.0)

    # Distribution moments: accurate long balls outrank claims/punches and are boosted
    # by progressive distance, but never above the save ceiling.
    long_pass_mask = (df["type"] == "Pass") & outcome_ok & _bool_col(df, "is_long_ball")
    long_pass_scores = 70.0 + prog_pass_vals.loc[long_pass_mask].clip(upper=18.0)
    df.loc[long_pass_mask, "moment_score"] = (
        df.loc[long_pass_mask, "moment_score"]
        .clip(lower=0.0)
        .combine(long_pass_scores.clip(upper=88.0), max)
    )

    df["moment_score"] = df["moment_score"].clip(upper=100.0)

    return df


def _raw_outfield(ev):
    def_ev = ev[ev["type"].isin(DEF_ACTIONS - {"Dispossessed"})]
    if "outcomeType" in def_ev.columns:
        defensive = int(len(def_ev[def_ev["outcomeType"] == "Successful"]))
    else:
        defensive = int(len(def_ev))

    creative = 0
    if "is_key_pass" in ev.columns:
        creative = int(
            pd.to_numeric(ev["is_key_pass"], errors="coerce").fillna(0).astype(bool).sum()
        )

    progressive = 0
    if "prog_pass" in ev.columns:
        progressive += int(
            pd.to_numeric(ev["prog_pass"], errors="coerce").fillna(0).gt(0).sum()
        )
    if "prog_carry" in ev.columns:
        progressive += int(
            pd.to_numeric(ev["prog_carry"], errors="coerce").fillna(0).gt(0).sum()
        )

    shooting = int(ev[ev["type"].isin(SHOT_TYPES)].shape[0])

    danger = 0.0
    if "xT" in ev.columns:
        danger = float(
            pd.to_numeric(
                ev[ev["type"].isin({"Pass", "Carry"})]["xT"], errors="coerce"
            ).fillna(0).sum()
        )

    dribbling = 0
    if "outcomeType" in ev.columns:
        dribbling = int(
            ev[(ev["type"] == "TakeOn") & (ev["outcomeType"] == "Successful")].shape[0]
        )

    aerial = 0
    if "outcomeType" in ev.columns:
        aerial = int(
            ev[(ev["type"] == "Aerial") & (ev["outcomeType"] == "Successful")].shape[0]
        )

    passes = ev[ev["type"] == "Pass"]
    if len(passes) > 0 and "outcomeType" in passes.columns:
        ball_retention = float(
            len(passes[passes["outcomeType"] == "Successful"]) / len(passes) * 100
        )
    else:
        ball_retention = 0.0

    involvement = int(len(ev))

    return {
        "Defensive":      defensive,
        "Creative":       creative,
        "Progressive":    progressive,
        "Shooting":       shooting,
        "Danger":         danger,
        "Dribbling":      dribbling,
        "Aerial":         aerial,
        "Pass Completion %": ball_retention,
        "Involvement":    involvement,
    }


def _raw_gk(ev):
    # Saves: "Save" event type only — is_gk_save is a flag on the same rows, not additional events
    saves = int(ev[ev["type"] == "Save"].shape[0])

    # Claiming: successful catches from crosses
    _claims = ev[ev["type"] == "Claim"]
    if "outcomeType" in _claims.columns:
        claiming = int(len(_claims[_claims["outcomeType"] == "Successful"]))
    else:
        claiming = int(len(_claims))

    # Punching: successful punch clearances
    _punches = ev[ev["type"] == "Punch"]
    if "outcomeType" in _punches.columns:
        punching = int(len(_punches[_punches["outcomeType"] == "Successful"]))
    else:
        punching = int(len(_punches))

    # Sweeping: successful off-line interventions
    _sweeps = ev[ev["type"] == "KeeperSweeper"]
    if "outcomeType" in _sweeps.columns:
        sweeping = int(len(_sweeps[_sweeps["outcomeType"] == "Successful"]))
    else:
        sweeping = int(len(_sweeps))

    # Distribution: successful passes
    passes = ev[ev["type"] == "Pass"]
    if "outcomeType" in passes.columns:
        distribution = int(len(passes[passes["outcomeType"] == "Successful"]))
    else:
        distribution = int(len(passes))

    # Long distribution: successful long passes
    if "is_long_ball" in passes.columns and "outcomeType" in passes.columns:
        long_passes = passes[
            pd.to_numeric(passes["is_long_ball"], errors="coerce").fillna(0).astype(bool)
        ]
        long_distribution = int(len(long_passes[long_passes["outcomeType"] == "Successful"]))
    else:
        long_distribution = 0

    # Ball recovery: successful keeper pickups
    pickups = ev[ev["type"] == "KeeperPickup"]
    if "outcomeType" in pickups.columns:
        ball_recovery = int(len(pickups[pickups["outcomeType"] == "Successful"]))
    else:
        ball_recovery = int(len(pickups))

    return {
        "Saves":             saves,
        "Claiming":          claiming,
        "Punching":          punching,
        "Sweeping":          sweeping,
        "Distribution":      distribution,
        "Long Distribution": long_distribution,
        "Ball Recovery":     ball_recovery,
    }


def _build_percentile_pools():
    outfield_pool = {}
    gk_pool = {}
    if df_all is None or df_all.empty:
        return outfield_pool, gk_pool
    for pname, pev in df_all.groupby("playerName"):
        if _is_gk(pev):
            gk_pool[pname] = _raw_gk(pev)
        else:
            outfield_pool[pname] = _raw_outfield(pev)
    return outfield_pool, gk_pool


def _gk_head_to_head(p1_raw, p2_raw):
    """Normalize GK stats per-axis so the higher value = 100, the other proportional.
    Returns (p1_norm, p2_norm) dicts scaled 0-100."""
    p1_norm, p2_norm = {}, {}
    for key in p1_raw:
        v1, v2 = p1_raw[key], p2_raw[key]
        max_v = max(v1, v2)
        if max_v == 0:
            p1_norm[key] = 0
            p2_norm[key] = 0
        else:
            p1_norm[key] = round(v1 / max_v * 100)
            p2_norm[key] = round(v2 / max_v * 100)
    return p1_norm, p2_norm


def _percentile_rank(player_raw, pool):
    total = len(pool)
    if total == 0:
        return {k: 0 for k in player_raw}
    result = {}
    for key, val in player_raw.items():
        below = sum(1 for other_raw in pool.values() if other_raw.get(key, 0) < val)
        result[key] = min(100, int(below / total * 100))
    return result


def _build_radar_figure(axes, p1_pct, p2_pct, p1_raw, p2_raw, player1, player2,
                         color1="#E8FF4D", color2="#ff7351"):
    closed_axes = axes + [axes[0]]
    p1_vals = [p1_pct.get(a, 0) for a in axes] + [p1_pct.get(axes[0], 0)]
    p2_vals = [p2_pct.get(a, 0) for a in axes] + [p2_pct.get(axes[0], 0)]

    def _hover_text(axes_list, pct_dict, raw_dict):
        lines = []
        for a in axes_list[:-1]:
            raw_val = raw_dict.get(a, 0)
            fmt = f"{raw_val:.2f}" if isinstance(raw_val, float) else str(raw_val)
            lines.append(f"{a}: {pct_dict.get(a, 0)}th pct  (raw {fmt})")
        return lines + [lines[0]]

    def _hex_to_rgba(hex_color, alpha=0.3):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    fill1 = _hex_to_rgba(color1) if color1.startswith("#") else "rgba(232,255,77,0.3)"
    fill2 = _hex_to_rgba(color2) if color2.startswith("#") else "rgba(255,115,81,0.3)"

    trace1 = go.Scatterpolar(
        r=p1_vals, theta=closed_axes, fill="toself",
        fillcolor=fill1, line=dict(color=color1, width=2),
        name=player1, hovertemplate="%{text}<extra></extra>",
        text=_hover_text(closed_axes, p1_pct, p1_raw),
        hoveron="points",
    )
    trace2 = go.Scatterpolar(
        r=p2_vals, theta=closed_axes, fill="toself",
        fillcolor=fill2, line=dict(color=color2, width=2),
        name=player2, hovertemplate="%{text}<extra></extra>",
        text=_hover_text(closed_axes, p2_pct, p2_raw),
        hoveron="points",
    )

    fig = go.Figure(data=[trace1, trace2])
    fig.update_layout(
        height=520,
        margin=dict(t=60, b=40, l=60, r=60),
        paper_bgcolor="#0e0e0e",
        plot_bgcolor="#0e0e0e",
        font=dict(color="#ffffff", family="Inter, sans-serif"),
        polar=dict(
            bgcolor="#131313",
            angularaxis=dict(
                tickfont=dict(size=12, color="#adaaaa"),
                linecolor="#2c2c2c",
                gridcolor="#2c2c2c",
            ),
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickvals=[0, 25, 50, 75, 100],
                tickfont=dict(size=9, color="#767575"),
                gridcolor="#2c2c2c",
                linecolor="#2c2c2c",
            ),
        ),
        legend=dict(
            font=dict(color="#ffffff", size=12),
            bgcolor="rgba(0,0,0,0)",
            bordercolor="#2c2c2c",
        ),
        showlegend=True,
    )
    return fig


# =============================================================================
# TAB 7 — PLAYER COMPARISON (E1)
# =============================================================================
@st.fragment
def render_comparison_tab():
    if df_all is None or df_all.empty:
        st.info("No match data loaded.")
        return

    if not _PLOTLY_AVAILABLE:
        st.warning("Install plotly (`pip install plotly`) to use the comparison view.")
        return

    st.subheader("Player Comparison")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Player 1**")
        _team1_opts = [t for t in [home_team, away_team] if t]
        if not _team1_opts:
            _team1_opts = sorted(df_all["team"].dropna().unique().tolist())[:2]
        team1 = st.radio("Team 1", _team1_opts, horizontal=True, key="comp_team1",
                         label_visibility="collapsed")
        players1 = sorted(df_all[df_all["team"] == team1]["playerName"].dropna().unique().tolist())
        player1  = st.selectbox("Player 1", players1, key="comp_player1",
                                label_visibility="collapsed") if players1 else None

    with col2:
        st.markdown("**Player 2**")
        _team2_opts = [t for t in [home_team, away_team] if t]
        if not _team2_opts:
            _team2_opts = sorted(df_all["team"].dropna().unique().tolist())[:2]
        team2 = st.radio("Team 2", _team2_opts, horizontal=True, key="comp_team2",
                         label_visibility="collapsed")
        players2 = sorted(df_all[df_all["team"] == team2]["playerName"].dropna().unique().tolist())
        player2  = st.selectbox("Player 2", players2, key="comp_player2",
                                label_visibility="collapsed") if players2 else None

    if not player1 or not player2:
        st.info("Select two players to compare.")
        return

    p1_ev = df_all[df_all["playerName"] == player1].copy()
    p2_ev = df_all[df_all["playerName"] == player2].copy()

    # ── Performance Radar ────────────────────────────────────────────────────
    st.subheader("Performance Radar")

    _p1_is_gk = _is_gk(p1_ev)
    _p2_is_gk = _is_gk(p2_ev)

    if _p1_is_gk != _p2_is_gk:
        st.warning(
            f"Role mismatch: **{player1}** is classified as "
            f"{'a goalkeeper' if _p1_is_gk else 'an outfield player'} and "
            f"**{player2}** is classified as "
            f"{'a goalkeeper' if _p2_is_gk else 'an outfield player'}. "
            "Radar uses outfield indexes — comparison may not be meaningful."
        )

    _outfield_pool, _gk_pool = _build_percentile_pools()

    _use_gk_axes = _p1_is_gk and _p2_is_gk
    if _use_gk_axes:
        _axes   = ["Saves", "Claiming", "Punching", "Sweeping",
                   "Distribution", "Long Distribution", "Ball Recovery"]
        _p1_raw = _raw_gk(p1_ev)
        _p2_raw = _raw_gk(p2_ev)
        _p1_pct, _p2_pct = _gk_head_to_head(_p1_raw, _p2_raw)
    else:
        _axes   = ["Defensive", "Creative", "Progressive", "Shooting", "Danger",
                   "Dribbling", "Aerial", "Pass Completion %", "Involvement"]
        _p1_raw = _raw_outfield(p1_ev)
        _p2_raw = _raw_outfield(p2_ev)
        _pool   = _outfield_pool
        _p1_pct = _percentile_rank(_p1_raw, _pool)
        _p2_pct = _percentile_rank(_p2_raw, _pool)

    st.plotly_chart(
        _build_radar_figure(
            axes=_axes,
            p1_pct=_p1_pct, p2_pct=_p2_pct,
            p1_raw=_p1_raw, p2_raw=_p2_raw,
            player1=player1, player2=player2,
            color1="#E8FF4D", color2=AWAY_COLOR,
        ),
        use_container_width=True,
    )

    # ── Pitch Zone Activity ──────────────────────────────────────────────────
    st.subheader("Pitch Zone Activity")
    _zones = ["Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing"]
    z1, z2 = st.columns(2)

    def _zone_bar(ev, player_name, color):
        zs = _effective_pitch_zone_series(ev).value_counts()
        counts = [zs.get(z, 0) for z in _zones]
        fig = go.Figure(go.Bar(y=_zones, x=counts, orientation="h",
                               marker=dict(color=color)))
        fig.update_layout(title=player_name, xaxis_title="Count",
                          height=320, margin=dict(t=40, b=0, l=0, r=0))
        return fig

    with z1:
        st.plotly_chart(_zone_bar(p1_ev, player1, HOME_COLOR), use_container_width=True)
    with z2:
        st.plotly_chart(_zone_bar(p2_ev, player2, AWAY_COLOR), use_container_width=True)

    # ── Top 5 Moments ─────────────────────────────────────────────────────────
    st.subheader("Top 5 Moments")
    _ROLE_OPTS = ["Attacker", "Midfielder", "Defender"]
    _role_col1, _role_col2 = st.columns(2)

    with _role_col1:
        if _p1_is_gk:
            st.caption(f"{player1} — Goalkeeper")
            _role1 = None
        else:
            _role1 = st.selectbox(
                f"Role — {player1}", _ROLE_OPTS, key="comp_role1",
                label_visibility="visible"
            ).lower()

    with _role_col2:
        if _p2_is_gk:
            st.caption(f"{player2} — Goalkeeper")
            _role2 = None
        else:
            _role2 = st.selectbox(
                f"Role — {player2}", _ROLE_OPTS, key="comp_role2",
                label_visibility="visible"
            ).lower()

    def _top5_moments(ev, role, is_gk=False):
        """Return (full_top5_df, display_df) for the given role."""
        scored = _score_gk_moments(ev) if is_gk else _score_moments(ev, role)
        scored = scored[scored["moment_score"] > 0]
        top5 = scored.nlargest(5, "moment_score")
        disp = top5[["minute", "second", "type", "moment_score"]].copy()
        disp = disp.rename(columns={"moment_score": "Score"})
        disp["Score"] = disp["Score"].round(1)
        return top5, disp

    def _generate_reel(moments_df):
        """Cut top-5 moment clips and concatenate them. Returns output path."""
        if not video_path:
            raise ValueError("No video file loaded. Go to Home and set a video path.")
        ffmpeg_bin = get_ffmpeg()
        _before_buf, _after_buf = _analysts_room_buffers()
        _period_col = "period" if "period" in moments_df.columns else "resolved_period"
        tmp_clips = []
        for _, row in moments_df.iterrows():
            p = cut_clip(int(row["minute"]), int(row["second"]),
                         str(row[_period_col]) if _period_col in row.index else "FirstHalf",
                         before=_before_buf, after=_after_buf)
            tmp_clips.append(p)
        if len(tmp_clips) == 1:
            return tmp_clips[0]
        list_file = tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", encoding="utf-8"
        )
        for p in tmp_clips:
            list_file.write(f"file '{p.replace(os.sep, '/')}'\n")
        list_file.close()
        out_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        out_path = out_tmp.name
        out_tmp.close()
        r = subprocess.run([
            ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
            "-i", list_file.name, "-c", "copy", out_path
        ], capture_output=True, text=True)
        for p in tmp_clips:
            try:
                os.remove(p)
            except Exception:
                pass
        try:
            os.remove(list_file.name)
        except Exception:
            pass
        if r.returncode != 0:
            raise ValueError(f"FFmpeg concat error: {r.stderr[-400:]}")
        return out_path

    def _render_moment_col(ev, role, player_name, is_gk, prefix):
        top5_df, disp_df = _top5_moments(ev, role, is_gk=is_gk)
        if disp_df.empty:
            st.caption("No qualifying moments found for this player.")
            return
        st.dataframe(disp_df, use_container_width=True, hide_index=True)
        reel_key = (
            f"{player_name}|{'goalkeeper' if is_gk else role}|"
            + ",".join(
                f"{int(r['minute'])}:{int(r['second'])}"
                for _, r in top5_df.iterrows()
            )
        )
        existing_path  = st.session_state.get(f"{prefix}_reel_path")
        existing_key   = st.session_state.get(f"{prefix}_reel_key")
        existing_error = st.session_state.get(f"{prefix}_reel_error")

        if existing_key == reel_key and existing_path and os.path.exists(existing_path):
            with open(existing_path, "rb") as _vf:
                st.video(_vf.read())
            with open(existing_path, "rb") as _dl:
                st.download_button(
                    "Download reel", data=_dl.read(),
                    file_name=f"{player_name}_top5_moments.mp4",
                    mime="video/mp4", key=f"{prefix}_dl"
                )
        elif existing_error and existing_key == reel_key:
            st.error(f"Could not generate reel: {existing_error}")
            if st.button("Retry", key=f"{prefix}_retry"):
                st.session_state[f"{prefix}_reel_error"] = None
                st.session_state[f"{prefix}_reel_key"] = None
                st.rerun()
        else:
            if not video_path:
                st.caption("Load a video file on the Home page to generate a highlight reel.")
            else:
                if st.button("▶ Show Top Moments", key=f"{prefix}_gen"):
                    with st.spinner("Cutting clips…"):
                        try:
                            path = _generate_reel(top5_df)
                            st.session_state[f"{prefix}_reel_path"]  = path
                            st.session_state[f"{prefix}_reel_key"]   = reel_key
                            st.session_state[f"{prefix}_reel_error"] = None
                        except Exception as _exc:
                            st.session_state[f"{prefix}_reel_error"] = str(_exc)
                            st.session_state[f"{prefix}_reel_key"]   = reel_key
                    st.rerun()

    _mc1, _mc2 = st.columns(2)
    with _mc1:
        _render_moment_col(p1_ev, _role1, player1, _p1_is_gk, "comp_p1")
    with _mc2:
        _render_moment_col(p2_ev, _role2, player2, _p2_is_gk, "comp_p2")


# =============================================================================
# RENDER TABS
# =============================================================================
with tab_shot:
    render_shot_tab()

with tab_pass:
    render_pass_tab()

with tab_def:
    render_def_tab()

with tab_dc:
    render_dc_tab()

with tab_gk:
    render_gk_tab()

with tab_bu:
    render_build_up_tab()

with tab_comp:
    render_comparison_tab()

theme.render_support_footer("Analyst's Room")
