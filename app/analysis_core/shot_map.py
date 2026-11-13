"""Shot Map: data rules shared by the classic tab and the native workspace."""
from __future__ import annotations

from .common import (
    OUTCOME_ICON, OUTCOME_LABEL, PITCH_ZONE_OPTIONS,
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
    }


def shot_label(row):
    icon = OUTCOME_ICON.get(reclassify_shot(row), "✕")
    period = row.get("period", "")
    et = " ET" if "ExtraTime" in str(period) else ""
    return f"{icon}  {row.get('minute', 0)}'{int(row.get('second', 0)):02d}\"{et}  {row.get('playerName', 'Unknown')}  ({row.get('team', '')})"


def qualifiers(row, table=SHOT_QUALIFIERS):
    return [label for column, label in table if safe_bool(row.get(column, ""))]


def shot_stats(shots_df, home_team, away_team):
    """Counts behind the Shot Map stats bar."""
    def side(team):
        frame = shots_df[shots_df["team"] == team] if team else shots_df.iloc[0:0]
        return {"shots": int(len(frame)), "on_target": int(frame["type"].isin(ON_TARGET).sum()),
                "goals": int((frame["type"] == "Goal").sum())}
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
                 "value": " · ".join(qualifiers(row, PENALTY_QUALIFIERS if penalty else SHOT_QUALIFIERS)) or "—"}],
    )


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
    filters += [segmented("team", "Team", teams, team), select("player", "Player", players, player),
                pitch_zone_filter(zone)]
    stats = shot_stats(shots_df, frames.home_team, frames.away_team)
    result = view(
        filters=filters, share=stats["share"],
        stats=[{"label": "Shots", "home": stats["home"]["shots"], "away": stats["away"]["shots"]},
               {"label": "On target", "home": stats["home"]["on_target"], "away": stats["away"]["on_target"]},
               {"label": "Goals", "home": stats["home"]["goals"], "away": stats["away"]["goals"]}],
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
    result.update(
        components=components,
        legend="● Goal  ◯ Saved / Post  ✕ Missed · Click a shot to inspect it",
        picker=picker("Select a shot", SHOT_PLACEHOLDER, shots, shot_label),
        selected=shot_detail(frames, selected, shots_df.loc[selected].to_dict()) if selected is not None else None,
    )
    return result


clip_event = views_clip_event(build_view)
