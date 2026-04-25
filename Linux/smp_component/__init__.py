import os
import streamlit.components.v1 as components

_FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

# Single component declaration — routing happens inside index.html via component_type arg
_analyst_component = components.declare_component(
    "analyst_room",
    path=_FRONTEND,
)


def penalty_shootout_map(shots, home_team, away_team, selected_idx=None, key=None):
    """
    Penalty shootout view: goalframe centre, home circles left, away circles right.
    Clicking a player circle returns [df_idx, timestamp].
    """
    return _analyst_component(
        component_type="penalty_shootout",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        height=820, key=key, default=None,
    )


def shot_map(shots, home_team, away_team, selected_idx=None,
             view="pitch", key=None):
    height_map = {
        "pitch": 460, "halfpitch": 460,
        "halfpitch_vert": 520, "goalframe": 320,
    }
    height = height_map.get(view, 460)
    return _analyst_component(
        component_type="shot_map",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, view=view,
        height=height, key=key, default=None,
    )


def pass_map(passes, home_team, away_team, selected_idx=None,
             mode="player", key=None):
    height = 800 if mode == "network" else 470
    return _analyst_component(
        component_type="pass_map",
        passes=passes, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, mode=mode,
        height=height, key=key, default=None,
    )


def defensive_map(actions, home_team, away_team, selected_idx=None, key=None):
    height = 500
    return _analyst_component(
        component_type="defensive_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        height=height, key=key, default=None,
    )


def dribble_carry_map(actions, home_team, away_team, selected_idx=None, key=None):
    height = 500
    return _analyst_component(
        component_type="dribble_carry_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        height=height, key=key, default=None,
    )


def build_up_map(actions, is_home, key=None):
    return _analyst_component(
        component_type="build_up_map",
        actions=actions,
        is_home=bool(is_home),
        height=260,
        key=key,
        default=None,
    )


def goalkeeper_map(actions, home_team, away_team, selected_idx=None,
                   shots_faced=False, key=None):
    height = 520
    return _analyst_component(
        component_type="goalkeeper_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, shots_faced=shots_faced,
        height=height, key=key, default=None,
    )


def roi_selector(frame_b64, frame_w, frame_h, existing_roi=None, key=None):
    """
    Interactive ROI selector — displays a video frame as a canvas the user can
    click-and-drag on to draw a rectangle.  Returns {x, y, w, h} in image-pixel
    coordinates when the user finishes drawing, or None if no draw has happened yet.
    """
    est_h = min(600, max(280, int(frame_h * 640 / max(frame_w, 1)) + 50))
    return _analyst_component(
        component_type="roi_selector",
        frame_b64=frame_b64,
        frame_w=frame_w,
        frame_h=frame_h,
        existing_roi=existing_roi or {},
        height=est_h,
        key=key,
        default=None,
    )


def timeline_window(
    current_window_seconds,
    selected_before_seconds=0,
    selected_after_seconds=0,
    before_limit_seconds=180,
    after_limit_seconds=180,
    key=None,
):
    return _analyst_component(
        component_type="timeline_window",
        current_window_seconds=int(current_window_seconds or 0),
        selected_before_seconds=int(selected_before_seconds or 0),
        selected_after_seconds=int(selected_after_seconds or 0),
        before_limit_seconds=int(before_limit_seconds or 0),
        after_limit_seconds=int(after_limit_seconds or 0),
        height=170,
        key=key,
        default=None,
    )


def pressing_map(press_wins, is_home_team, selected_idx=None, key=None):
    """
    Render a full-pitch scatter of high-press wins using Plotly.
    press_wins: list of dicts from detect_press_wins, each with x, y, type,
                playerName, minute, second, period, press_zone, idx.
    Colour coding: High press (x>66) = bright accent, Mid-block (50<x<=66) = muted.
    Returns a Plotly figure rendered via st.plotly_chart.
    """
    import streamlit as st
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("Plotly not installed — pressing map unavailable.")
        return

    # Pitch dimensions (WhoScored 0-100 scale mapped to visual 105x68)
    PITCH_LENGTH = 105
    PITCH_WIDTH  = 68
    PLOTLY_EXPORT_CONFIG = {
        "displayModeBar": True,
        "displaylogo": False,
        "toImageButtonOptions": {
            "format": "png",
            "filename": "clipmaker_plot",
            "scale": 2,
        },
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    }

    def _to_px(x, y):
        """Convert WhoScored 0-100 coordinates to pitch coordinates."""
        px = x / 100 * PITCH_LENGTH
        py = y / 100 * PITCH_WIDTH
        return round(px, 2), round(py, 2)

    # Separate wins by zone
    high_wins = [w for w in press_wins if w["press_zone"] == "High"]
    mid_wins  = [w for w in press_wins if w["press_zone"] == "Mid"]

    TYPE_ICON = {
        "BallRecovery": "R",
        "Interception": "I",
        "Tackle":       "T",
    }
    PERIOD_LABEL = {
        "FirstHalf": "1H", "SecondHalf": "2H",
        "FirstPeriodOfExtraTime": "ET1", "SecondPeriodOfExtraTime": "ET2",
    }

    def _hover(w):
        p = PERIOD_LABEL.get(w["period"], "")
        return (
            f"<b>{w['playerName']}</b><br>"
            f"{w['type']}  {w['minute']}'{w['second']:02d}\" {p}<br>"
            f"Zone: {w['press_zone']} Press"
        )

    def _marker_size(w):
        return 18 if w.get("idx") == selected_idx else 13

    fig = go.Figure()
    half_line_x = PITCH_LENGTH * 0.50
    final_third_x = PITCH_LENGTH * 0.66

    # ── Pitch markings ──────────────────────────────────────────────────────
    _line = dict(color="#555555", width=1.5)
    # Outer boundary
    fig.add_shape(type="rect", x0=0, y0=0, x1=PITCH_LENGTH, y1=PITCH_WIDTH,
                  line=_line, fillcolor="#1a2a1a", layer="below")
    # Halfway line
    fig.add_shape(type="line", x0=PITCH_LENGTH/2, y0=0, x1=PITCH_LENGTH/2, y1=PITCH_WIDTH, line=_line, layer="below")
    # Centre circle (approx radius 9.15m)
    fig.add_shape(type="circle",
                  x0=PITCH_LENGTH/2-9.15, y0=PITCH_WIDTH/2-9.15,
                  x1=PITCH_LENGTH/2+9.15, y1=PITCH_WIDTH/2+9.15,
                  line=_line, layer="below")
    # Centre spot
    fig.add_trace(go.Scatter(x=[PITCH_LENGTH/2], y=[PITCH_WIDTH/2],
                             mode="markers",
                             marker=dict(color="#555555", size=4),
                             showlegend=False, hoverinfo="skip"))
    # Penalty areas (attacking = right side when is_home_team=True)
    for side in ("left", "right"):
        x0 = 0 if side == "left" else PITCH_LENGTH - 16.5
        x1 = 16.5 if side == "left" else PITCH_LENGTH
        fig.add_shape(type="rect", x0=x0, y0=(PITCH_WIDTH-40.32)/2,
                      x1=x1, y1=(PITCH_WIDTH+40.32)/2, line=_line, layer="below")
        # 6-yard box
        x0b = 0 if side == "left" else PITCH_LENGTH - 5.5
        x1b = 5.5 if side == "left" else PITCH_LENGTH
        fig.add_shape(type="rect", x0=x0b, y0=(PITCH_WIDTH-18.32)/2,
                      x1=x1b, y1=(PITCH_WIDTH+18.32)/2, line=_line, layer="below")

    fig.add_shape(
        type="rect",
        x0=half_line_x,
        y0=0,
        x1=final_third_x,
        y1=PITCH_WIDTH,
        fillcolor="rgba(106,159,0,0.12)",
        line=dict(color="rgba(106,159,0,0.28)", width=1),
        layer="below",
    )
    fig.add_shape(
        type="rect",
        x0=final_third_x,
        y0=0,
        x1=PITCH_LENGTH,
        y1=PITCH_WIDTH,
        fillcolor="rgba(200,255,0,0.10)",
        line=dict(color="rgba(200,255,0,0.35)", width=1),
        layer="below",
    )
    fig.add_shape(
        type="line",
        x0=half_line_x,
        y0=0,
        x1=half_line_x,
        y1=PITCH_WIDTH,
        line=dict(color="rgba(255,255,255,0.18)", width=1, dash="dot"),
        layer="below",
    )
    fig.add_shape(
        type="line",
        x0=final_third_x,
        y0=0,
        x1=final_third_x,
        y1=PITCH_WIDTH,
        line=dict(color="rgba(200,255,0,0.55)", width=1, dash="dot"),
        layer="below",
    )
    fig.add_annotation(
        x=(half_line_x + final_third_x) / 2,
        y=PITCH_WIDTH - 3,
        text="Mid-Block",
        showarrow=False,
        font=dict(color="#94b65b", size=11),
        bgcolor="rgba(0,0,0,0.28)",
    )
    fig.add_annotation(
        x=(final_third_x + PITCH_LENGTH) / 2,
        y=PITCH_WIDTH - 3,
        text="High Press / Final Third",
        showarrow=False,
        font=dict(color="#d8ff6a", size=11),
        bgcolor="rgba(0,0,0,0.28)",
    )

    # ── Press win scatter traces ────────────────────────────────────────────
    for zone_wins, colour, label in [
        (high_wins, "#c8ff00", "High Press"),
        (mid_wins,  "#6a9f00", "Mid-Block"),
    ]:
        if not zone_wins:
            continue
        xs, ys, texts, hovers, idxs, sizes, borders = [], [], [], [], [], [], []
        for w in zone_wins:
            px, py = _to_px(w["x"], w["y"])
            xs.append(px)
            ys.append(py)
            texts.append(TYPE_ICON.get(w["type"], "?"))
            hovers.append(_hover(w))
            idxs.append(w["idx"])
            is_selected = w.get("idx") == selected_idx
            sizes.append(20 if is_selected else _marker_size(w))
            borders.append(3 if is_selected else 1)
        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="markers+text",
            marker=dict(
                color=colour, size=sizes,
                line=dict(color="white", width=borders),
                symbol="circle",
                opacity=0.95,
            ),
            text=texts,
            textfont=dict(color="#000000", size=8, family="monospace"),
            textposition="middle center",
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
            customdata=idxs,
            name=label,
        ))

    fig.update_layout(
        plot_bgcolor="#1a2a1a",
        paper_bgcolor="#111111",
        margin=dict(l=5, r=5, t=5, b=5),
        xaxis=dict(range=[-2, PITCH_LENGTH+2], showgrid=False, zeroline=False,
                   showticklabels=False, fixedrange=True),
        yaxis=dict(range=[-2, PITCH_WIDTH+2], showgrid=False, zeroline=False,
                   showticklabels=False, scaleanchor="x", scaleratio=1, fixedrange=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    font=dict(color="#cccccc", size=11)),
        height=440,
        annotations=list(fig.layout.annotations) + [
            dict(
                x=PITCH_LENGTH,
                y=-2,
                text="Opponent goal -> higher press height",
                showarrow=False,
                xanchor="right",
                font=dict(color="#8a8a8a", size=10),
            ),
            dict(
                text="ClipMaker v1.2.1<br>@B03GHB4L1",
                xref="paper",
                yref="paper",
                x=0.995,
                y=0.015,
                xanchor="right",
                yanchor="bottom",
                showarrow=False,
                align="right",
                font=dict(size=10, color="#DFFF00", family="monospace"),
            ),
        ],
    )

    st.plotly_chart(fig, use_container_width=True, key=key, config=PLOTLY_EXPORT_CONFIG,
                    selection_mode="points", on_select="rerun")
