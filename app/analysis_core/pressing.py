"""Pressing & high turnovers: map option (moved from smp_component.pressing_map) and native view."""
from __future__ import annotations

import math

from .common import map_context
from .views import as_index, badge, clip_event, segmented, selected_panel, team_options, view

ZONES = ["All", "High Press (final third)", "Mid-Block"]
PERIOD_LABEL = {"FirstHalf": "1H", "SecondHalf": "2H", "FirstPeriodOfExtraTime": "ET1", "SecondPeriodOfExtraTime": "ET2"}
NOTE = ("Subset: ball recoveries, interceptions and tackles in the selected press zone. "
        "High press is the final third; mid-block is the middle band.")


def pressing_option(press_wins, selected_idx=None, light_mode=False, context_title="", context_subtitle=""):
    """ECharts option for the full-pitch pressing map. Markers carry their event id."""
    PITCH_LENGTH = 105
    PITCH_WIDTH = 68
    half_line_x = PITCH_LENGTH * 0.50
    final_third_x = PITCH_LENGTH * 0.66
    if light_mode:
        _pitch_fill, _paper_bg, _line = "#d4e8c2", "#f0ece4", "rgba(25,61,9,0.66)"
        _sep_final, _leg_font, _marker_border = "rgba(47,93,22,0.50)", "#1f241b", "#315322"
        _high_color, _mid_color = "#2f6f18", "#7fae16"
    else:
        _pitch_fill, _paper_bg, _line = "#1a2a1a", "#111111", "rgba(220,220,220,0.42)"
        _sep_final, _leg_font, _marker_border = "rgba(200,255,0,0.60)", "#cccccc", "#ffffff"
        _high_color, _mid_color = "#c8ff00", "#6a9f00"

    def _to_px(x, y):
        return round(float(x or 0) / 100 * PITCH_LENGTH, 2), round(float(y or 0) / 100 * PITCH_WIDTH, 2)

    def _rect_points(x0, y0, x1, y1):
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]

    def _circle_points(cx, cy, r, steps=48):
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
            "lineStyle": {"color": _sep_final if i == 8 else _line, "width": 1.6 if i < 7 else 1.1,
                          "type": "dotted" if i >= 7 else "solid"},
            "z": 1,
        })
    series.append({"type": "scatter", "data": [[PITCH_LENGTH / 2, PITCH_WIDTH / 2]],
                   "symbolSize": 5, "silent": True, "itemStyle": {"color": _line}, "z": 2})

    type_icon = {"BallRecovery": "R", "Interception": "I", "Tackle": "T"}
    for zone, color, label in [("High", _high_color, "High Press"), ("Mid", _mid_color, "Mid-Block")]:
        points = []
        for w in [row for row in press_wins if row.get("press_zone") == zone]:
            px, py = _to_px(w.get("x"), w.get("y"))
            selected = w.get("idx") == selected_idx
            p = PERIOD_LABEL.get(w.get("period"), "")
            points.append({
                "name": type_icon.get(w.get("type"), "?"),
                "value": [px, py],
                "customdata": int(w.get("idx")),
                "symbolSize": 22 if selected else 16,
                "tooltip": f"<b>{w.get('playerName', '')}</b><br>{w.get('type', '')} {w.get('minute', 0)}'{int(w.get('second', 0) or 0):02d}\" {p}<br>Zone: {label}",
                "itemStyle": {
                    "color": color,
                    "borderColor": "#1f4218" if light_mode and zone == "High" else _marker_border,
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

    return {
        "cmPitchAspect": PITCH_LENGTH / PITCH_WIDTH,
        "backgroundColor": _paper_bg,
        "animationDuration": 450,
        "title": {
            "text": context_title or "Pressing Map", "subtext": context_subtitle or "", "left": 16, "top": 10,
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
            {"type": "text", "right": 34, "bottom": 14,
             "style": {"text": "VizorPlay\n@B03GHB4L1", "fill": "#2f5d16" if light_mode else "#DFFF00", "font": "700 10px monospace"},
             "silent": True},
        ],
        "series": series,
    }


def pressing_component_args(press_wins, selected_idx=None, light_mode=False,
                            context_title="", context_subtitle="", context_note=""):
    """Arguments the map component receives (the classic echarts_chart wrapper's)."""
    option = pressing_option(press_wins, selected_idx, light_mode, context_title, context_subtitle)
    return {
        "component_type": "echarts_option", "option": option,
        "height": 500 if context_title or context_note else 460,
        "context_title": context_title or "pressing_map", "context_subtitle": context_subtitle or "",
        "context_note": context_note or "", "filename_hint": "pressing_map", "light_mode": light_mode,
    }


def win_label(win):
    zone = "High press" if win["press_zone"] == "High" else "Mid-block"
    return (f"{win['type']}  {win['minute']}'{win['second']:02d}\" {PERIOD_LABEL.get(win['period'], '')}  "
            f"{win['playerName']}  ({zone})")


def build_view(frames, controls, light_mode=True):
    from clipmaker_core import detect_press_wins
    df_all = frames.df_all
    if df_all is None or df_all.empty:
        return view(empty="No match data loaded.")
    teams = team_options(df_all, frames.home_team, frames.away_team)
    team = controls.get("team") if controls.get("team") in teams else teams[0]
    zone = controls.get("zone") if controls.get("zone") in ZONES else ZONES[0]
    result = view(filters=[segmented("team", "Team", teams, team), segmented("zone", "Zone", ZONES, zone)],
                  controls={"team": team, "zone": zone, "selected": None})
    all_wins = detect_press_wins(df_all, team)
    if zone == "High Press (final third)":
        wins = [w for w in all_wins if w["press_zone"] == "High"]
    elif zone == "Mid-Block":
        wins = [w for w in all_wins if w["press_zone"] == "Mid"]
    else:
        wins = all_wins
    if not wins:
        result["empty"] = f"No pressing wins found for {team} with the current zone filter."
        return result
    high = sum(1 for w in all_wins if w["press_zone"] == "High")
    high_pct = high / len(all_wins) * 100 if all_wins else 0
    avg_x = sum(w["x"] for w in all_wins) / len(all_wins) if all_wins else 0
    result["stats"] = [
        {"label": "Press Wins", "home": len(wins) if zone == "All" else f"{len(wins)} / {len(all_wins)}"},
        {"label": "High Press %", "home": f"{high_pct:.0f}%"},
        {"label": "Avg Press Height", "home": f"{avg_x / 100 * 105:.1f}m"},
    ]
    by_id = {int(w["idx"]): w for w in wins}
    selected = as_index(controls.get("selected"), by_id)
    result["controls"]["selected"] = selected
    result["components"] = [{"role": "map", "args": pressing_component_args(
        wins, selected, light_mode, **map_context(df_all, f"Pressing Wins - {team}", team=team, subset=zone,
                                                  count=len(wins), unit="win", note=NOTE))}]
    result["legend"] = "R ball recovery · I interception · T tackle · Click a marker to inspect it"
    result["picker"] = {"label": "Select a press win", "placeholder": "— Select a press win to inspect —",
                        "items": [{"id": int(w["idx"]), "label": win_label(w)} for w in wins]}
    if selected is not None:
        win = by_id[selected]
        row = df_all.loc[selected].to_dict()
        result["selected"] = selected_panel(
            frames, selected, row, [badge("HIGH PRESS" if win["press_zone"] == "High" else "MID-BLOCK", "good")],
            [{"label": "Type", "value": win["type"]}])
    return result


clip = clip_event(build_view)
