import os
import shutil
import subprocess
import sys
import tempfile
from html import escape

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme
from clipmaker_core import read_csv_safe, to_seconds

try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PLOTLY_AVAILABLE = True
except ImportError:
    _PLOTLY_AVAILABLE = False


st.set_page_config(
    page_title="Tactical Lab - ClipMaker v1.2.2",
    page_icon="../ClipMaker_logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.inject(
    logo_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ClipMaker_logo.png")
)
theme.init_shared_state()
theme.render_top_nav("tactical")

HOME_COLOR = "#7ab4ff"
AWAY_COLOR = "#ff7351"
ACCENT = "#DFFF00"
MUTED = "#767575"
SHOT_TYPES = {"SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost", "BlockedShot", "AttemptSaved", "Attempt"}
DEF_WIN_TYPES = {"BallRecovery", "Interception", "Tackle"}
PPDA_DEFENSIVE_ACTION_TYPES = {"Tackle", "Interception", "Challenge", "BallRecovery"}
LOSS_TYPES = {"Dispossessed", "Error"}
IN_POSSESSION_ACTION_TYPES = {"Pass", "Carry", "TakeOn", "BallTouch", *SHOT_TYPES}
PITCH_ZONE_ORDER = ["Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing"]
DEPTH_ZONE_ORDER = ["Attacking Third", "Middle Third", "Defensive Third"]
PPDA_PRESS_ZONE_MIN_X = 40
PPDA_SCORE_CEILING = 20
PERIOD_ORDER = {
    "FirstHalf": 1,
    "SecondHalf": 2,
    "FirstPeriodOfExtraTime": 3,
    "SecondPeriodOfExtraTime": 4,
    "PenaltyShootout": 5,
}
PLOTLY_EXPORT_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "filename": "clipmaker_tactical_lab", "scale": 2},
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}
TRANSITION_PITCH_HEIGHT = 510


def _is_light():
    return bool(st.session_state.get("light_mode", False))


def _bool_series(df, col):
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    return df[col].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def _num(df, col, default=0.0):
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def _str_series(df, col, default=""):
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="object")
    return df[col].fillna(default).astype(str)


def _event_clock(row):
    minute = int(float(row.get("minute", 0) or 0))
    second = int(float(row.get("second", 0) or 0))
    return f"{minute}'{second:02d}\""


def _fmt_metric(value, suffix="", decimals=0):
    if pd.isna(value):
        return "-"
    if decimals:
        return f"{float(value):.{decimals}f}{suffix}"
    return f"{int(round(float(value)))}{suffix}"


def _brand_fig(fig, height=None):
    light = _is_light()
    if light:
        paper = "#f5f0e8"
        plot = "#f0ebe2"
        font = "#111111"
        grid = "rgba(80,60,30,0.14)"
        line = "rgba(80,60,30,0.28)"
    else:
        paper = "#0b0e14"
        plot = "#10131a"
        font = "#ecedf6"
        grid = "rgba(142,255,113,0.08)"
        line = "rgba(142,255,113,0.18)"
    fig.update_layout(
        paper_bgcolor=paper,
        plot_bgcolor=plot,
        font=dict(color=font, family="Inter, sans-serif"),
        margin=dict(l=18, r=18, t=42, b=24),
        hoverlabel=dict(bgcolor=plot, bordercolor=line, font=dict(color=font)),
    )
    fig.update_xaxes(gridcolor=grid, zerolinecolor=line, linecolor=line, tickfont=dict(color=font))
    fig.update_yaxes(gridcolor=grid, zerolinecolor=line, linecolor=line, tickfont=dict(color=font))
    if height:
        fig.update_layout(height=height)
    return fig


def _pitch_layout(fig, title="", height=520):
    light = _is_light()
    paper = "#f5f0e8" if light else "#0b0e14"
    pitch = "#d4e8c2" if light else "#172617"
    line = "rgba(30,70,10,0.58)" if light else "rgba(220,220,220,0.42)"
    fig.update_layout(
        title=title,
        height=height,
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False, visible=False),
        yaxis=dict(range=[0, 100], showgrid=False, zeroline=False, visible=False, scaleanchor="x", scaleratio=0.68),
        plot_bgcolor=pitch,
        paper_bgcolor=paper,
        margin=dict(l=10, r=10, t=42, b=10),
        font=dict(color="#111111" if light else "#ecedf6", family="Inter, sans-serif"),
        hoverlabel=dict(
            bgcolor="#f0ebe2" if light else "#10131a",
            bordercolor=line,
            font=dict(color="#111111" if light else "#ecedf6"),
        ),
    )
    shapes = [
        dict(type="rect", x0=0, y0=0, x1=100, y1=100, line=dict(color=line, width=2)),
        dict(type="line", x0=50, y0=0, x1=50, y1=100, line=dict(color=line, width=1.4)),
        dict(type="rect", x0=0, y0=21, x1=16.5, y1=79, line=dict(color=line, width=1.3)),
        dict(type="rect", x0=83.5, y0=21, x1=100, y1=79, line=dict(color=line, width=1.3)),
        dict(type="circle", x0=41.5, y0=35, x1=58.5, y1=65, line=dict(color=line, width=1.3)),
    ]
    fig.update_layout(shapes=shapes)
    return fig


def _scatter_pitch(df, title, color_col=None, color_map=None, hover_cols=None, height=520):
    fig = go.Figure()
    if df.empty:
        return _pitch_layout(fig, title, height=height)
    hover_cols = hover_cols or []
    work = df.copy()
    work["x_plot"] = _num(work, "x")
    work["y_plot"] = _num(work, "y")
    if color_col and color_col in work.columns:
        for label, group in work.groupby(color_col, dropna=False):
            color = (color_map or {}).get(label, ACCENT)
            hover = []
            for _, row in group.iterrows():
                bits = [f"<b>{row.get('team', '')}</b>", f"{row.get('playerName', '')} - {_event_clock(row)}"]
                bits.extend(f"{c}: {row.get(c, '')}" for c in hover_cols if c in row)
                hover.append("<br>".join(bits))
            fig.add_trace(go.Scatter(
                x=group["x_plot"], y=group["y_plot"], mode="markers",
                name=str(label), text=hover, hovertemplate="%{text}<extra></extra>",
                marker=dict(size=12, color=color, line=dict(width=1, color="#0e0e0e"), opacity=0.84),
            ))
    else:
        hover = [f"<b>{r.get('team', '')}</b><br>{r.get('playerName', '')} - {_event_clock(r)}" for _, r in work.iterrows()]
        fig.add_trace(go.Scatter(
            x=work["x_plot"], y=work["y_plot"], mode="markers",
            text=hover, hovertemplate="%{text}<extra></extra>",
            marker=dict(size=12, color=ACCENT, line=dict(width=1, color="#0e0e0e"), opacity=0.84),
        ))
    return _pitch_layout(fig, title, height=height)


def _arrow_pitch(df, title, color=ACCENT, limit=80):
    fig = go.Figure()
    if not df.empty:
        work = df.head(limit).copy()
        for _, row in work.iterrows():
            x0, y0 = float(row.get("x", 0) or 0), float(row.get("y", 0) or 0)
            x1, y1 = float(row.get("endX", x0) or x0), float(row.get("endY", y0) or y0)
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines+markers",
                line=dict(color=color, width=1.8),
                marker=dict(size=[5, 8], color=color),
                opacity=0.58,
                hovertemplate=f"{row.get('playerName','')}<br>{row.get('type','')} - {_event_clock(row)}<extra></extra>",
                showlegend=False,
            ))
    return _pitch_layout(fig, title)


def _prepare_df(df):
    df = df.copy()
    df["period_order"] = _str_series(df, "period").map(PERIOD_ORDER).fillna(1).astype(int)
    df["minute"] = _num(df, "minute").astype(int)
    df["second"] = _num(df, "second").astype(int)
    df["event_seconds"] = df["minute"] * 60 + df["second"]
    df["x"] = _num(df, "x")
    df["y"] = _num(df, "y")
    df["endX"] = _num(df, "endX")
    df["endY"] = _num(df, "endY")
    df["xT"] = _num(df, "xT")
    sort_cols = ["period_order", "event_seconds"]
    if "match_id" in df.columns:
        sort_cols = ["match_id"] + sort_cols
    df = df.sort_values(sort_cols).reset_index(drop=True)
    df["event_id"] = df.index
    return df


def _sample_paths():
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "match data")
    if not os.path.isdir(base):
        return []
    return sorted(os.path.join(base, f) for f in os.listdir(base) if f.lower().endswith(".csv"))


@st.cache_data(show_spinner=False)
def _load_csv(path):
    return _prepare_df(read_csv_safe(path))


def _match_label(path):
    label = os.path.basename(path)
    return label.replace("whoscored_", "").replace("_all_events.csv", "").replace("_", " ")


def _load_matches():
    session_path = st.session_state.get("csv_path") or st.session_state.get("scraped_csv_path") or ""
    samples = _sample_paths()
    options = []
    for path in (st.session_state.get("multi_scraped_csv_paths", []) or []) + samples + ([session_path] if session_path else []):
        if path and os.path.exists(path) and path not in options:
            options.append(path)

    with st.expander("Match Source", expanded=False):
        st.toggle("Analyze across matches", key="tl_multi_mode", value=False)
        if st.session_state.get("tl_multi_mode", False):
            selected = st.multiselect(
                "Select matches (1-10)",
                options=options,
                format_func=os.path.basename,
                max_selections=10,
                key="tl_selected_matches",
            )
            if not selected:
                st.info("Select at least one match.")
                return None, []
            frames = []
            labels = []
            for idx, path in enumerate(selected):
                frame = _load_csv(path).copy()
                frame["match_id"] = idx
                frame["match_label"] = _match_label(path)
                frames.append(frame)
                labels.append(os.path.basename(path))
            merged = _prepare_df(pd.concat(frames, ignore_index=True))
            return merged, labels

    if session_path and os.path.exists(session_path):
        df = _load_csv(session_path).copy()
        df["match_id"] = 0
        df["match_label"] = _match_label(session_path)
        return _prepare_df(df), [os.path.basename(session_path)]

    if options:
        choice = st.selectbox("Sample match", options, format_func=os.path.basename)
        df = _load_csv(choice).copy()
        df["match_id"] = 0
        df["match_label"] = _match_label(choice)
        return _prepare_df(df), [os.path.basename(choice)]

    return None, []


def _team_names(df):
    home = str(df["homeTeam"].dropna().iloc[0]) if "homeTeam" in df.columns and not df["homeTeam"].dropna().empty else ""
    away = str(df["awayTeam"].dropna().iloc[0]) if "awayTeam" in df.columns and not df["awayTeam"].dropna().empty else ""
    teams = [t for t in [home, away] if t]
    if len(teams) < 2 and "team" in df.columns:
        teams = sorted(df["team"].dropna().astype(str).unique().tolist())[:2]
    return teams


def _loss_mask(df, team):
    team_df = df["team"].astype(str).eq(team)
    unsuccessful = _str_series(df, "outcomeType").eq("Unsuccessful")
    risky_types = df["type"].isin(["Pass", "Carry", "TakeOn", "BallTouch"])
    return team_df & ((unsuccessful & risky_types) | df["type"].isin(LOSS_TYPES))


def _def_win_mask(df, team):
    team_df = df["team"].astype(str).eq(team)
    successful_or_recovery = _str_series(df, "outcomeType").eq("Successful") | df["type"].eq("BallRecovery")
    return team_df & df["type"].isin(DEF_WIN_TYPES) & successful_or_recovery


def _danger_mask(df):
    return (
        df["type"].isin(SHOT_TYPES)
        | _bool_series(df, "is_box_entry_pass")
        | _bool_series(df, "is_box_entry_carry")
        | _bool_series(df, "is_touch_in_box")
        | _bool_series(df, "is_deep_completion")
    )


def _progression_mask(df):
    return (
        _bool_series(df, "prog_pass")
        | _bool_series(df, "prog_carry")
        | _bool_series(df, "is_final_third_entry_pass")
        | _bool_series(df, "is_final_third_entry_carry")
        | _bool_series(df, "is_box_entry_pass")
        | _bool_series(df, "is_box_entry_carry")
    )


def detect_defensive_transitions(df, team, window_seconds=8, max_events=8):
    losses = df[_loss_mask(df, team)].copy()
    rows = []
    for _, loss in losses.iterrows():
        same_period = df["period_order"].eq(loss["period_order"])
        same_match = df["match_id"].eq(loss.get("match_id")) if "match_id" in df.columns else pd.Series(True, index=df.index)
        after = df[same_match & same_period & (df["event_id"] > loss["event_id"])].head(max_events)
        after = after[after["event_seconds"].sub(loss["event_seconds"]).between(0, window_seconds)]
        opp = after[after["team"].astype(str).ne(team)]
        own = after[after["team"].astype(str).eq(team)]
        recovered = bool((_def_win_mask(own, team)).any()) if not own.empty else False
        shot = bool(opp["type"].isin(SHOT_TYPES).any())
        box_entry = bool(_danger_mask(opp).any()) if not opp.empty else False
        progression = bool(_progression_mask(opp).any()) if not opp.empty else False
        if recovered:
            outcome = "Recovered"
        elif shot:
            outcome = "Shot conceded"
        elif box_entry:
            outcome = "Box entry conceded"
        elif progression:
            outcome = "Progression conceded"
        else:
            outcome = "Slowed"
        rows.append({
            "event_id": loss["event_id"],
            "match_id": loss.get("match_id", None),
            "match_label": loss.get("match_label", ""),
            "team": team,
            "playerName": loss.get("playerName", ""),
            "type": loss.get("type", ""),
            "outcomeType": loss.get("outcomeType", ""),
            "period": loss.get("period", ""),
            "minute": loss["minute"],
            "second": loss["second"],
            "x": loss["x"],
            "y": loss["y"],
            "outcome": outcome,
            "opp_events": len(opp),
            "opp_xT": opp["xT"].clip(lower=0).sum() if not opp.empty else 0.0,
            "recovered": recovered,
            "shot_conceded": shot,
            "box_entry_conceded": box_entry,
            "progression_conceded": progression,
        })
    return pd.DataFrame(rows)


def detect_attacking_transitions(df, team, window_seconds=10, max_events=8):
    wins = df[_def_win_mask(df, team)].copy()
    rows = []
    for _, win in wins.iterrows():
        same_period = df["period_order"].eq(win["period_order"])
        same_match = df["match_id"].eq(win.get("match_id")) if "match_id" in df.columns else pd.Series(True, index=df.index)
        after = df[same_match & same_period & (df["event_id"] >= win["event_id"])].head(max_events)
        after = after[after["event_seconds"].sub(win["event_seconds"]).between(0, window_seconds)]
        own = after[after["team"].astype(str).eq(team)]
        shot = bool(own["type"].isin(SHOT_TYPES).any())
        box_entry = bool(_danger_mask(own).any()) if not own.empty else False
        progression = bool(_progression_mask(own).any()) if not own.empty else False
        retained = len(own) >= 3
        if shot:
            outcome = "Shot"
        elif box_entry:
            outcome = "Box entry"
        elif progression:
            outcome = "Progression"
        elif retained:
            outcome = "Retained"
        else:
            outcome = "Stalled"
        rows.append({
            "event_id": win["event_id"],
            "match_id": win.get("match_id", None),
            "match_label": win.get("match_label", ""),
            "team": team,
            "playerName": win.get("playerName", ""),
            "type": win.get("type", ""),
            "outcomeType": win.get("outcomeType", ""),
            "period": win.get("period", ""),
            "minute": win["minute"],
            "second": win["second"],
            "x": win["x"],
            "y": win["y"],
            "outcome": outcome,
            "own_events": len(own),
            "xT_created": own["xT"].clip(lower=0).sum() if not own.empty else 0.0,
            "shot": shot,
            "box_entry": box_entry,
            "progression": progression,
        })
    return pd.DataFrame(rows)


def render_metric_row(items):
    cols = st.columns(len(items))
    for col, (label, value, help_text) in zip(cols, items):
        col.metric(label, value, help=help_text)


def _match_scope_df(df, key, label="Analysis scope"):
    if "match_id" not in df.columns or df["match_id"].nunique() <= 1:
        return df
    options = ["All selected matches"]
    match_rows = df.groupby("match_id")["match_label"].first().reset_index().sort_values("match_id")
    options.extend(match_rows["match_label"].astype(str).tolist())
    selected = st.selectbox(label, options, key=key)
    if selected == "All selected matches":
        return df
    match_id = match_rows.loc[match_rows["match_label"].astype(str).eq(selected), "match_id"]
    if match_id.empty:
        return df
    return df[df["match_id"].eq(match_id.iloc[0])].copy()


def _period_int(period_value):
    return PERIOD_ORDER.get(str(period_value), 1)


def _period_label(period_value):
    return {
        "FirstHalf": "1H",
        "SecondHalf": "2H",
        "FirstPeriodOfExtraTime": "ET1",
        "SecondPeriodOfExtraTime": "ET2",
        "PenaltyShootout": "PS",
    }.get(str(period_value), "")


def _video_state():
    return {
        "video_path": st.session_state.get("video_path", ""),
        "video2_path": st.session_state.get("video2_path", ""),
        "split_video": bool(st.session_state.get("split_video", False)),
        "half1_time": st.session_state.get("half1_time", ""),
        "half2_time": st.session_state.get("half2_time", ""),
        "half3_time": st.session_state.get("half3_time", ""),
        "half4_time": st.session_state.get("half4_time", ""),
        "half5_time": st.session_state.get("half5_time", ""),
    }


def _video_ready():
    state = _video_state()
    if not (state["video_path"] and os.path.exists(state["video_path"])):
        return False
    if state["split_video"] and not (state["video2_path"] and os.path.exists(state["video2_path"])):
        return False
    return True


def _get_ffmpeg():
    cmd = shutil.which("ffmpeg")
    if cmd:
        return cmd
    try:
        from moviepy.config import FFMPEG_BINARY
        if os.path.exists(FFMPEG_BINARY):
            return FFMPEG_BINARY
    except Exception:
        pass
    raise ValueError("FFmpeg not found. Install FFmpeg or run ClipMaker with bundled dependencies.")


def _period_starts():
    state = _video_state()
    values = {
        1: state["half1_time"],
        2: state["half2_time"],
        3: state["half3_time"],
        4: state["half4_time"],
        5: state["half5_time"],
    }
    starts = {}
    for period, value in values.items():
        if value:
            starts[period] = to_seconds(value)
    return starts


def _match_seconds(row):
    return int(row.get("minute", 0) or 0) * 60 + int(row.get("second", 0) or 0)


def _video_timestamp(row):
    period = _period_int(row.get("period", "FirstHalf"))
    starts = _period_starts()
    if period not in starts:
        raise ValueError(f"No kick-off video time set for period {period}.")
    offset = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60, 5: 120 * 60}.get(period, 0)
    return starts[period] + max(0, _match_seconds(row) - offset)


def _source_video(row):
    state = _video_state()
    period = _period_int(row.get("period", "FirstHalf"))
    if state["split_video"] and period >= 2:
        if not state["video2_path"]:
            raise ValueError("2nd half video file is required for this second-half clip.")
        return state["video2_path"]
    return state["video_path"]


def _cut_tactical_clip(row, before=8, after=12):
    if not _video_ready():
        raise ValueError("No video file loaded. Set the match video on Home first.")
    src = _source_video(row)
    if not src or not os.path.exists(src):
        raise ValueError("The selected source video file could not be found.")
    video_ts = _video_timestamp(row)
    start_ts = max(0.0, video_ts - int(before))
    duration = max(1.0, int(before) + int(after))
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    out = tmp.name
    tmp.close()
    result = subprocess.run([
        _get_ffmpeg(), "-y", "-ss", str(start_ts), "-i", src,
        "-t", str(duration), "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "0",
        "-c:a", "aac", "-avoid_negative_ts", "make_zero", out,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError(f"FFmpeg error: {result.stderr[-400:]}")
    return out


def _concat_tactical_clips(paths):
    if not paths:
        raise ValueError("No clips were created.")
    if len(paths) == 1:
        return paths[0]
    list_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8")
    try:
        for path in paths:
            list_file.write(f"file '{path.replace(os.sep, '/')}'\n")
        list_file.close()
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        out = tmp.name
        tmp.close()
        result = subprocess.run([
            _get_ffmpeg(), "-y", "-f", "concat", "-safe", "0",
            "-i", list_file.name, "-c", "copy", out,
        ], capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"FFmpeg concat error: {result.stderr[-400:]}")
        return out
    finally:
        try:
            os.remove(list_file.name)
        except Exception:
            pass


def _event_window(df, row, before=6, after=12):
    event_seconds = row.get("event_seconds", None)
    period_order = row.get("period_order", None)
    if pd.isna(event_seconds) or pd.isna(period_order):
        match = df[df["event_id"].eq(row.get("event_id"))]
        if not match.empty:
            event_seconds = match.iloc[0].get("event_seconds", 0)
            period_order = match.iloc[0].get("period_order", 1)
    event_seconds = 0 if pd.isna(event_seconds) else event_seconds
    period_order = 1 if pd.isna(period_order) else period_order
    start = int(event_seconds) - int(before)
    end = int(event_seconds) + int(after)
    same_match = pd.Series(True, index=df.index)
    match_id = row.get("match_id", None)
    if "match_id" in df.columns and match_id is not None and not pd.isna(match_id):
        same_match = df["match_id"].eq(match_id)
    return df[
        same_match
        & df["period_order"].eq(int(period_order))
        & df["event_seconds"].between(start, end)
    ].copy()


def _coord_value(row, col, default=0):
    value = row.get(col, default)
    if pd.isna(value):
        value = default
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(100.0, float(default or 0)))


def _trace_coordinates(row, focus_team=""):
    x0 = _coord_value(row, "x", 0)
    y0 = _coord_value(row, "y", 0)
    x1 = _coord_value(row, "endX", x0)
    y1 = _coord_value(row, "endY", y0)
    team_name = "" if pd.isna(row.get("team", "")) else str(row.get("team", ""))
    focus_team = str(focus_team or "")

    flip_length = bool(focus_team and team_name and team_name != focus_team)
    flip_width = flip_length

    if flip_length:
        x0, x1 = 100 - x0, 100 - x1
    if flip_width:
        y0, y1 = 100 - y0, 100 - y1
    return x0, y0, x1, y1


def _sequence_trace(window_df, focus_id=None, focus_team=""):
    fig = go.Figure()
    if window_df.empty:
        return _pitch_layout(fig, "Event Trace", height=390)
    work = window_df.sort_values("event_id").copy()
    for _, row in work.iterrows():
        color = ACCENT if row.get("event_id") == focus_id else (HOME_COLOR if row.get("type") in ["Pass", "Carry"] else AWAY_COLOR)
        x0, y0, x1, y1 = _trace_coordinates(row, focus_team)
        player = "" if pd.isna(row.get("playerName", "")) else str(row.get("playerName", ""))
        event_type = "" if pd.isna(row.get("type", "")) else str(row.get("type", ""))
        team_name = "" if pd.isna(row.get("team", "")) else str(row.get("team", ""))
        xt_value = float(row.get("xT", 0) or 0)
        hover_text = (
            f"<b>{event_type or 'Event'}</b>"
            f"<br>{player or 'Unknown player'}"
            f"<br>{team_name}"
            f"<br>{_event_clock(row)}"
            f"<br>xT: {xt_value:.3f}"
            f"<br>Trace frame: selected team attacks right"
        )
        if row.get("type") in ["Pass", "Carry"] and (x0 != x1 or y0 != y1):
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[y0, y1],
                mode="lines+markers",
                line=dict(color=color, width=3 if row.get("event_id") == focus_id else 1.7),
                marker=dict(size=[6, 9], color=color),
                opacity=0.86 if row.get("event_id") == focus_id else 0.45,
                text=[hover_text, hover_text],
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            ))
        else:
            fig.add_trace(go.Scatter(
                x=[x0], y=[y0],
                mode="markers",
                marker=dict(size=13 if row.get("event_id") == focus_id else 8, color=color, line=dict(color="#111111", width=1)),
                opacity=0.9 if row.get("event_id") == focus_id else 0.55,
                text=[hover_text],
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            ))
    return _pitch_layout(fig, "Event Trace", height=390)


def _box_entry_mask(df):
    return _bool_series(df, "is_box_entry_pass") | _bool_series(df, "is_box_entry_carry")


def _playlist_rows(df, team, dt_seconds, dt_events, at_seconds, at_events):
    rows = []
    defensive = detect_defensive_transitions(df, team, dt_seconds, dt_events)
    if not defensive.empty:
        for _, row in defensive.sort_values(["shot_conceded", "box_entry_conceded", "opp_xT"], ascending=False).head(30).iterrows():
            rows.append({
                **row.to_dict(),
                "playlist": "Defensive Transition",
                "score": float(row.get("opp_xT", 0)) + (3 if row.get("shot_conceded") else 0) + (1.5 if row.get("box_entry_conceded") else 0),
                "why": row.get("outcome", ""),
            })
    attacking = detect_attacking_transitions(df, team, at_seconds, at_events)
    if not attacking.empty:
        for _, row in attacking.sort_values(["shot", "box_entry", "xT_created"], ascending=False).head(30).iterrows():
            rows.append({
                **row.to_dict(),
                "playlist": "Attacking Transition",
                "score": float(row.get("xT_created", 0)) + (3 if row.get("shot") else 0) + (1.5 if row.get("box_entry") else 0),
                "why": row.get("outcome", ""),
            })
    team_df = df[df["team"].astype(str).eq(team)].copy()
    threat = team_df[team_df["type"].isin(["Pass", "Carry"]) & (team_df["xT"] > 0)].sort_values("xT", ascending=False).head(30)
    for _, row in threat.iterrows():
        rows.append({
            **row.to_dict(),
            "playlist": "xT Passes And Carries",
            "score": float(row.get("xT", 0)),
            "why": f"+{float(row.get('xT', 0)):.3f} xT",
        })
    box_entries = team_df[_box_entry_mask(team_df)].copy()
    if not box_entries.empty:
        box_entries["entry_score"] = box_entries["xT"].clip(lower=0) + box_entries["type"].isin(SHOT_TYPES).astype(int)
        for _, row in box_entries.sort_values("entry_score", ascending=False).head(30).iterrows():
            rows.append({
                **row.to_dict(),
                "playlist": "Box Entries",
                "score": float(row.get("entry_score", 0)),
                "why": str(row.get("type", "")),
            })
    restarts = team_df[_set_piece_mask(team_df)].copy()
    if not restarts.empty:
        for _, row in restarts.sort_values("xT", ascending=False).head(30).iterrows():
            rows.append({
                **row.to_dict(),
                "playlist": "Restarts",
                "score": float(max(row.get("xT", 0), 0)),
                "why": _restart_type(row),
            })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    event_lookup = df.set_index("event_id")
    for col in ["event_seconds", "period_order", "endX", "endY"]:
        if col in event_lookup.columns:
            mapped = out["event_id"].map(event_lookup[col])
            if col not in out.columns:
                out[col] = mapped
            else:
                out[col] = out[col].where(out[col].notna(), mapped)
    out["time"] = out.apply(_event_clock, axis=1)
    out["period_label"] = out["period"].map(_period_label)
    out["moment"] = (
        out["time"].astype(str) + " " + out["period_label"].astype(str)
        + " | " + out["playerName"].fillna("").astype(str)
        + " | " + out["type"].fillna("").astype(str)
        + " | " + out["why"].fillna("").astype(str)
    )
    return out.sort_values(["playlist", "score"], ascending=[True, False]).reset_index(drop=True)


def _moment_list_html(rows):
    light = _is_light()
    bg = "#f0ebe2" if light else "#10131a"
    border = "rgba(80,60,30,0.22)" if light else "rgba(142,255,113,0.16)"
    head = "#ded7ca" if light else "#171b24"
    text = "#111111" if light else "#ecedf6"
    sub = "#5d5a52" if light else "#aaaeb8"
    line = "rgba(80,60,30,0.12)" if light else "rgba(255,255,255,0.08)"
    html = [
        f'<div style="border:1px solid {border};background:{bg};border-radius:4px;overflow:hidden">',
        f'<div style="display:grid;grid-template-columns:72px 1.4fr 1fr 58px;gap:0;background:{head};border-bottom:1px solid {border};font-family:monospace;font-size:11px;letter-spacing:0.04em;text-transform:uppercase;color:{sub}">',
        '<div style="padding:9px 10px">Time</div>',
        '<div style="padding:9px 10px">Player</div>',
        '<div style="padding:9px 10px">Moment</div>',
        '<div style="padding:9px 10px;text-align:right">Score</div>',
        '</div>',
    ]
    for _, row in rows.head(10).iterrows():
        html.append(f'<div style="display:grid;grid-template-columns:72px 1.4fr 1fr 58px;gap:0;border-bottom:1px solid {line};font-family:monospace;font-size:12px;color:{text}">')
        html.append(f'<div style="padding:9px 10px">{escape(str(row.get("time", "")))} {escape(str(row.get("period_label", "")))}</div>')
        html.append(f'<div style="padding:9px 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{escape(str(row.get("playerName", "")))}</div>')
        html.append(f'<div style="padding:9px 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{escape(str(row.get("type", "")))} | {escape(str(row.get("why", "")))}</div>')
        html.append(f'<div style="padding:9px 10px;text-align:right">{float(row.get("score", 0) or 0):.2f}</div>')
        html.append('</div>')
    html.append("</div>")
    return "".join(html)


def render_video_lab(df, team):
    st.subheader("Video Lab")
    df = _match_scope_df(df, "vl_match_scope", "Clip source match")
    vc1, vc2, vc3, vc4 = st.columns([1, 1, 1, 1])
    with vc1:
        playlist = st.selectbox("Playlist", [
            "Defensive Transition",
            "Attacking Transition",
            "xT Passes And Carries",
            "Box Entries",
            "Restarts",
        ], key="vl_playlist")
    with vc2:
        before = st.slider("Before clip", 0, 30, 8, key="vl_before")
    with vc3:
        after = st.slider("After clip", 4, 45, 14, key="vl_after")
    with vc4:
        reel_count = st.slider("Reel moments", 2, 10, 5, key="vl_reel_count")

    rows = _playlist_rows(
        df,
        team,
        st.session_state.get("dt_seconds", 8),
        st.session_state.get("dt_events", 8),
        st.session_state.get("at_seconds", 10),
        st.session_state.get("at_events", 8),
    )
    if rows.empty:
        st.info("No tactical moments found for the selected team.")
        return
    current = rows[rows["playlist"].eq(playlist)].copy()
    if current.empty:
        st.info("No moments found for this playlist.")
        return

    current = current.sort_values("score", ascending=False).head(40).reset_index(drop=True)
    selected_label = st.selectbox("Moment", current["moment"].tolist(), key=f"vl_selected_moment_{playlist}")
    selected = current[current["moment"].eq(selected_label)].iloc[0].to_dict()
    clip_key = f"{team}|{playlist}|{int(selected.get('event_id', -1))}|{before}|{after}"

    detail, trace = st.columns([1, 1.35], gap="large")
    with detail:
        render_metric_row([
            ("Time", f"{selected.get('time', '')} {selected.get('period_label', '')}", "Match clock for this tactical moment."),
            ("Player", selected.get("playerName", "-") or "-", "Primary event player."),
            ("Score", _fmt_metric(selected.get("score", 0), decimals=2), "Playlist ranking score from the event context."),
        ])
        st.markdown(_moment_list_html(current), unsafe_allow_html=True)
    with trace:
        window = _event_window(df, selected, before=6, after=max(10, after))
        st.caption(
            "Event Trace shows the highlighted event plus nearby match events from the same period. "
            "The trace is normalized so the selected team attacks left-to-right."
        )
        try:
            st.plotly_chart(
                _sequence_trace(window, selected.get("event_id"), team),
                use_container_width=True,
                config=PLOTLY_EXPORT_CONFIG,
            )
        except Exception as exc:
            st.error(f"Could not render event trace: {exc}")

    clip_path = st.session_state.get("vl_clip_path")
    clip_error = st.session_state.get("vl_clip_error")
    cached_key = st.session_state.get("vl_clip_key")
    b1, b2, b3 = st.columns([1, 1, 2])
    with b1:
        disabled = not _video_ready()
        if st.button("Cut Moment", key="vl_cut", use_container_width=True, disabled=disabled):
            with st.spinner("Cutting tactical clip..."):
                try:
                    path = _cut_tactical_clip(selected, before=before, after=after)
                    st.session_state["vl_clip_path"] = path
                    st.session_state["vl_clip_key"] = clip_key
                    st.session_state["vl_clip_error"] = None
                except Exception as exc:
                    st.session_state["vl_clip_error"] = str(exc)
                    st.session_state["vl_clip_key"] = clip_key
            st.rerun()
    with b2:
        reel_key = f"{team}|{playlist}|{before}|{after}|{reel_count}|" + ",".join(current.head(reel_count)["event_id"].astype(str))
        if st.button("Build Reel", key="vl_reel", use_container_width=True, disabled=not _video_ready()):
            made = []
            with st.spinner("Building tactical reel..."):
                try:
                    for _, row in current.head(reel_count).iterrows():
                        made.append(_cut_tactical_clip(row.to_dict(), before=before, after=after))
                    st.session_state["vl_reel_path"] = _concat_tactical_clips(made)
                    st.session_state["vl_reel_key"] = reel_key
                    st.session_state["vl_reel_error"] = None
                except Exception as exc:
                    st.session_state["vl_reel_error"] = str(exc)
                    st.session_state["vl_reel_key"] = reel_key
            st.rerun()
    with b3:
        if not _video_ready():
            st.caption("Load a match video on Home to cut moments and reels.")

    if cached_key == clip_key and clip_path and os.path.exists(clip_path):
        st.video(clip_path)
    elif clip_error and cached_key == clip_key:
        st.error(f"Could not cut moment: {clip_error}")

    reel_path = st.session_state.get("vl_reel_path")
    reel_error = st.session_state.get("vl_reel_error")
    if st.session_state.get("vl_reel_key") == (
        f"{team}|{playlist}|{before}|{after}|{reel_count}|" + ",".join(current.head(reel_count)["event_id"].astype(str))
    ):
        if reel_path and os.path.exists(reel_path):
            st.markdown("##### Playlist Reel")
            st.video(reel_path)
            with open(reel_path, "rb") as file:
                st.download_button("Download Reel", file.read(), file_name=f"{team}_{playlist.replace(' ', '_')}_reel.mp4", mime="video/mp4")
        elif reel_error:
            st.error(f"Could not build reel: {reel_error}")


def render_defensive_transitions(df, team):
    st.subheader("Defensive Transitions")
    df = _match_scope_df(df, "dt_match_scope")
    c1, c2 = st.columns([1, 1])
    with c1:
        seconds = st.slider("Reaction window", 4, 15, 8, key="dt_seconds")
    with c2:
        max_events = st.slider("Opponent event cap", 3, 12, 8, key="dt_events")
    trans = detect_defensive_transitions(df, team, seconds, max_events)
    if trans.empty:
        st.info("No possession-loss events found for this team.")
        return

    total = len(trans)
    recovered = trans["recovered"].mean() * 100
    dangerous = (trans["shot_conceded"] | trans["box_entry_conceded"]).mean() * 100
    avg_xt = trans["opp_xT"].mean()
    high_losses = (trans["x"] > 66).sum()
    render_metric_row([
        ("Losses Tracked", total, "Unsuccessful passes/carries/take-ons/touches plus dispossessions and errors."),
        ("Recovered", _fmt_metric(recovered, "%"), f"Recovered within {seconds} seconds / {max_events} events."),
        ("Danger Allowed", _fmt_metric(dangerous, "%"), "Opponent shot or box-entry event in the transition window."),
        ("Avg xT Allowed", _fmt_metric(avg_xt, decimals=3), "Mean positive opponent xT immediately after the loss."),
        ("High Losses", high_losses, "Losses in the attacking third, often the most counterpressable."),
    ])

    colors = {
        "Recovered": ACCENT,
        "Slowed": "#7ab4ff",
        "Progression conceded": "#f6c85f",
        "Box entry conceded": "#ff9f1c",
        "Shot conceded": "#ff7351",
    }
    st.plotly_chart(
        _scatter_pitch(trans, "Loss Locations By Transition Outcome", "outcome", colors, ["outcome", "opp_xT"], height=TRANSITION_PITCH_HEIGHT),
        use_container_width=True,
        config=PLOTLY_EXPORT_CONFIG,
    )

    st.caption(
        f"Read this as the team's rest-defence profile after losing the ball. "
        f"{_fmt_metric(recovered, '%')} of losses are recovered inside the selected window, while "
        f"{_fmt_metric(dangerous, '%')} become a shot or box-entry concession. The pitch plot shows where the losses happen "
        "and how the first defensive reaction resolves."
    )


def render_attacking_transitions(df, team):
    st.subheader("Attacking Transitions")
    df = _match_scope_df(df, "at_match_scope")
    c1, c2 = st.columns([1, 1])
    with c1:
        seconds = st.slider("Attack window", 5, 18, 10, key="at_seconds")
    with c2:
        max_events = st.slider("Own event cap", 3, 12, 8, key="at_events")
    trans = detect_attacking_transitions(df, team, seconds, max_events)
    if trans.empty:
        st.info("No recovery events found for this team.")
        return
    total = len(trans)
    threat = (trans["shot"] | trans["box_entry"]).mean() * 100
    prog = trans["progression"].mean() * 100
    avg_xt = trans["xT_created"].mean()
    high_wins = (trans["x"] > 66).sum()
    render_metric_row([
        ("Recoveries Tracked", total, "Ball recoveries, successful tackles and successful interceptions."),
        ("Threat Rate", _fmt_metric(threat, "%"), "Recoveries leading to a shot or box entry inside the window."),
        ("Progression Rate", _fmt_metric(prog, "%"), "Recoveries followed by meaningful territory gain."),
        ("Avg xT Created", _fmt_metric(avg_xt, decimals=3), "Mean positive xT created after the recovery."),
        ("High Wins", high_wins, "Recoveries in the opponent's final third."),
    ])

    colors = {
        "Shot": "#ff7351",
        "Box entry": "#ff9f1c",
        "Progression": ACCENT,
        "Retained": "#7ab4ff",
        "Stalled": MUTED,
    }
    st.plotly_chart(
        _scatter_pitch(trans, "Recovery Locations By Attack Outcome", "outcome", colors, ["outcome", "xT_created"], height=TRANSITION_PITCH_HEIGHT),
        use_container_width=True,
        config=PLOTLY_EXPORT_CONFIG,
    )

    st.caption(
        f"Read this as the team's ability to turn ball-wins into immediate attack. "
        f"{_fmt_metric(threat, '%')} of recoveries become a shot or box entry and "
        f"{_fmt_metric(prog, '%')} produce meaningful progression inside the selected window. The pitch plot shows launch points "
        "and separates fast threat from recoveries that only retain possession."
    )


def _attacking_set_piece_mask(df):
    return (
        _bool_series(df, "is_corner")
        | _bool_series(df, "is_freekick")
        | _bool_series(df, "is_throw_in")
        | df["type"].isin(["CornerAwarded"])
    )


def _set_piece_shot_ids(df, team, window_seconds=12, max_events=8):
    team_df = df[df["team"].astype(str).eq(team)].copy()
    restarts = team_df[_attacking_set_piece_mask(team_df)].copy()
    shot_ids = set()
    for _, restart in restarts.iterrows():
        same_match = df["match_id"].eq(restart.get("match_id")) if "match_id" in df.columns else pd.Series(True, index=df.index)
        after = df[
            same_match
            & df["period_order"].eq(restart["period_order"])
            & (df["event_id"] >= restart["event_id"])
            & df["event_seconds"].sub(restart["event_seconds"]).between(0, window_seconds)
        ].head(max_events)
        own_shots = after[after["team"].astype(str).eq(team) & after["type"].isin(SHOT_TYPES)]
        shot_ids.update(own_shots["event_id"].dropna().astype(int).tolist())
    return shot_ids, len(restarts)


def compute_style_metrics(df, team):
    team_df = df[df["team"].astype(str).eq(team)].copy()
    opp_df = df[df["team"].astype(str).ne(team)].copy()
    match_count = max(int(df["match_id"].nunique()) if "match_id" in df.columns else 1, 1)
    passes = max(int(team_df["type"].eq("Pass").sum()), 1)
    carries = int(team_df["type"].eq("Carry").sum())
    box_entries = (_bool_series(team_df, "is_box_entry_pass") | _bool_series(team_df, "is_box_entry_carry")).sum()
    ft_entries = (_bool_series(team_df, "is_final_third_entry_pass") | _bool_series(team_df, "is_final_third_entry_carry")).sum()
    touches_att_third = _str_series(team_df, "depth_zone").eq("Attacking Third").sum()
    opp_att_third = _str_series(opp_df, "depth_zone").eq("Attacking Third").sum()
    field_tilt = touches_att_third / max(touches_att_third + opp_att_third, 1) * 100
    ppda_zone = df["x"] >= PPDA_PRESS_ZONE_MIN_X
    opponent_passes_allowed = int((df["team"].astype(str).ne(team) & df["type"].eq("Pass") & ppda_zone).sum())
    ppda_committed_fouls = df["type"].eq("Foul") & _str_series(df, "outcomeType").eq("Unsuccessful")
    press_defensive_actions = int((
        df["team"].astype(str).eq(team)
        & (df["type"].isin(PPDA_DEFENSIVE_ACTION_TYPES) | ppda_committed_fouls)
        & ppda_zone
    ).sum())
    ppda = opponent_passes_allowed / max(press_defensive_actions, 1)
    pressing_score = max(0, min((PPDA_SCORE_CEILING - ppda) / PPDA_SCORE_CEILING * 100, 100))
    direct_count = (
        _bool_series(team_df, "is_long_ball")
        | _bool_series(team_df, "is_launch")
        | _bool_series(team_df, "is_diagonal_long_ball")
    ).sum()
    possession_actions = team_df["type"].isin(IN_POSSESSION_ACTION_TYPES)
    wide_zone = _str_series(team_df, "pitch_zone").isin(["Left Wing", "Right Wing"])
    wide_actions = int((possession_actions & wide_zone).sum())
    possession_action_count = int(possession_actions.sum())
    wide_play_pct = wide_actions / max(possession_action_count, 1) * 100
    shots = team_df["type"].isin(SHOT_TYPES).sum()
    set_piece_shot_ids, attacking_restart_count = _set_piece_shot_ids(df, team)
    penetration_actions = passes + carries + attacking_restart_count
    final_third_penetration_pct = (box_entries + ft_entries) / max(penetration_actions, 1) * 100
    set_piece_shots = len(set_piece_shot_ids)
    set_piece_shot_pct = set_piece_shots / max(int(shots), 1) * 100
    at = detect_attacking_transitions(df, team, 10, 8)
    dt = detect_defensive_transitions(df, team, 8, 8)
    transition_threat = (at["shot"] | at["box_entry"]).mean() * 100 if not at.empty else 0
    defensive_danger = (dt["shot_conceded"] | dt["box_entry_conceded"]).mean() * 100 if not dt.empty else 0
    pass_xt = team_df.loc[team_df["type"].eq("Pass"), "xT"].clip(lower=0)

    dims = {
        "Possession\nControl": round(field_tilt, 1),
        "Pressing\nIntensity": round(pressing_score, 1),
        "Directness": round(min(direct_count / passes * 300, 100), 1),
        "Wide Play": round(wide_play_pct, 1),
        "Final Third\nPenetration": round(min(final_third_penetration_pct * 5, 100), 1),
        "Set Piece\nReliance": round(min(set_piece_shot_pct, 100), 1),
        "Transition\nThreat": round(transition_threat, 1),
    }
    raw = {
        "matches_analyzed": int(match_count),
        "field_tilt_pct": round(field_tilt, 1),
        "box_entries": int(box_entries),
        "box_entries_per_match": round(box_entries / match_count, 1),
        "ft_entries": int(ft_entries),
        "ft_entries_per_match": round(ft_entries / match_count, 1),
        "final_third_penetration_pct": round(final_third_penetration_pct, 1),
        "penetration_actions": int(penetration_actions),
        "shots": int(shots),
        "shots_per_match": round(shots / match_count, 1),
        "direct_passes_pct": round(direct_count / passes * 100, 1),
        "wide_in_possession_actions": int(wide_actions),
        "wide_in_possession_action_pct": round(wide_play_pct, 1),
        "in_possession_actions": int(possession_action_count),
        "set_piece_count": int(attacking_restart_count),
        "set_piece_count_per_match": round(attacking_restart_count / match_count, 1),
        "set_piece_shots": int(set_piece_shots),
        "set_piece_shots_per_match": round(set_piece_shots / match_count, 1),
        "set_piece_shot_pct": round(set_piece_shot_pct, 1),
        "transition_threat_pct": round(transition_threat, 1),
        "xT_per_pass": round(float(pass_xt.mean()) if not pass_xt.empty else 0, 4),
        "defensive_losses_total": int(len(dt)),
        "defensive_losses_per_match": round(len(dt) / match_count, 1),
        "defensive_danger_pct": round(defensive_danger, 1),
        "passes_total": int(passes),
        "passes_per_match": round(passes / match_count, 1),
        "events_total": int(len(team_df)),
        "events_per_match": round(len(team_df) / match_count, 1),
        "ppda": round(ppda, 2),
        "ppda_opponent_passes": int(opponent_passes_allowed),
        "ppda_defensive_actions": int(press_defensive_actions),
    }
    return dims, raw


def _radar_chart(dims, team_name):
    labels = [label.replace("\n", "<br>") for label in dims.keys()]
    values = list(dims.values())
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=labels + [labels[0]],
        fill="toself",
        fillcolor="rgba(223,255,0,0.18)",
        line=dict(color=ACCENT, width=2.5),
        name=team_name,
        hovertemplate="%{theta}: %{r:.1f}<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], gridcolor="rgba(142,255,113,0.14)"),
            angularaxis=dict(tickfont=dict(size=11)),
        ),
        showlegend=False,
        margin=dict(l=58, r=58, t=44, b=44),
    )
    return _brand_fig(fig, 480)


def _radar_legend_html(raw):
    light = _is_light()
    bg = "#f0ebe2" if light else "#10131a"
    border = "rgba(80,60,30,0.22)" if light else "rgba(142,255,113,0.16)"
    text = "#111111" if light else "#ecedf6"
    sub = "#5d5a52" if light else "#aaaeb8"
    wide_actions = raw.get("wide_in_possession_actions", 0)
    wide_pct = raw.get("wide_in_possession_action_pct", 0)
    possession_actions = raw.get("in_possession_actions", 0)
    rows = [
        ("0-100 scale", "Indexed style scores, not percentiles. Higher means more pronounced in the loaded match scope."),
        ("Possession Control", "Field tilt: share of both teams' attacking-third activity."),
        ("Pressing Intensity", f"PPDA-based score. Lower PPDA means more intense pressure. Current PPDA: {raw.get('ppda', 0)} ({raw.get('ppda_opponent_passes', 0)} opponent passes / {raw.get('ppda_defensive_actions', 0)} defensive actions)."),
        ("Directness", f"Long balls, launches and diagonal long balls as a share of passes, scaled for the radar. Raw direct-pass share: {raw.get('direct_passes_pct', 0)}%."),
        ("Wide Play", f"Share of in-possession actions in the left and right wing zones: {wide_pct}% ({wide_actions}/{possession_actions})."),
        ("Final Third Penetration", f"Final-third entries plus box entries relative to passes, carries and attacking set pieces, scaled for the radar. Raw share: {raw.get('final_third_penetration_pct', 0)}% ({raw.get('ft_entries', 0) + raw.get('box_entries', 0)}/{raw.get('penetration_actions', 0)})."),
        ("Set Piece Reliance", f"Share of total shots that came shortly after an attacking restart: {raw.get('set_piece_shot_pct', 0)}% ({raw.get('set_piece_shots', 0)}/{raw.get('shots', 0)} shots)."),
        ("Transition Threat", f"Share of attacking transitions that produced a shot or box entry. Current rate: {raw.get('transition_threat_pct', 0)}%."),
    ]
    body = "".join(
        f'<div style="display:grid;grid-template-columns:150px 1fr;gap:14px;padding:8px 0;border-top:1px solid {border}">'
        f'<div style="color:{text};font-weight:700">{escape(label)}</div>'
        f'<div style="color:{sub}">{escape(desc)}</div>'
        f'</div>'
        for label, desc in rows
    )
    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:4px;padding:10px 14px;'
        f'font-family:monospace;font-size:12px;line-height:1.45">{body}</div>'
    )


def _per_match_trends(df, team, match_labels):
    rows = []
    if "match_id" not in df.columns:
        return pd.DataFrame()
    for match_id in sorted(df["match_id"].dropna().unique()):
        match_df = df[df["match_id"].eq(match_id)]
        dims, _ = compute_style_metrics(match_df, team)
        try:
            label = match_labels[int(match_id)]
        except Exception:
            label = str(match_id)
        row = {"Match": label}
        row.update(dims)
        rows.append(row)
    return pd.DataFrame(rows)


def detect_strengths_weaknesses(dims, raw):
    strengths = []
    weaknesses = []
    ft = raw.get("field_tilt_pct", 0)
    if ft >= 58:
        strengths.append({"label": "Territorial Dominance", "metric": f"Field tilt {ft}%", "context": "Controls a large share of attacking-third activity."})
    elif ft <= 42:
        weaknesses.append({"label": "Territorial Deficit", "metric": f"Field tilt {ft}%", "context": "Often spends less time applying pressure in advanced areas."})
    if raw.get("box_entries_per_match", 0) >= 12:
        strengths.append({"label": "Strong Box Penetration", "metric": f"{raw['box_entries_per_match']} box entries per match", "context": "Reaches dangerous areas regularly across the loaded matches."})
    elif raw.get("box_entries_per_match", 0) <= 4:
        weaknesses.append({"label": "Low Box Penetration", "metric": f"{raw['box_entries_per_match']} box entries per match", "context": "Final-third work is not converting into box-level danger often enough."})
    if raw.get("transition_threat_pct", 0) >= 35:
        strengths.append({"label": "Counter-Attack Potency", "metric": f"{raw['transition_threat_pct']}% transition threat", "context": "Recoveries are frequently converted into immediate danger."})
    if raw.get("defensive_danger_pct", 0) >= 40:
        weaknesses.append({"label": "Transition Vulnerability", "metric": f"{raw['defensive_danger_pct']}% danger after losses", "context": "Possession losses often expose the team quickly."})
    if raw.get("direct_passes_pct", 0) >= 25:
        strengths.append({"label": "Direct Play Style", "metric": f"{raw['direct_passes_pct']}% direct passes", "context": "Willing to play over pressure and attack forward runs."})
    if raw.get("set_piece_shot_pct", 0) > 50 and raw.get("set_piece_shots_per_match", 0) >= 1:
        weaknesses.append({
            "label": "Set Piece Over-Reliance",
            "metric": f"{raw['set_piece_shot_pct']}% of shots came after corners, free kicks or throw-ins",
            "context": "Most of the team's shot volume is being created from attacking restarts rather than open play.",
        })
    if raw.get("xT_per_pass", 0) >= 0.008:
        strengths.append({"label": "High-Value Passing", "metric": f"{raw['xT_per_pass']:.4f} xT per pass", "context": "Passing actions move the ball into more threatening zones."})
    elif raw.get("xT_per_pass", 0) <= 0.002:
        weaknesses.append({"label": "Low-Threat Passing", "metric": f"{raw['xT_per_pass']:.4f} xT per pass", "context": "Pass volume may be recycling without enough penetration."})
    return strengths[:4], weaknesses[:4]


def render_style_profile(df, team):
    st.subheader("Style Profile")
    team_df = df[df["team"].astype(str).eq(team)].copy()
    if team_df.empty:
        st.info("No team events found.")
        return

    dims, raw = compute_style_metrics(df, team)
    strengths, weaknesses = detect_strengths_weaknesses(dims, raw)
    render_metric_row([
        ("Field Tilt", _fmt_metric(raw["field_tilt_pct"], "%"), "Share of both teams' attacking-third events."),
        ("Box Entries / Match", raw["box_entries_per_match"], "Passes and carries entering the box, normalized per match."),
        ("Transition Threat", _fmt_metric(raw["transition_threat_pct"], "%"), "Recoveries leading to a shot or box entry."),
        ("Direct Passes", _fmt_metric(raw["direct_passes_pct"], "%"), "Long balls, launches and diagonals as a share of passes."),
        ("xT / Pass", _fmt_metric(raw["xT_per_pass"], decimals=4), "Mean positive xT created by passes."),
    ])

    t1, t2 = st.columns([1, 1])
    with t1:
        st.plotly_chart(_radar_chart(dims, team), use_container_width=True, config=PLOTLY_EXPORT_CONFIG, key="style_profile_radar")
        with st.expander("Radar Info", expanded=False):
            st.markdown(_radar_legend_html(raw), unsafe_allow_html=True)
    with t2:
        pass_xt_created = team_df.loc[team_df["type"].eq("Pass"), "xT"].clip(lower=0).sum()
        carry_xt_created = team_df.loc[team_df["type"].eq("Carry"), "xT"].clip(lower=0).sum()
        threat = pd.DataFrame({
            "Action": ["Passes", "Carries"],
            "xT Created": [pass_xt_created, carry_xt_created],
        })
        fig = px.pie(
            threat,
            names="Action",
            values="xT Created",
            title="Threat Created Through Passes And Carries",
            color="Action",
            color_discrete_map={"Passes": HOME_COLOR, "Carries": ACCENT},
            hole=0.45,
        )
        fig.update_traces(
            textinfo="label+percent",
            hovertemplate="%{label}<br>Share: %{percent}<br>xT Created: %{value:.3f}<extra></extra>",
            sort=False,
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(_brand_fig(fig, 420), use_container_width=True, config=PLOTLY_EXPORT_CONFIG)

    f1, f2 = st.columns([1, 1])
    with f1:
        final_third_entries = raw["ft_entries"]
        touches_att_third = _str_series(team_df, "depth_zone").eq("Attacking Third").sum()
        funnel = pd.DataFrame({
            "Stage": ["All Events", "Attacking Third", "Final Third Entries", "Box Entries", "Shots"],
            "Per Match": [
                round(len(team_df) / raw["matches_analyzed"], 1),
                round(touches_att_third / raw["matches_analyzed"], 1),
                raw["ft_entries_per_match"],
                raw["box_entries_per_match"],
                raw["shots_per_match"],
            ],
        })
        fig = px.funnel(funnel, x="Per Match", y="Stage", title="Progression Funnel Per Match")
        st.plotly_chart(_brand_fig(fig, 420), use_container_width=True, config=PLOTLY_EXPORT_CONFIG)
    with f2:
        zone = team_df.groupby(["depth_zone", "pitch_zone"]).size().reset_index(name="Events")
        all_zones = pd.MultiIndex.from_product(
            [DEPTH_ZONE_ORDER, PITCH_ZONE_ORDER],
            names=["depth_zone", "pitch_zone"],
        ).to_frame(index=False)
        zone = all_zones.merge(zone, on=["depth_zone", "pitch_zone"], how="left").fillna({"Events": 0})
        fig = px.density_heatmap(
            zone,
            x="pitch_zone",
            y="depth_zone",
            z="Events",
            histfunc="sum",
            title="Territory Heatmap",
            category_orders={
                "pitch_zone": PITCH_ZONE_ORDER,
                "depth_zone": DEPTH_ZONE_ORDER,
            },
        )
        st.plotly_chart(_brand_fig(fig, 420), use_container_width=True, config=PLOTLY_EXPORT_CONFIG)

    if "match_id" in df.columns and df["match_id"].nunique() > 1:
        trend_df = _per_match_trends(df, team, [str(x) for x in df.groupby("match_id")["match_label"].first().tolist()])
        dim_cols = [col for col in trend_df.columns if col != "Match"]
        if dim_cols:
            selected_dim = st.selectbox("Style dimension", dim_cols, key="style_trend_dim")
            fig = px.line(
                trend_df,
                x="Match",
                y=selected_dim,
                markers=True,
                title=f"{selected_dim.replace(chr(10), ' ')} Across Matches",
            )
            fig.add_hline(y=50, line_dash="dot", line_color=MUTED)
            st.plotly_chart(_brand_fig(fig, 340), use_container_width=True, config=PLOTLY_EXPORT_CONFIG, key="style_profile_trend")

    st.markdown("##### Strength Signals")
    if strengths:
        for item in strengths:
            st.success(f"{item['label']}: {item['metric']}")
    else:
        st.caption("No strength threshold is strongly flagged yet.")


def _set_piece_mask(df):
    return (
        _bool_series(df, "is_corner")
        | _bool_series(df, "is_freekick")
        | _bool_series(df, "is_throw_in")
        | _bool_series(df, "is_goal_kick")
        | _bool_series(df, "is_keeper_throw")
        | _bool_series(df, "is_gk_hoof")
        | df["type"].isin(["CornerAwarded"])
    )


def _restart_type(row):
    if str(row.get("type", "")).strip() == "CornerAwarded":
        return "Corner"
    checks = [
        ("Corner", "is_corner"),
        ("Freekick", "is_freekick"),
        ("Throw-in", "is_throw_in"),
        ("Goal kick", "is_goal_kick"),
        ("Keeper throw", "is_keeper_throw"),
        ("GK hoof", "is_gk_hoof"),
    ]
    for label, col in checks:
        value = str(row.get(col, "")).strip().lower()
        if value in {"true", "1", "yes"}:
            return label
    return str(row.get("type", "Restart"))


def render_set_pieces(df, team):
    st.subheader("Set-Piece And Restart Profile")
    df = _match_scope_df(df, "sp_match_scope")
    team_df = df[df["team"].astype(str).eq(team)].copy()
    restarts = team_df[_set_piece_mask(team_df)].copy()
    if restarts.empty:
        st.info("No restart events found for this team in the loaded data.")
        return
    restarts["restart_type"] = restarts.apply(_restart_type, axis=1)

    rows = []
    for _, restart in restarts.iterrows():
        same_match = df["match_id"].eq(restart.get("match_id")) if "match_id" in df.columns else pd.Series(True, index=df.index)
        after = df[
            same_match
            & (df["period_order"].eq(restart["period_order"]))
            & (df["event_id"] >= restart["event_id"])
            & (df["event_seconds"].sub(restart["event_seconds"]).between(0, 12))
        ].head(8)
        own = after[after["team"].astype(str).eq(team)]
        rows.append({
            "event_id": restart["event_id"],
            "restart_type": restart["restart_type"],
            "playerName": restart.get("playerName", ""),
            "minute": restart["minute"],
            "second": restart["second"],
            "period": restart.get("period", ""),
            "x": restart["x"],
            "y": restart["y"],
            "endX": restart["endX"],
            "endY": restart["endY"],
            "retained": len(own) >= 2,
            "box_entry": bool(_danger_mask(own).any()) if not own.empty else False,
            "shot": bool(own["type"].isin(SHOT_TYPES).any()) if not own.empty else False,
            "xT_created": own["xT"].clip(lower=0).sum() if not own.empty else 0.0,
        })
    profile = pd.DataFrame(rows)
    retained = profile["retained"].mean() * 100
    threat = (profile["box_entry"] | profile["shot"]).mean() * 100
    render_metric_row([
        ("Restarts", len(profile), "Corners, free kicks, throw-ins, goal kicks and goalkeeper distributions."),
        ("Retention", _fmt_metric(retained, "%"), "Team kept at least two events in the 12-second restart window."),
        ("Threat Rate", _fmt_metric(threat, "%"), "Restart led to a shot or box entry within 12 seconds."),
        ("xT / Restart", _fmt_metric(profile["xT_created"].mean(), decimals=3), "Mean positive xT generated from restart windows."),
    ])
    left, right = st.columns([1.25, 1])
    with left:
        st.plotly_chart(_arrow_pitch(profile, "Restart Delivery Map", color=ACCENT), use_container_width=True, config=PLOTLY_EXPORT_CONFIG)
    with right:
        counts = profile.groupby("restart_type").agg(
            Count=("event_id", "count"),
            Threat=("box_entry", "mean"),
            xT=("xT_created", "mean"),
        ).reset_index()
        counts["Threat"] = counts["Threat"] * 100
        fig = px.bar(counts, x="restart_type", y="Count", color="Threat", title="Restart Mix And Threat %")
        st.plotly_chart(_brand_fig(fig, 440), use_container_width=True, config=PLOTLY_EXPORT_CONFIG)
    st.markdown("##### Restart Outcomes")
    show = profile.sort_values(["shot", "box_entry", "xT_created"], ascending=False).copy()
    show["time"] = show.apply(_event_clock, axis=1)
    st.dataframe(show[["time", "restart_type", "playerName", "retained", "box_entry", "shot", "xT_created"]].head(16), hide_index=True, use_container_width=True)


_logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ClipMaker_logo.png")
_logo_b64 = theme.load_logo_b64(_logo_path)
st.markdown(
    theme.logo_header("Tactical Lab", "Team style, transition behaviour and restart analysis", _logo_b64 or None, uppercase_title=False),
    unsafe_allow_html=True,
)
st.divider()

if not _PLOTLY_AVAILABLE:
    st.error("Plotly is required for the Tactical Lab. Run the launcher so dependencies can be installed.")
    st.stop()

df_all, match_labels = _load_matches()
if df_all is None:
    st.markdown(
        f"""<div class="cm-no-data-msg">
            <div style="font-size:40px;margin-bottom:16px">{theme.icon_span("[DATA]", color=theme.light_color("#ccc", "#555"), size=40)}</div>
            <b style="font-size:17px">No match data loaded</b><br><br>
            Load or scrape a match from Home to open the Tactical Lab.
        </div>""",
        unsafe_allow_html=True,
    )
    st.stop()

teams = _team_names(df_all)
if not teams:
    st.error("No team names were found in the match data.")
    st.stop()

match_name = ", ".join(match_labels[:3])
if len(match_labels) > 3:
    match_name = f"{match_name} + {len(match_labels) - 3} more"
if not match_name and "matchName" in df_all.columns and not df_all["matchName"].dropna().empty:
    match_name = str(df_all["matchName"].dropna().iloc[0])
top_c1, top_c2 = st.columns([2.2, 1])
with top_c1:
    st.caption(f"Loaded: `{match_name}`")
with top_c2:
    team = st.selectbox("Team", teams, key="tactical_team")

tab_dt, tab_at, tab_style, tab_set, tab_video = st.tabs([
    "Defensive Transitions",
    "Attacking Transitions",
    "Style Profile",
    "Set Pieces",
    "Video Lab",
])

with tab_dt:
    render_defensive_transitions(df_all, team)
with tab_at:
    render_attacking_transitions(df_all, team)
with tab_style:
    render_style_profile(df_all, team)
with tab_set:
    render_set_pieces(df_all, team)
with tab_video:
    render_video_lab(df_all, team)
