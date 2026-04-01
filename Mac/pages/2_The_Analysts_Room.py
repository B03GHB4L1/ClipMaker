import sys
import os
import re
import subprocess
import tempfile
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme
from smp_component import shot_map, pass_map, defensive_map
from clipmaker_core import to_seconds

def _h(s):
    import re as _re
    return _re.sub(r'\s{2,}', ' ', s.replace('\n', ' ')).strip()

st.set_page_config(
    page_title="The Analyst's Room",
    page_icon="../ClipMaker_logo.png",
    layout="wide"
)

# =============================================================================
# STYLING
# =============================================================================
theme.inject(
    logo_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ClipMaker_logo.png")
)
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

OUTCOME_ICON  = {"Goal": "⚽", "SavedShot": "🧤", "ShotOnPost": "🏗",
                 "BlockedShot": "🛡", "MissedShot": "❌"}
OUTCOME_LABEL = {"Goal": "⚽ GOAL", "SavedShot": "🧤 SAVED", "ShotOnPost": "🏗 POST",
                 "BlockedShot": "🛡 BLOCKED", "MissedShot": "❌ MISSED"}
OUTCOME_CLASS = {"Goal": "badge badge-goal", "SavedShot": "badge badge-saved",
                 "ShotOnPost": "badge badge-post", "BlockedShot": "badge badge-blocked",
                 "MissedShot": "badge badge-missed"}

DEF_LABEL = {
    "Tackle": "🔵 TACKLE", "Interception": "🟢 INTERCEPTION",
    "Clearance": "⚪ CLEARANCE", "Aerial": "🟣 AERIAL",
    "Block": "🟠 BLOCK", "Challenge": "🩵 CHALLENGE",
    "Dispossessed": "🔴 DISPOSSESSED",
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
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# =============================================================================
# DATA LOADING
# =============================================================================
df_all    = None
shots_df  = None
pso_shots_df = None
passes_df = None
def_df    = None

if data_loaded:
    try:
        df_all    = pd.read_csv(csv_path)
        pso_shots_df = df_all[df_all["period"] == "PenaltyShootout"].copy()
        pso_shots_df = pso_shots_df[pso_shots_df["type"].isin(SHOT_TYPES)].copy().reset_index(drop=True)
        if "period" in df_all.columns:
            df_all = df_all[df_all["period"] != "PenaltyShootout"].copy()
        shots_df  = df_all[df_all["type"].isin(SHOT_TYPES)].copy().reset_index(drop=True)
        passes_df = df_all[df_all["type"] == "Pass"].copy().reset_index(drop=True)
        def_df    = df_all[df_all["type"].isin(DEF_ACTIONS)].copy().reset_index(drop=True)
    except Exception as e:
        st.error(f"Could not load match data: {e}")

# =============================================================================
# HELPERS
# =============================================================================
def safe_float(v):
    try: return float(v)
    except: return None

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
    label = {1:"1H",2:"2H",3:"ET1",4:"ET2",5:"PSO"}.get(p,"?")
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

def cut_clip(minute, second, period_str, before=5, after=8):
    if not video_path:
        raise ValueError("No video file loaded. Go to Home and set a video path.")
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
    gh = len(hs[hs["type"] == "Goal"]);  ga = len(as_[as_["type"] == "Goal"])
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

# =============================================================================
# WATCH PANEL
# =============================================================================
def render_watch_panel(row, prefix, label_fn):
    minute_val = row.get("minute", 0)
    second_val = row.get("second", 0)
    period_val = row.get("period", "FirstHalf")
    player_val = row.get("playerName", "")
    event_key  = f"{minute_val}_{second_val}_{period_val}_{player_val}"
    clip_label = f"🎬  {player_val} · {fmt_time(minute_val, second_val, period_val)}"

    existing_clip = st.session_state.get(f"{prefix}_clip_path")
    existing_key  = st.session_state.get(f"{prefix}_clip_key")
    clip_error    = st.session_state.get(f"{prefix}_clip_error")

    st.markdown(f"**{clip_label}**")

    if existing_key == event_key and existing_clip and os.path.exists(existing_clip):
        with open(existing_clip, "rb") as _vf:
            st.video(_vf.read())
        with open(existing_clip, "rb") as _dl:
            safe_name = re.sub(r"[^\w\-.]", "_", f"{player_val}_{minute_val}.mp4")
            st.download_button("⬇️ Download clip", data=_dl.read(),
                               file_name=safe_name, mime="video/mp4",
                               use_container_width=True)
    elif clip_error and existing_key == event_key:
        st.error(f"Could not cut clip: {clip_error}")
        if st.button("↻ Retry", use_container_width=True, key=f"{prefix}_retry"):
            st.session_state[f"{prefix}_clip_error"] = None
            st.session_state[f"{prefix}_clip_key"]   = None
            st.rerun()
    else:
        if st.button("▶  Watch", type="primary", use_container_width=True, key=f"{prefix}_watch"):
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
st.markdown(theme.logo_header("The Analyst's Room", "Shot Map · Pass Map · Defensive Actions", _b64 or None), unsafe_allow_html=True)

st.divider()

if not data_loaded:
    st.markdown("""<div class="cm-no-data-msg">
        <div style="font-size:40px;margin-bottom:16px">🔍</div>
        <b style="color:#ccc;font-size:17px">No match data loaded</b><br><br>
        Go to <b>Home</b> and scrape a match first.
    </div>""", unsafe_allow_html=True)
    st.stop()

# =============================================================================
# TABS
# =============================================================================
tab_shot, tab_pass, tab_def = st.tabs(["🎯  Shot Map", "🗺️  Pass Map", "🛡️  Defensive Actions"])

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

        st.markdown("<div style='font-size:11px;color:#767575;margin-top:-4px'>"
                    "● Goal &nbsp;◯ Saved / Post &nbsp;✕ Missed &nbsp;·&nbsp;"
                    "Click a penalty to inspect it</div>", unsafe_allow_html=True)

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        def shot_label(row):
            icon   = OUTCOME_ICON.get(reclassify_shot(row), "❌")
            period = row.get("period", "")
            et     = " ET" if "ExtraTime" in str(period) else ""
            return f"{icon}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"{et}  {row.get('playerName','?')}  ({row.get('team','')})"

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
            is_head    = safe_bool(row.get("is_header", ""))
            is_bc      = safe_bool(row.get("is_big_chance_shot", ""))
            extras     = " · ".join(x for x in ["Header" if is_head else "", "Big Chance" if is_bc else ""] if x) or "—"
            badge_cls  = OUTCOME_CLASS.get(s_type, "badge badge-missed")
            badge_lbl  = OUTCOME_LABEL.get(s_type, "❌ MISSED")
            minute_v   = row.get("minute", 0); second_v = row.get("second", 0); period_v = row.get("period", "")

            st.divider()
            dc, vc = st.columns([1, 1], gap="large")
            with dc:
                st.markdown(_h(f"""<div class="cm-shot-panel">
                    <div class="cm-panel-title" style="color:{accent}">{row.get('playerName','?')}</div>
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

    _smp_fkey = f"{team_sel}|{player_filter_shot}"
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

    st.markdown("<div style='font-size:11px;color:#767575;margin-top:-4px'>"
                "● Goal &nbsp;◯ Saved / Post &nbsp;✕ Missed &nbsp;·&nbsp;"
                "Click a shot to inspect it</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    def shot_label(row):
        icon   = OUTCOME_ICON.get(reclassify_shot(row), "❌")
        period = row.get("period", "")
        et     = " ET" if "ExtraTime" in str(period) else ""
        return f"{icon}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"{et}  {row.get('playerName','?')}  ({row.get('team','')})"

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
        is_head    = safe_bool(row.get("is_header", ""))
        is_bc      = safe_bool(row.get("is_big_chance_shot", ""))
        extras     = " · ".join(x for x in ["Header" if is_head else "", "Big Chance" if is_bc else ""] if x) or "—"
        badge_cls  = OUTCOME_CLASS.get(s_type, "badge badge-missed")
        badge_lbl  = OUTCOME_LABEL.get(s_type, "❌ MISSED")
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
                "is_cross": safe_bool(row.get("is_cross", False)),
                "is_long_ball": safe_bool(row.get("is_long_ball", False)),
                "is_through_ball": safe_bool(row.get("is_through_ball", False)),
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
            "Key passes": "is_key_pass", "Crosses": "is_cross",
            "Long balls": "is_long_ball", "Through balls": "is_through_ball",
        }
        available_pass_types = {k: v for k, v in bool_cols_present.items() if v in passes_df.columns}
        pass_type_sel = st.radio("Pass type", ["All passes"] + list(available_pass_types.keys()),
                                 horizontal=True, key="pm_type_radio", label_visibility="collapsed")

        _pm_fkey = f"{view_sel}|{player_sel}|{pass_type_sel}"
        if st.session_state.get("_pm_last_filter") != _pm_fkey:
            st.session_state["_pm_last_filter"] = _pm_fkey
            st.session_state["pm_selected_idx"] = None
            st.session_state["pm_clip_path"]    = None
            st.session_state["pm_clip_key"]     = None
            st.session_state["pm_clip_error"]   = None

        if player_sel == "— Select a player —":
            st.markdown("""<div class="cm-no-data-msg" style="padding:40px 20px">
                <div style="font-size:32px;margin-bottom:12px">🗺️</div>
                Select a player above to view their pass map
            </div>""", unsafe_allow_html=True)
        else:
            player_passes = team_passes[team_passes["playerName"] == player_sel].copy()
            if pass_type_sel != "All passes" and pass_type_sel in available_pass_types:
                col = available_pass_types[pass_type_sel]
                player_passes = player_passes[player_passes[col] == True]
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
                    "is_key_pass": safe_bool(row.get("is_key_pass", False)),
                    "is_cross": safe_bool(row.get("is_cross", False)),
                    "is_long_ball": safe_bool(row.get("is_long_ball", False)),
                    "is_through_ball": safe_bool(row.get("is_through_ball", False)),
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
                outcome = "✅" if str(row.get("outcomeType", "")).lower() == "successful" else "❌"
                kp = " 🔑" if safe_bool(row.get("is_key_pass", False)) else ""
                return f"{outcome}{kp}  {row.get('minute',0)}'{int(row.get('second',0)):02d}\"  {row.get('playerName','?')}"

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
                badge_l  = "✅ SUCCESSFUL" if outcome == "Successful" else "❌ UNSUCCESSFUL"
                tags     = " · ".join(x for x in [
                    "Key Pass"    if safe_bool(row.get("is_key_pass"))    else "",
                    "Cross"       if safe_bool(row.get("is_cross"))       else "",
                    "Long Ball"   if safe_bool(row.get("is_long_ball"))   else "",
                    "Through Ball" if safe_bool(row.get("is_through_ball")) else "",
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

    _dm_fkey = f"{def_team_sel}|{def_player_sel}"
    if st.session_state.get("_dm_last_filter") != _dm_fkey:
        st.session_state["_dm_last_filter"] = _dm_fkey
        st.session_state["dm_selected_idx"] = None
        st.session_state["dm_clip_path"]    = None
        st.session_state["dm_clip_key"]     = None
        st.session_state["dm_clip_error"]   = None

    if def_player_sel == "— Select a player —":
        render_def_stats(team_def)
        st.markdown("""<div class="cm-no-data-msg" style="padding:40px 20px">
            <div style="font-size:32px;margin-bottom:12px">🛡️</div>
            Select a player above to view their defensive actions
        </div>""", unsafe_allow_html=True)
        return

    player_def = team_def[team_def["playerName"] == def_player_sel].copy()
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
            ("Tackle", "🔵"), ("Interception", "🟢"), ("Clearance", "⚪"),
            ("Aerial", "🟣"), ("Block", "🟠"), ("Challenge", "🩵"), ("Dispossessed", "🔴"),
        ]
        if label in player_def["type"].values
    )
    st.markdown(f"<div style='margin-top:-4px;margin-bottom:8px'>{legend_items}</div>",
                unsafe_allow_html=True)

    def def_label(row):
        icon = {"Tackle": "🔵", "Interception": "🟢", "Clearance": "⚪",
                "Aerial": "🟣", "Block": "🟠", "Challenge": "🩵",
                "Dispossessed": "🔴"}.get(row.get("type", ""), "●")
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
        badge_l = DEF_LABEL.get(atype, atype.upper())

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

# =============================================================================
# RENDER TABS
# =============================================================================
with tab_shot:
    render_shot_tab()

with tab_pass:
    render_pass_tab()

with tab_def:
    render_def_tab()

st.markdown('<div class="cm-footer">@B03GHB4L1</div>', unsafe_allow_html=True)
