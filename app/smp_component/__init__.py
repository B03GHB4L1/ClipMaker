import os
import streamlit.components.v1 as components

_FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

# Single component declaration — routing happens inside index.html via component_type arg
_analyst_component = components.declare_component(
    "analyst_room",
    path=_FRONTEND,
)


def penalty_shootout_map(shots, home_team, away_team, selected_idx=None, key=None,
                         light_mode=False, context_title="", context_subtitle="", context_note=""):
    return _analyst_component(
        component_type="penalty_shootout",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=820, key=key, default=None, light_mode=light_mode,
    )


def shot_map(shots, home_team, away_team, selected_idx=None,
             view="pitch", key=None, light_mode=False,
             context_title="", context_subtitle="", context_note=""):
    height_map = {
        "pitch": 460, "halfpitch": 460,
        "halfpitch_vert": 520, "goalframe": 320,
    }
    height = height_map.get(view, 460)
    return _analyst_component(
        component_type="shot_map",
        shots=shots, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, view=view,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def pass_map(passes, home_team, away_team, selected_idx=None,
             mode="player", key=None, light_mode=False,
             context_title="", context_subtitle="", context_note=""):
    height = 800 if mode == "network" else 470
    return _analyst_component(
        component_type="pass_map",
        passes=passes, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, mode=mode,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def defensive_map(actions, home_team, away_team, selected_idx=None, key=None, light_mode=False,
                  context_title="", context_subtitle="", context_note=""):
    height = 500
    return _analyst_component(
        component_type="defensive_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def dribble_carry_map(actions, home_team, away_team, selected_idx=None, key=None, light_mode=False,
                      context_title="", context_subtitle="", context_note=""):
    height = 500
    return _analyst_component(
        component_type="dribble_carry_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
    )


def build_up_map(actions, is_home, selected_idx=None, key=None, light_mode=False,
                 entry_mode="", height=520,
                 context_title="", context_subtitle="", context_note=""):
    return _analyst_component(
        component_type="build_up_map",
        actions=actions,
        is_home=bool(is_home),
        selected_idx=selected_idx,
        entry_mode=entry_mode or "",
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height,
        key=key,
        default=None,
        light_mode=light_mode,
    )


def goalkeeper_map(actions, home_team, away_team, selected_idx=None,
                   shots_faced=False, key=None, light_mode=False,
                   context_title="", context_subtitle="", context_note=""):
    height = 520
    return _analyst_component(
        component_type="goalkeeper_map",
        actions=actions, home_team=home_team or "", away_team=away_team or "",
        selected_idx=selected_idx, shots_faced=shots_faced,
        context_title=context_title or "", context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        height=height, key=key, default=None, light_mode=light_mode,
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


def echarts_chart(option, height=520, key=None, light_mode=False,
                  context_title="", context_subtitle="", context_note="",
                  filename_hint="echarts_chart"):
    return _analyst_component(
        component_type="echarts_option",
        option=option or {},
        height=int(height or 520),
        context_title=context_title or filename_hint or "",
        context_subtitle=context_subtitle or "",
        context_note=context_note or "",
        filename_hint=filename_hint or "echarts_chart",
        key=key,
        default=None,
        light_mode=light_mode,
    )


def pressing_map(press_wins, is_home_team, selected_idx=None, key=None, light_mode=False,
                 context_title="", context_subtitle="", context_note=""):
    """Render a full-pitch high-press map using ECharts."""
    PITCH_LENGTH = 105
    PITCH_WIDTH  = 68
    half_line_x = PITCH_LENGTH * 0.50
    final_third_x = PITCH_LENGTH * 0.66
    if light_mode:
        _pitch_fill = "#d4e8c2"
        _paper_bg      = "#f0ece4"
        _line          = "rgba(25,61,9,0.66)"
        _zone_mid_bg   = "rgba(80,120,40,0.08)"
        _zone_high_bg  = "rgba(47,93,22,0.12)"
        _zone_mid_ln   = "rgba(80,120,40,0.20)"
        _sep_final     = "rgba(47,93,22,0.50)"
        _leg_font      = "#1f241b"
        _marker_border = "#315322"
        _high_color    = "#2f6f18"
        _mid_color     = "#7fae16"
    else:
        _pitch_fill = "#1a2a1a"
        _paper_bg      = "#111111"
        _line          = "rgba(220,220,220,0.42)"
        _zone_mid_bg   = "rgba(106,159,0,0.12)"
        _zone_high_bg  = "rgba(200,255,0,0.11)"
        _zone_mid_ln   = "rgba(106,159,0,0.30)"
        _sep_final     = "rgba(200,255,0,0.60)"
        _leg_font      = "#cccccc"
        _marker_border = "#ffffff"
        _high_color    = "#c8ff00"
        _mid_color     = "#6a9f00"

    def _to_px(x, y):
        return round(float(x or 0) / 100 * PITCH_LENGTH, 2), round(float(y or 0) / 100 * PITCH_WIDTH, 2)

    def _rect_points(x0, y0, x1, y1):
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]

    def _circle_points(cx, cy, r, steps=48):
        import math
        return [[cx + math.cos(i / steps * math.tau) * r, cy + math.sin(i / steps * math.tau) * r] for i in range(steps + 1)]

    pitch_lines = [
        _rect_points(0, 0, PITCH_LENGTH, PITCH_WIDTH),
        [[PITCH_LENGTH / 2, 0], [PITCH_LENGTH / 2, PITCH_WIDTH]],
        _circle_points(PITCH_LENGTH / 2, PITCH_WIDTH / 2, 9.15),
        _rect_points(0, (PITCH_WIDTH - 40.32) / 2, 16.5, (PITCH_WIDTH + 40.32) / 2),
        _rect_points(PITCH_LENGTH - 16.5, (PITCH_WIDTH - 40.32) / 2, PITCH_LENGTH, (PITCH_WIDTH + 40.32) / 2),
        _rect_points(0, (PITCH_WIDTH - 18.32) / 2, 5.5, (PITCH_WIDTH + 18.32) / 2),
        _rect_points(PITCH_LENGTH - 5.5, (PITCH_WIDTH - 18.32) / 2, PITCH_LENGTH, (PITCH_WIDTH + 18.32) / 2),
        [[half_line_x, 0], [half_line_x, PITCH_WIDTH]],
        [[final_third_x, 0], [final_third_x, PITCH_WIDTH]],
    ]
    series = []
    for i, pts in enumerate(pitch_lines):
        series.append({
            "type": "line", "data": pts, "showSymbol": False, "silent": True,
            "lineStyle": {"color": _sep_final if i == 8 else _line, "width": 1.6 if i < 7 else 1.1, "type": "dotted" if i >= 7 else "solid"},
            "z": 1,
        })
    series.append({
        "type": "scatter", "data": [[PITCH_LENGTH / 2, PITCH_WIDTH / 2]],
        "symbolSize": 5, "silent": True, "itemStyle": {"color": _line}, "z": 2,
    })

    type_icon = {"BallRecovery": "R", "Interception": "I", "Tackle": "T"}
    period_label = {"FirstHalf": "1H", "SecondHalf": "2H", "FirstPeriodOfExtraTime": "ET1", "SecondPeriodOfExtraTime": "ET2"}

    for zone, color, label in [("High", _high_color, "High Press"), ("Mid", _mid_color, "Mid-Block")]:
        points = []
        for w in [row for row in press_wins if row.get("press_zone") == zone]:
            px, py = _to_px(w.get("x"), w.get("y"))
            selected = w.get("idx") == selected_idx
            p = period_label.get(w.get("period"), "")
            points.append({
                "name": type_icon.get(w.get("type"), "?"),
                "value": [px, py],
                "symbolSize": 22 if selected else 16,
                "tooltip": f"<b>{w.get('playerName', '')}</b><br>{w.get('type', '')} {w.get('minute', 0)}'{int(w.get('second', 0) or 0):02d}\" {p}<br>Zone: {label}",
                "itemStyle": {
                    "color": color,
                    "borderColor": "#1f4218" if light_mode and zone == "High" else (_marker_border if light_mode else _marker_border),
                    "borderWidth": 2.4 if selected else (1.2 if light_mode else 1.8),
                },
            })
        if points:
            series.append({
                "type": "scatter", "name": label, "data": points,
                "label": {
                    "show": True, "formatter": "{b}",
                    "color": "#ffffff" if light_mode and zone == "High" else "#111111",
                    "fontSize": 8, "fontWeight": 800,
                    "textBorderColor": "#1f2d16" if light_mode and zone == "High" else "#f8f6f0",
                    "textBorderWidth": 1.4 if light_mode else 0,
                },
                "itemStyle": {"opacity": 0.95},
                "emphasis": {"scale": 1.25},
                "z": 10,
            })

    option = {
        "cmPitchAspect": PITCH_LENGTH / PITCH_WIDTH,
        "backgroundColor": _paper_bg,
        "animationDuration": 450,
        "title": {
            "text": context_title or "Pressing Map",
            "subtext": context_subtitle or "",
            "left": 16,
            "top": 10,
            "textStyle": {"color": _leg_font, "fontSize": 18, "fontWeight": 800},
            "subtextStyle": {"color": _leg_font, "fontSize": 11},
        },
        "grid": {"left": 20, "right": 20, "top": 72 if context_title else 24, "bottom": 42, "containLabel": False},
        "xAxis": {"type": "value", "min": -2, "max": PITCH_LENGTH + 2, "show": False},
        "yAxis": {"type": "value", "min": -2, "max": PITCH_WIDTH + 2, "show": False, "inverse": True},
        "legend": {"bottom": 8, "left": "center", "textStyle": {"color": _leg_font, "fontSize": 11}},
        "tooltip": {"trigger": "item", "confine": True},
        "graphic": [
            {"type": "rect", "left": "20px", "right": "20px", "top": "72px" if context_title else "24px", "bottom": "42px",
             "cmPitchBackground": True, "style": {"fill": _pitch_fill}, "silent": True, "z": -10},
            {"type": "text", "right": 34, "bottom": 14, "style": {"text": "ClipMaker v1.2.3\n@B03GHB4L1", "fill": "#2f5d16" if light_mode else "#DFFF00", "font": "700 10px monospace"}, "silent": True},
        ],
        "series": series,
    }
    return echarts_chart(
        option,
        height=500 if context_title or context_note else 460,
        key=key,
        light_mode=light_mode,
        context_title=context_title,
        context_subtitle=context_subtitle,
        context_note=context_note,
        filename_hint="pressing_map",
    )
