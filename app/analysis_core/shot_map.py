"""Shot Map: data rules shared by the classic tab and the native workspace."""
from __future__ import annotations

from .common import (
    AWAY_COLOR, HOME_COLOR, OUTCOME_ICON, OUTCOME_LABEL, PITCH_ZONE_OPTIONS,
    filter_by_pitch_zone, map_context, reclassify_shot, safe_bool, safe_float, scope_line,
)
from .views import (
    as_index, badge, choice, picker, pitch_zone_filter, segmented, select, selected_panel, view,
    clip_event as views_clip_event,
)

SHOT_PLACEHOLDER = "— Select a shot to inspect —"
PENALTY_PLACEHOLDER = "— Select a penalty to inspect —"
ON_TARGET = {"SavedShot", "Goal", "ShotOnPost"}

SHOT_QUALIFIERS = [
    ("is_header", "Header"), ("is_big_chance_shot", "Big Chance"), ("is_penalty", "Penalty"),
    ("is_volley", "Volley"), ("is_chipped", "Chipped"), ("is_direct_from_corner", "Direct from Corner"),
    ("is_left_foot", "Left Foot"), ("is_right_foot", "Right Foot"), ("is_fast_break", "Fast Break"),
    ("is_scramble", "Scramble"), ("is_corner_situation", "2nd Phase"), ("is_individual_play", "Solo"),
    ("is_follows_dribble", "After Dribble"), ("is_shot_strong", "Strong"), ("is_shot_weak", "Weak"),
    ("is_hit_woodwork", "Woodwork"),
]
PENALTY_QUALIFIERS = [("is_penalty", "Penalty"), ("is_left_foot", "Left Foot"), ("is_right_foot", "Right Foot")]

NORMAL_NOTE = ("Subset: shots after the selected team/player/pitch-zone filters. "
               "The half-pitch view points toward the attacking goal.")
GOALFRAME_NOTE = "Goal-mouth placement for the selected shot. Posts and crossbar are shown for export context."
XG_LABEL = "VizorPlay xG"
XG_NOTE = ("VizorPlay xG: the chance each shot is scored, from where and how it was taken. Fitted on "
           "StatsBomb open data (Data: StatsBomb); defender positions are not in the data. "
           "Own goals count as goals with no xG.")
PENALTY_NOTE = ("Subset: penalty shootout attempts only. Goalframe shows selected placement; "
                "player circles are ordered chronologically by team.")


def shot_to_dict(idx, row, home_team):
    return {
        "df_idx": int(idx), "is_home": bool(row.get("team", "") == home_team),
        "team": str(row.get("team", "")), "playerName": str(row.get("playerName", "")),
        "minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
        "period": str(row.get("period", "")), "type": reclassify_shot(row),
        "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
        "goal_mouth_y": safe_float(row.get("goal_mouth_y")),
        "goal_mouth_z": safe_float(row.get("goal_mouth_z")),
        "xG": shot_xg(row),
    }


def shot_xg(row):
    """The shot's VizorPlay xG, or None (own goals, shoot-out kicks, no location)."""
    value = safe_float(row.get("xG"))
    return None if value is None or value != value else round(value, 2)


def xg_text(value):
    return "—" if value is None else f"{value:.2f}"


def shot_label(row):
    icon = OUTCOME_ICON.get(reclassify_shot(row), "✕")
    period = row.get("period", "")
    et = " ET" if "ExtraTime" in str(period) else ""
    xg = shot_xg(row)
    xg_part = f"  · xG {xg:.2f}" if xg is not None else ""
    return (f"{icon}  {row.get('minute', 0)}'{int(row.get('second', 0)):02d}\"{et}  "
            f"{row.get('playerName', 'Unknown')}  ({row.get('team', '')}){xg_part}")


def qualifiers(row, table=SHOT_QUALIFIERS):
    return [label for column, label in table if safe_bool(row.get(column, ""))]


def shot_stats(shots_df, home_team, away_team):
    """Counts behind the Shot Map stats bar."""
    def side(team):
        frame = shots_df[shots_df["team"] == team] if team else shots_df.iloc[0:0]
        xg = frame["xG"].sum() if "xG" in frame else 0.0
        return {"shots": int(len(frame)), "on_target": int(frame["type"].isin(ON_TARGET).sum()),
                "goals": int((frame["type"] == "Goal").sum()), "xg": round(float(xg), 2)}
    home, away = side(home_team), side(away_team)
    total = home["shots"] + away["shots"]
    share = None
    if total > 0:
        home_share = round(home["shots"] / total * 100)
        share = {"home": home_share, "away": 100 - home_share}
    return {"home": home, "away": away, "share": share}


def team_options(shots_df, home_team, away_team):
    options = [team for team in (home_team, away_team) if team]
    return options or sorted(shots_df["team"].dropna().unique().tolist())[:2]


def team_players(shots_df, team):
    all_players = sorted(shots_df["playerName"].dropna().unique()) if "playerName" in shots_df.columns else []
    return [player for player in all_players if player in shots_df[shots_df["team"] == team]["playerName"].values]


def filtered_shots(shots_df, team, player, zone):
    shots = shots_df[shots_df["team"] == team].copy()
    if player != "All players":
        shots = shots[shots["playerName"] == player]
    return filter_by_pitch_zone(shots, zone)


def pitch_map_args(frames, shots, team, player, zone, selected_idx, light_mode):
    return {
        "component_type": "shot_map",
        "shots": [shot_to_dict(idx, row, frames.home_team) for idx, row in shots.iterrows()],
        "home_team": frames.home_team or "", "away_team": frames.away_team or "",
        "selected_idx": selected_idx, "view": "halfpitch_vert",
        **map_context(frames.df_all, f"Shot Map - {team if player == 'All players' else player}",
                      team=team, player="" if player == "All players" else player, subset="Shots",
                      pitch_zone=zone, count=len(shots), unit="shot", note=NORMAL_NOTE),
        "height": 520, "light_mode": light_mode,
    }


def goalframe_args(frames, idx, row, light_mode):
    return {
        "component_type": "shot_map",
        "shots": [shot_to_dict(idx, row, frames.home_team)],
        "home_team": frames.home_team or "", "away_team": frames.away_team or "",
        "selected_idx": idx, "view": "goalframe",
        **map_context(frames.df_all, f"Shot Placement - {row.get('playerName', 'Unknown')}",
                      team=row.get("team", ""), subset=reclassify_shot(row), count=1, unit="shot",
                      note=GOALFRAME_NOTE),
        "height": 320, "light_mode": light_mode,
    }


def penalty_map_args(frames, selected_idx, light_mode):
    shots = frames.pso_shots_df
    return {
        "component_type": "penalty_shootout",
        "shots": [shot_to_dict(idx, row, frames.home_team) for idx, row in shots.iterrows()],
        "home_team": frames.home_team or "", "away_team": frames.away_team or "",
        "selected_idx": selected_idx,
        **map_context(frames.df_all, "Penalty Shootout Map",
                      team=scope_line(frames.home_team, frames.away_team),
                      subset="Penalty shootout attempts", count=len(shots), unit="penalty", note=PENALTY_NOTE),
        "height": 820, "light_mode": light_mode,
    }


def shot_detail(frames, idx, row, penalty=False):
    s_type = reclassify_shot(row)
    return selected_panel(
        frames, idx, row,
        badges=[badge(OUTCOME_LABEL.get(s_type, "[ERR] MISSED"), "good" if s_type == "Goal" else
                      "info" if s_type in {"SavedShot", "ShotOnPost"} else "bad")],
        fields=[{"label": "Qualifier",
                 "value": " · ".join(qualifiers(row, PENALTY_QUALIFIERS if penalty else SHOT_QUALIFIERS)) or "—"}]
        + ([] if penalty else [{"label": XG_LABEL, "value": xg_text(shot_xg(row))}]),
    )


def match_clock(row):
    """Match minute as a number (WhoScored minutes already run on through each half)."""
    minute = safe_float(row.get("minute")) or 0.0
    second = safe_float(row.get("second")) or 0.0
    return minute + second / 60


def xg_race_option(shots_df, home_team, away_team, selected_idx=None, light_mode=False, title="", subtitle=""):
    """ECharts option: each team's running xG total through the match, a step at every shot.
    Markers carry the shot's row id so clicking one selects that shot."""
    ink = "#1f241b" if light_mode else "#cccccc"
    grid_line = "rgba(31,36,27,0.12)" if light_mode else "rgba(220,220,220,0.12)"
    half_line = "rgba(31,36,27,0.45)" if light_mode else "rgba(220,220,220,0.45)"
    colors = {home_team: "#1f6fd1" if light_mode else HOME_COLOR, away_team: "#d1462b" if light_mode else AWAY_COLOR}
    frame = shots_df.copy()
    frame["_clock"] = [match_clock(row) for _, row in frame.iterrows()]
    frame = frame.sort_values("_clock", kind="stable")
    end = max(90.0, float(frame["_clock"].max() if len(frame) else 90.0) + 1)
    series, top = [], 0.5
    for team in (home_team, away_team):
        own = frame[frame["team"] == team]
        total, line, marks = 0.0, [[0, 0]], []
        for idx, row in own.iterrows():
            xg = safe_float(row.get("xG"))
            xg = None if xg is None or xg != xg else xg  # unrounded, so totals match the stats bar
            goal = row.get("type") == "Goal"
            if xg is None and not goal:
                continue
            clock = round(float(row["_clock"]), 2)
            line.append([clock, round(total, 3)])
            total += xg or 0.0
            line.append([clock, round(total, 3)])
            selected = selected_idx is not None and int(idx) == int(selected_idx)
            marks.append({
                "value": [clock, round(total, 3)], "customdata": int(idx),
                "symbol": "circle" if goal else "emptyCircle",
                "symbolSize": (16 if goal else 7) + (6 if selected else 0),
                "itemStyle": {"color": colors[team], "borderColor": ink if goal else colors[team],
                              "borderWidth": 2 if goal or selected else 1.2},
                "tooltip": (f"<b>{row.get('playerName', '')}</b> ({team})<br>{int(row.get('minute', 0))}'"
                            f"{int(row.get('second', 0) or 0):02d}\" · {reclassify_shot(row)}<br>"
                            f"xG {xg_text(xg)}{' (own goal)' if xg is None else ''} · running total {total:.2f}"),
            })
        line.append([round(end, 2), round(total, 3)])
        top = max(top, total)
        name = f"{team}  {total:.2f} xG"
        series.append({"type": "line", "name": name, "data": line, "showSymbol": False, "silent": True,
                       "lineStyle": {"color": colors[team], "width": 2.6}, "itemStyle": {"color": colors[team]},
                       "areaStyle": {"color": colors[team], "opacity": 0.08}, "z": 2})
        series.append({"type": "scatter", "name": name, "data": marks, "z": 5, "emphasis": {"scale": 1.3}})
    series.append({"type": "line", "data": [], "silent": True, "markLine": {
        "symbol": "none", "silent": True, "label": {"formatter": "HT", "color": ink, "fontSize": 10},
        "lineStyle": {"color": half_line, "type": "dashed"}, "data": [{"xAxis": 45}]}})
    return {
        "backgroundColor": "#f0ece4" if light_mode else "#111111",
        "animationDuration": 450,
        "title": {"text": title or "xG Race", "subtext": subtitle, "left": 16, "top": 10,
                  "textStyle": {"color": ink, "fontSize": 18, "fontWeight": 800},
                  "subtextStyle": {"color": ink, "fontSize": 11}},
        "grid": {"left": 52, "right": 24, "top": 96, "bottom": 58},
        "legend": {"top": 64, "left": 16, "textStyle": {"color": ink, "fontSize": 12}, "itemWidth": 18},
        "xAxis": {"type": "value", "min": 0, "max": round(end), "interval": 15, "name": "Minute",
                  "nameLocation": "middle", "nameGap": 26, "nameTextStyle": {"color": ink},
                  "axisLabel": {"color": ink, "formatter": "{value}'"}, "axisLine": {"lineStyle": {"color": ink}},
                  "splitLine": {"lineStyle": {"color": grid_line}}},
        "yAxis": {"type": "value", "min": 0, "max": round(max(top * 1.15, top + 0.2), 1),
                  "axisLabel": {"color": ink},
                  "splitLine": {"lineStyle": {"color": grid_line}}},
        "graphic": [{"type": "text", "right": 24, "bottom": 10,
                     "style": {"text": "VizorPlay\n@B03GHB4L1", "fill": "#2f5d16" if light_mode else "#DFFF00",
                               "font": "700 10px monospace"}, "silent": True}],
        "series": series,
    }


def xg_race_args(frames, selected_idx, light_mode):
    context = map_context(frames.df_all, "xG Race", team=scope_line(frames.home_team, frames.away_team),
                          subset="All shots, both teams", count=len(frames.shots_df), unit="shot", note=XG_NOTE)
    return {
        "component_type": "echarts_option",
        "option": xg_race_option(frames.shots_df, frames.home_team, frames.away_team, selected_idx, light_mode,
                                 context["context_title"], context["context_subtitle"]),
        "height": 380, "filename_hint": "xg_race", "light_mode": light_mode, **context,
    }


MODES = {"Normal": "normal", "Penalty Shootout": "penalties"}


def build_view(frames, controls, light_mode=True):
    """Everything the native Shot Map tab shows for the given controls."""
    controls = controls if isinstance(controls, dict) else {}
    shots_df = frames.shots_df
    if shots_df is None or shots_df.empty:
        return view(empty="No shot data found in the loaded CSV.")
    has_pso = frames.pso_shots_df is not None and not frames.pso_shots_df.empty
    mode = "penalties" if has_pso and controls.get("mode") == "penalties" else "normal"
    filters = [{"key": "mode", "label": "Mode", "type": "segmented", "value": mode,
                "options": [{"value": value, "label": label} for label, value in MODES.items()]}] if has_pso else []

    if mode == "penalties":
        shots = frames.pso_shots_df
        selected = as_index(controls.get("selected"), shots.index)
        return view(
            filters=filters, controls={"mode": mode, "selected": selected},
            components=[{"role": "map", "args": penalty_map_args(frames, selected, light_mode)}],
            legend="● Scored  ◯ Saved / Post  ✕ Missed · Click a player circle to inspect their penalty",
            picker=picker("Select a penalty", PENALTY_PLACEHOLDER, shots, shot_label),
            selected=shot_detail(frames, selected, shots.loc[selected].to_dict(), penalty=True)
            if selected is not None else None,
        )

    teams = team_options(shots_df, frames.home_team, frames.away_team)
    team = choice(controls.get("team"), teams)
    players = ["All players"] + team_players(shots_df, team)
    player = choice(controls.get("player"), players)
    zone = choice(controls.get("zone"), PITCH_ZONE_OPTIONS)
    # A shot picked on the xG race may be outside the map's filters: show it.
    picked = as_index(controls.get("selected"), shots_df.index)
    if picked is not None and picked not in filtered_shots(shots_df, team, player, zone).index:
        team = choice(shots_df.at[picked, "team"], teams)
        players = ["All players"] + team_players(shots_df, team)
        player, zone = "All players", PITCH_ZONE_OPTIONS[0]
    filters += [segmented("team", "Team", teams, team), select("player", "Player", players, player),
                pitch_zone_filter(zone)]
    stats = shot_stats(shots_df, frames.home_team, frames.away_team)
    result = view(
        filters=filters, share=stats["share"],
        stats=[{"label": "Shots", "home": stats["home"]["shots"], "away": stats["away"]["shots"]},
               {"label": "On target", "home": stats["home"]["on_target"], "away": stats["away"]["on_target"]},
               {"label": "Goals", "home": stats["home"]["goals"], "away": stats["away"]["goals"]},
               {"label": "xG", "home": f"{stats['home']['xg']:.2f}", "away": f"{stats['away']['xg']:.2f}"}],
    )
    shots = filtered_shots(shots_df, team, player, zone)
    selected = as_index(controls.get("selected"), shots.index)
    result["controls"] = {"mode": mode, "team": team, "player": player, "zone": zone, "selected": selected}
    if shots.empty:
        result["empty"] = "No shots match the current filter."
        return result
    components = []
    if selected is not None:
        components.append({"role": "aux", "args": goalframe_args(frames, selected, shots.loc[selected], light_mode)})
    components.append({"role": "map", "args": pitch_map_args(frames, shots, team, player, zone, selected, light_mode)})
    components.append({"role": "map", "args": xg_race_args(frames, selected, light_mode)})
    result.update(
        components=components,
        legend="● Goal  ◯ Saved / Post  ✕ Missed · Bigger marker = higher xG · Click a shot to inspect it",
        picker=picker("Select a shot", SHOT_PLACEHOLDER, shots, shot_label),
        selected=shot_detail(frames, selected, shots_df.loc[selected].to_dict()) if selected is not None else None,
    )
    return result


clip_event = views_clip_event(build_view)
