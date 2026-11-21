"""Pass Map, Defensive Actions, Dribbles & Carries and Goalkeeper native views.

Ported from the classic Analyst Room tabs; tests/test_analyst_native.py checks
each against the recorded classic snapshot.
"""
from __future__ import annotations

import pandas as pd

from .common import (
    PITCH_ZONE_OPTIONS, filter_by_pitch_zone, map_context, reclassify_shot, safe_bool, safe_float, scope_line,
)
from .shot_map import shot_to_dict
from .views import (
    DEPTH_ZONE_OPTIONS, as_index, badge, choice, clip_event, depth_zone_filter, picker, pitch_zone_filter,
    segmented, select, selected_panel, team_options, view,
)

PLAYER_PROMPT = "— Select a player —"
ACTION_PLACEHOLDER = "— Select an action to inspect —"


def _depth(frame, depth):
    if depth and "depth_zone" in frame.columns:
        return frame[frame["depth_zone"] == depth]
    return frame


def _players(frame):
    return sorted(frame["playerName"].dropna().unique().tolist()) if "playerName" in frame.columns else []


def _clock(row):
    return f"{row.get('minute', 0)}'{int(row.get('second', 0)):02d}\""


def _component(component_type, height, frames, light_mode, **args):
    return {"component_type": component_type, "home_team": frames.home_team or "",
            "away_team": frames.away_team or "", **args, "height": height, "light_mode": light_mode}


def _type_counts(frame, types):
    counts = frame["type"].value_counts()
    return [{"label": t, "home": int(counts.get(t, 0))} for t in types if counts.get(t, 0) > 0]


# ── Pass Map ────────────────────────────────────────────────────────────────

PASS_NETWORK = "Pass Network"
PASS_TYPES = {
    "Key passes": "is_key_pass", "Crosses": "is_cross", "Long balls": "is_long_ball",
    "Switches of play": "is_switch_of_play", "Diagonals": "is_diagonal_long_ball",
    "Through balls": "is_through_ball", "Deep completions": "is_deep_completion",
    "Box entry passes": "is_box_entry_pass", "Final 3rd entries": "is_final_third_entry_pass",
    "Big chances created": "is_big_chance", "Assist (thru ball)": "is_assist_throughball",
    "Assist (cross)": "is_assist_cross", "Assist (corner)": "is_assist_corner",
    "Assist (free kick)": "is_assist_freekick", "Touch in box": "is_touch_in_box",
    "Goal kicks": "is_goal_kick", "Keeper throws": "is_keeper_throw", "Pull backs": "is_pull_back",
    "Lay-offs": "is_lay_off", "Flick-ons": "is_flick_on", "Assists": "is_assist", "Throw ins": "is_throw_in",
}
PASS_FLAGS = ["is_key_pass", "is_cross", "is_long_ball", "is_switch_of_play", "is_diagonal_long_ball",
              "is_through_ball", "is_big_chance", "is_assist_throughball", "is_assist_cross", "is_assist_corner",
              "is_assist_freekick", "is_intentional_assist", "is_fast_break", "is_touch_in_box"]
PASS_TAGS = [("is_key_pass", "Key Pass"), ("is_cross", "Cross"), ("is_long_ball", "Long Ball"),
             ("is_switch_of_play", "Switch of Play"), ("is_diagonal_long_ball", "Diagonal"),
             ("is_through_ball", "Through Ball"), ("is_big_chance", "Big Chance Created"),
             ("is_assist_throughball", "Assist (Through Ball)"), ("is_assist_cross", "Assist (Cross)"),
             ("is_assist_corner", "Assist (Corner)"), ("is_assist_freekick", "Assist (Free Kick)"),
             ("is_intentional_assist", "Intentional Assist"), ("is_fast_break", "Fast Break"),
             ("is_touch_in_box", "Touch in Box")]


def pass_label(row):
    outcome = "✓" if str(row.get("outcomeType", "")).lower() == "successful" else "✕"
    kp = " ◆" if safe_bool(row.get("is_key_pass", False)) else ""
    return f"{outcome}{kp}  {_clock(row)}  {row.get('playerName', 'Unknown')}"


def _pass_accuracy(frame):
    if frame.empty:
        return "—"
    successful = len(frame[frame["outcomeType"] == "Successful"]) if "outcomeType" in frame.columns else 0
    return f"{round(successful / len(frame) * 100)}%"


def _key_passes(frame):
    return int(frame["is_key_pass"].sum()) if "is_key_pass" in frame.columns else 0


def build_pass_view(frames, controls, light_mode=True):
    passes_df = frames.passes_df
    if passes_df is None or passes_df.empty:
        return view(empty="No pass data found in the loaded CSV.")
    home, away = frames.home_team, frames.away_team
    views = [PASS_NETWORK] + [team for team in (home, away) if team]
    selected_view = choice(controls.get("view"), views)
    filters = [segmented("view", "View", views, selected_view)]

    if selected_view == PASS_NETWORK:
        subs_on = set()
        df_all = frames.df_all
        if df_all is not None and "type" in df_all.columns:
            subs_on = set(df_all[df_all["type"].isin({"SubstitutionOn", "PlayerOn"})]["playerName"].dropna().unique())
        network = []
        for idx, row in passes_df.iterrows():
            if pd.isna(safe_float(row.get("x"))) or pd.isna(safe_float(row.get("endX"))):
                continue
            name = str(row.get("playerName", ""))
            network.append({
                "df_idx": int(idx), "playerName": name, "team": str(row.get("team", "")),
                "is_home": bool(row.get("team", "") == home), "is_starter": name not in subs_on,
                "minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
                "period": str(row.get("period", "")), "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
                "endX": safe_float(row.get("endX")), "endY": safe_float(row.get("endY")),
                "successful": str(row.get("outcomeType", "")).lower() == "successful",
                "is_key_pass": safe_bool(row.get("is_key_pass", False)), "mode": "network",
            })
        home_passes = passes_df[passes_df["team"] == home] if home else passes_df.iloc[0:0]
        away_passes = passes_df[passes_df["team"] == away] if away else passes_df.iloc[0:0]
        args = _component("pass_map", 800, frames, light_mode, passes=network, selected_idx=None, mode="network",
                          **map_context(frames.df_all, "Pass Network", team=scope_line(home, away),
                                        subset="All team passes", count=len(network), unit="pass",
                                        note="Subset: all passes in the selected match source. Node size shows pass volume; line width shows connection frequency."))
        return view(filters=filters, controls={"view": selected_view},
                    stats=[{"label": "Passes", "home": len(home_passes), "away": len(away_passes)},
                           {"label": "Accuracy", "home": _pass_accuracy(home_passes), "away": _pass_accuracy(away_passes)},
                           {"label": "Key Passes", "home": _key_passes(home_passes), "away": _key_passes(away_passes)}],
                    components=[{"role": "aux", "args": args}],
                    legend="Node colour intensity = pass volume · Line colour intensity = connection frequency")

    team_passes = passes_df[passes_df["team"] == selected_view].copy()
    players = [PLAYER_PROMPT] + _players(team_passes)
    player = choice(controls.get("player"), players)
    available = {label: column for label, column in PASS_TYPES.items() if column in passes_df.columns}
    pass_types = ["All passes"] + list(available)
    pass_type = choice(controls.get("pass_type"), pass_types)
    zone = choice(controls.get("zone"), PITCH_ZONE_OPTIONS)
    depth = choice(controls.get("depth"), DEPTH_ZONE_OPTIONS)
    filters += [select("player", "Player", players, player), select("pass_type", "Pass type", pass_types, pass_type),
                pitch_zone_filter(zone), depth_zone_filter(depth)]
    result = view(filters=filters, controls={"view": selected_view, "player": player, "pass_type": pass_type,
                                             "zone": zone, "depth": depth, "selected": None})
    if player == PLAYER_PROMPT:
        result["notice"] = "Select a player above to view their pass map"
        return result
    shown = team_passes[team_passes["playerName"] == player].copy()
    if pass_type != "All passes" and pass_type in available:
        shown = shown[shown[available[pass_type]] == True]  # noqa: E712 (classic semantics)
    shown = _depth(filter_by_pitch_zone(shown, zone), depth).dropna(subset=["x", "endX"])
    if not shown.empty:
        successful = len(shown[shown["outcomeType"] == "Successful"]) if "outcomeType" in shown.columns else 0
        result["stats"] = [
            {"label": "Passes", "home": len(shown)},
            {"label": "Accuracy", "home": f"{round(successful / len(shown) * 100) if len(shown) > 0 else 0}%"},
            {"label": "Key Passes", "home": int(shown["is_key_pass"].sum()) if "is_key_pass" in shown.columns else 0},
            {"label": "Crosses", "home": int(shown["is_cross"].sum()) if "is_cross" in shown.columns else 0}]
    if shown.empty:
        result["empty"] = "No passes match the current filter."
        return result
    selected = as_index(controls.get("selected"), shown.index)
    result["controls"]["selected"] = selected
    items = []
    for idx, row in shown.iterrows():
        item = {"df_idx": int(idx), "playerName": str(row.get("playerName", "")), "team": str(row.get("team", "")),
                "is_home": bool(row.get("team", "") == home), "minute": int(row.get("minute", 0)),
                "second": int(row.get("second", 0)), "period": str(row.get("period", "")),
                "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
                "endX": safe_float(row.get("endX")), "endY": safe_float(row.get("endY")),
                "successful": str(row.get("outcomeType", "")).lower() == "successful"}
        item.update({flag: safe_bool(row.get(flag, False)) for flag in PASS_FLAGS})
        item["mode"] = "player"
        items.append(item)
    args = _component("pass_map", 470, frames, light_mode, passes=items, selected_idx=selected, mode="player",
                      **map_context(frames.df_all, f"Pass Map - {player}", team=selected_view, player=player,
                                    subset=pass_type, pitch_zone=zone, depth_zone=depth, count=len(shown), unit="pass",
                                    note="Subset: selected player's passes after pass-type, pitch-zone and depth-zone filters. Lines show start-to-end direction."))
    result.update(components=[{"role": "map", "args": args}],
                  legend="● Successful  ● Unsuccessful · Click a pass endpoint to inspect it",
                  picker=picker("Select a pass", "— Select a pass to inspect —", shown, pass_label))
    if selected is not None:
        row = passes_df.loc[selected].to_dict()
        ok = row.get("outcomeType", "") == "Successful"
        tags = " · ".join(label for column, label in PASS_TAGS if safe_bool(row.get(column))) or "—"
        result["selected"] = selected_panel(frames, selected, row,
                                            [badge("SUCCESSFUL" if ok else "UNSUCCESSFUL", "good" if ok else "bad")],
                                            [{"label": "Qualifiers", "value": tags}])
    return result


# ── Defensive Actions ───────────────────────────────────────────────────────

DEF_TYPES = ["Tackle", "Interception", "Clearance", "Aerial", "Block", "Challenge", "Dispossessed", "Error"]
DEF_ICONS = {"Tackle": "Ⓣ", "Interception": "Ⓘ", "Clearance": "Ⓒ", "Aerial": "Ⓐ", "Block": "Ⓑ",
             "Challenge": "Ⓗ", "Dispossessed": "Ⓓ", "Error": "Ⓔ"}


def def_label(row):
    return f"{DEF_ICONS.get(row.get('type', ''), '●')}  {_clock(row)}  {row.get('type', '')}  ({row.get('outcomeType', '')})"


def build_defensive_view(frames, controls, light_mode=True):
    def_df = frames.def_df
    if def_df is None or def_df.empty:
        return view(empty="No defensive action data found in the loaded CSV.")
    teams = team_options(def_df, frames.home_team, frames.away_team)
    team = choice(controls.get("team"), teams)
    team_def = def_df[def_df["team"] == team].copy()
    players = [PLAYER_PROMPT] + _players(team_def)
    player = choice(controls.get("player"), players)
    zone = choice(controls.get("zone"), PITCH_ZONE_OPTIONS)
    depth = choice(controls.get("depth"), DEPTH_ZONE_OPTIONS)
    result = view(filters=[segmented("team", "Team", teams, team), select("player", "Player", players, player),
                           pitch_zone_filter(zone), depth_zone_filter(depth)],
                  controls={"team": team, "player": player, "zone": zone, "depth": depth, "selected": None})
    if player == PLAYER_PROMPT:
        result.update(stats=_type_counts(team_def, DEF_TYPES) or None,
                      notice="Select a player above to view their defensive actions")
        return result
    shown = _depth(filter_by_pitch_zone(team_def[team_def["playerName"] == player].copy(), zone), depth)
    result["stats"] = _type_counts(shown, DEF_TYPES) or None
    if shown.empty:
        result["empty"] = "No defensive actions found for this player."
        return result
    selected = as_index(controls.get("selected"), shown.index)
    result["controls"]["selected"] = selected
    items = [{"df_idx": int(idx), "playerName": str(row.get("playerName", "")), "team": str(row.get("team", "")),
              "is_home": bool(row.get("team", "") == frames.home_team), "minute": int(row.get("minute", 0)),
              "second": int(row.get("second", 0)), "period": str(row.get("period", "")),
              "type": str(row.get("type", "")), "outcomeType": str(row.get("outcomeType", "")),
              "x": safe_float(row.get("x")), "y": safe_float(row.get("y"))} for idx, row in shown.iterrows()]
    args = _component("defensive_map", 500, frames, light_mode, actions=items, selected_idx=selected,
                      **map_context(frames.df_all, f"Defensive Actions - {player}", team=team, player=player,
                                    subset="Defensive actions", pitch_zone=zone, depth_zone=depth, count=len(shown),
                                    unit="action", note="Subset: tackles, interceptions, clearances, aerials, blocks and related defensive events after the active filters."))
    result.update(components=[{"role": "map", "args": args}],
                  picker=picker("Select an action", ACTION_PLACEHOLDER, shown, def_label))
    if selected is not None:
        row = def_df.loc[selected].to_dict()
        badges = [badge(row.get("type", "").upper())]
        for column, text in (("is_last_line", "Last line"), ("is_forced_out", "Forced out"),
                             ("is_error_led_to_shot", "Led to shot"), ("is_error_led_to_goal", "Led to goal")):
            if safe_bool(row.get(column, False)):
                badges.append(badge(text, "bad" if column.startswith("is_error") else "info"))
        result["selected"] = selected_panel(frames, selected, row, badges,
                                            [{"label": "Outcome", "value": row.get("outcomeType", "—")}])
    return result


# ── Dribbles & Carries ──────────────────────────────────────────────────────

def dc_label(row):
    atype, outcome = row.get("type", ""), row.get("outcomeType", "")
    icon = "▶" if atype == "Carry" else ("✓" if outcome == "Successful" else "✕")
    return f"{icon}  {_clock(row)}  {atype}  ({outcome})"


def build_dribbles_view(frames, controls, light_mode=True):
    dc_df = frames.dribble_carry_df
    if dc_df is None or dc_df.empty:
        return view(empty="No dribble or carry data found in the loaded CSV.")
    teams = team_options(dc_df, frames.home_team, frames.away_team)
    team = choice(controls.get("team"), teams)
    team_dc = dc_df[dc_df["team"] == team].copy()
    players = [PLAYER_PROMPT] + _players(team_dc)
    player = choice(controls.get("player"), players)
    zone = choice(controls.get("zone"), PITCH_ZONE_OPTIONS)
    depth = choice(controls.get("depth"), DEPTH_ZONE_OPTIONS)
    result = view(filters=[segmented("team", "Team", teams, team), select("player", "Player", players, player),
                           pitch_zone_filter(zone), depth_zone_filter(depth)],
                  controls={"team": team, "player": player, "zone": zone, "depth": depth, "selected": None})
    if player == PLAYER_PROMPT:
        result["notice"] = "Select a player above to view their dribbles and carries"
        return result
    shown = _depth(filter_by_pitch_zone(team_dc[team_dc["playerName"] == player].copy(), zone), depth)
    shown = shown.dropna(subset=["x", "y"])
    carries = shown[shown["type"] == "Carry"]
    dribbles = shown[shown["type"] == "TakeOn"]
    successful = dribbles[dribbles["outcomeType"] == "Successful"] if "outcomeType" in dribbles.columns else dribbles.iloc[0:0]
    result["stats"] = [{"label": "Carries", "home": len(carries)}, {"label": "Dribble Attempts", "home": len(dribbles)},
                       {"label": "Successful", "home": len(successful)},
                       {"label": "Dribble %", "home": f"{round(len(successful) / len(dribbles) * 100)}%" if len(dribbles) > 0 else "—"}]
    if shown.empty:
        result["empty"] = "No dribbles or carries match the current filter."
        return result
    selected = as_index(controls.get("selected"), shown.index)
    result["controls"]["selected"] = selected
    items = []
    for idx, row in shown.iterrows():
        entry = {"df_idx": int(idx), "type": str(row.get("type", "")), "playerName": str(row.get("playerName", "")),
                 "team": str(row.get("team", "")), "is_home": bool(row.get("team", "") == frames.home_team),
                 "minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
                 "period": str(row.get("period", "")), "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
                 "outcomeType": str(row.get("outcomeType", ""))}
        if str(row.get("type", "")) == "Carry":
            entry["endX"] = safe_float(row.get("endX"))
            entry["endY"] = safe_float(row.get("endY"))
        items.append(entry)
    args = _component("dribble_carry_map", 500, frames, light_mode, actions=items, selected_idx=selected,
                      **map_context(frames.df_all, f"Dribbles And Carries - {player}", team=team, player=player,
                                    subset="Carries and take-ons", pitch_zone=zone, depth_zone=depth, count=len(shown),
                                    unit="action", note="Subset: selected player's carries and take-ons after the active pitch-zone and depth-zone filters. Dotted lines are carries."))
    result.update(components=[{"role": "map", "args": args}],
                  legend="● Succ. dribble  ● Unsucc. dribble  —— Carry · Click to inspect",
                  picker=picker("Select an action", ACTION_PLACEHOLDER, shown, dc_label))
    if selected is not None:
        row = dc_df.loc[selected].to_dict()
        atype, outcome = row.get("type", ""), row.get("outcomeType", "")
        if atype == "Carry":
            tag = badge("CARRY", "info")
        elif outcome == "Successful":
            tag = badge("DRIBBLE SUCCESSFUL", "good")
        else:
            tag = badge("DRIBBLE UNSUCCESSFUL", "bad")
        result["selected"] = selected_panel(frames, selected, row, [tag], [{"label": "Outcome", "value": outcome or "—"}])
    return result


# ── Goalkeeper ──────────────────────────────────────────────────────────────

GK_MODES = ["GK Actions", "Shots Faced", "Distribution"]
GK_TYPES = ["Punch", "Claim", "KeeperSweeper", "KeeperPickup", "PenaltyFaced"]
DIST_COLS = ["is_goal_kick", "is_keeper_throw", "is_gk_hoof", "is_gk_kick_from_hands"]


def _dist_type_label(row):
    for label, column in [("Goal Kick", "is_goal_kick"), ("Keeper Throw", "is_keeper_throw"),
                          ("GK Hoof", "is_gk_hoof"), ("GK Kick", "is_gk_kick_from_hands")]:
        if column in row and safe_bool(row.get(column, False)):
            return label
    return "Distribution"


def sf_label(row):
    icon = "●" if reclassify_shot(row) == "SavedShot" else "✕"
    return f"{icon}  {_clock(row)}  {row.get('playerName', 'Unknown')}  ({row.get('team', '')})"


def dist_label(row):
    end_x = float(row.get("endX", 0) or 0)
    zone = "Short" if end_x < 40 else ("Long" if end_x >= 70 else "Med")
    return f"▶  {_clock(row)}  {_dist_type_label(row)}  [{zone}]  endX={end_x:.0f}"


def gk_label(row):
    return f"●  {_clock(row)}  {row.get('type', '')}  ({row.get('outcomeType', '')})"


def build_goalkeeper_view(frames, controls, light_mode=True):
    gk_df = frames.gk_df
    if gk_df is None or gk_df.empty:
        return view(empty="No goalkeeper action data found in the loaded CSV.")
    home, away = frames.home_team, frames.away_team
    teams = team_options(gk_df, home, away)
    team = choice(controls.get("team"), teams)
    team_gk = gk_df[gk_df["team"] == team].copy()
    players = ["— Select a goalkeeper —"] + _players(team_gk)
    player = choice(controls.get("player"), players)
    mode = choice(controls.get("mode"), GK_MODES)
    zone = choice(controls.get("zone"), PITCH_ZONE_OPTIONS)
    depth = choice(controls.get("depth"), DEPTH_ZONE_OPTIONS)
    result = view(filters=[segmented("team", "Team", teams, team), select("player", "Player", players, player),
                           segmented("mode", "Mode", GK_MODES, mode), pitch_zone_filter(zone), depth_zone_filter(depth)],
                  controls={"team": team, "player": player, "mode": mode, "zone": zone, "depth": depth, "selected": None})
    if player == "— Select a goalkeeper —":
        result["notice"] = "Select a goalkeeper above to view their actions"
        return result

    if mode == "Shots Faced":
        shots_df = frames.shots_df
        if shots_df is None or shots_df.empty:
            result["empty"] = "No shot data available."
            return result
        opponent = away if team == home else home
        shots = shots_df[(shots_df["team"] == opponent) & (shots_df["type"].isin({"SavedShot", "AttemptSaved", "Goal"}))].copy()
        shots = _depth(filter_by_pitch_zone(shots, zone), depth).dropna(subset=["x", "y"])
        result["stats"] = [
            {"label": "Saved", "home": sum(1 for _, r in shots.iterrows() if reclassify_shot(r) in {"SavedShot"})},
            {"label": "Goals Conceded", "home": sum(1 for _, r in shots.iterrows() if reclassify_shot(r) == "Goal")}]
        if shots.empty:
            result["empty"] = "No on-target shots match the current filter."
            return result
        selected = as_index(controls.get("selected"), shots.index)
        result["controls"]["selected"] = selected
        components = []
        if selected is not None:
            row = shots.loc[selected]
            components.append({"role": "aux", "args": {
                "component_type": "shot_map", "shots": [shot_to_dict(selected, row, home)],
                "home_team": home or "", "away_team": away or "", "selected_idx": selected, "view": "goalframe",
                **map_context(frames.df_all, f"Shot Faced Placement - {row.get('playerName', 'Unknown')}",
                              team=row.get("team", ""), subset=reclassify_shot(row), count=1, unit="shot",
                              note=f"Goal-mouth placement for the selected on-target shot faced by {player}."),
                "height": 320, "light_mode": light_mode}})
        items = []
        for idx, row in shots.iterrows():
            item = shot_to_dict(idx, row, home)
            items.append({"df_idx": item["df_idx"], "type": item["type"], "playerName": item["playerName"],
                          "team": item["team"], "is_home": item["is_home"], "minute": item["minute"],
                          "second": item["second"], "period": item["period"], "x": item["x"], "y": item["y"],
                          "goal_mouth_y": item["goal_mouth_y"], "goal_mouth_z": item["goal_mouth_z"]})
        components.append({"role": "map", "args": _component(
            "goalkeeper_map", 520, frames, light_mode, actions=items, selected_idx=selected, shots_faced=True,
            **map_context(frames.df_all, f"Shots Faced - {player}", team=team, player=player,
                          subset=f"On-target shots by {opponent}", pitch_zone=zone, depth_zone=depth, count=len(shots),
                          unit="shot", note="Subset: opposition on-target shots after the active pitch-zone and depth-zone filters. The map is drawn from the goalkeeper's defensive-half view."))})
        result.update(components=components, legend="● Saved  ✕ Goal · Click to inspect",
                      picker=picker("Select a shot", "— Select a shot to inspect —", shots, sf_label))
        if selected is not None:
            row = shots_df.loc[selected].to_dict()
            s_type = reclassify_shot(row)
            result["selected"] = selected_panel(frames, selected, row,
                                                [badge("GOAL" if s_type == "Goal" else "SAVED", "bad" if s_type == "Goal" else "good")],
                                                [{"label": "Type", "value": s_type}])
        return result

    if mode == "Distribution":
        passes_df = frames.passes_df
        if passes_df is None or passes_df.empty:
            result["empty"] = "No pass data available."
            return result
        dist = passes_df[(passes_df["team"] == team) & (passes_df["playerName"] == player)].copy()
        available = [column for column in DIST_COLS if column in dist.columns]
        if available and not dist.empty:
            dist = dist[dist[available].apply(lambda r: r.map(safe_bool).any(), axis=1)]
        dist = dist.dropna(subset=["x", "endX"])
        if dist.empty:
            result["empty"] = f"No distribution passes (goal kicks, keeper throws, hoofs) found for {player}."
            return result
        total = len(dist)
        end_x = dist["endX"].apply(lambda v: float(v or 0))
        short_n = int((end_x < 40).sum())
        medium_n = int(((end_x >= 40) & (end_x < 70)).sum())
        long_n = int((end_x >= 70).sum())
        result["stats"] = [{"label": "Total", "home": total},
                           {"label": "Short (<40)", "home": f"{round(short_n / total * 100)}%"},
                           {"label": "Medium (40-70)", "home": f"{round(medium_n / total * 100)}%"},
                           {"label": "Long (>70)", "home": f"{round(long_n / total * 100)}%"}]
        selected = as_index(controls.get("selected"), dist.index)
        result["controls"]["selected"] = selected
        items = []
        for idx, row in dist.iterrows():
            ex = float(row.get("endX", 0) or 0)
            items.append({"df_idx": int(idx), "playerName": str(row.get("playerName", "")), "team": str(row.get("team", "")),
                          "is_home": bool(row.get("team", "") == home), "minute": int(row.get("minute", 0)),
                          "second": int(row.get("second", 0)), "period": str(row.get("period", "")),
                          "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
                          "endX": safe_float(row.get("endX")), "endY": safe_float(row.get("endY")),
                          "successful": str(row.get("outcomeType", "")).lower() == "successful",
                          "is_key_pass": False, "is_cross": False, "is_long_ball": ex >= 70, "mode": "player"})
        result.update(
            components=[{"role": "map", "args": _component(
                "pass_map", 470, frames, light_mode, passes=items, selected_idx=selected, mode="player",
                **map_context(frames.df_all, f"Goalkeeper Distribution - {player}", team=team, player=player,
                              subset="Goal kicks, throws and GK kicks", count=len(dist), unit="pass",
                              note="Subset: goalkeeper distribution events only. Short/medium/long buckets are based on pass endX distance."))}],
            legend="—— Successful  —— Unsuccessful · Click to inspect",
            picker=picker("Select a distribution", "— Select a distribution —", dist, dist_label))
        if selected is not None:
            row = passes_df.loc[selected].to_dict()
            ex = float(row.get("endX", 0) or 0)
            zone_label = "Short" if ex < 40 else ("Long" if ex >= 70 else "Medium")
            result["selected"] = selected_panel(frames, selected, row, [badge(zone_label.upper(), "info")],
                                                [{"label": "Type · Distance", "value": f"{_dist_type_label(row)} · endX {ex:.0f}"}])
        return result

    shown = _depth(filter_by_pitch_zone(team_gk[team_gk["playerName"] == player].copy(), zone), depth).dropna(subset=["x", "y"])
    result["stats"] = _type_counts(shown, GK_TYPES) or None
    if shown.empty:
        result["empty"] = "No goalkeeper actions match the current filter."
        return result
    selected = as_index(controls.get("selected"), shown.index)
    result["controls"]["selected"] = selected
    items = [{"df_idx": int(idx), "type": str(row.get("type", "")), "playerName": str(row.get("playerName", "")),
              "team": str(row.get("team", "")), "is_home": bool(row.get("team", "") == home),
              "minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
              "period": str(row.get("period", "")), "x": safe_float(row.get("x")), "y": safe_float(row.get("y")),
              "outcomeType": str(row.get("outcomeType", ""))} for idx, row in shown.iterrows()]
    result.update(
        components=[{"role": "map", "args": _component(
            "goalkeeper_map", 520, frames, light_mode, actions=items, selected_idx=selected, shots_faced=False,
            **map_context(frames.df_all, f"Goalkeeper Actions - {player}", team=team, player=player, subset=mode,
                          pitch_zone=zone, depth_zone=depth, count=len(shown), unit="action",
                          note="Subset: goalkeeper actions after the active pitch-zone and depth-zone filters. The map is drawn from the goalkeeper's defensive-half view."))}],
        legend="Punch · Claim · Sweep · Pickup · Penalty · Click to inspect",
        picker=picker("Select an action", ACTION_PLACEHOLDER, shown, gk_label))
    if selected is not None:
        row = gk_df.loc[selected].to_dict()
        result["selected"] = selected_panel(frames, selected, row, [badge(str(row.get("type", "")).upper(), "info")],
                                            [{"label": "Outcome", "value": row.get("outcomeType", "") or "—"}])
    return result


TABS = {
    "pass-map": build_pass_view,
    "defensive-actions": build_defensive_view,
    "dribbles-carries": build_dribbles_view,
    "goalkeeper": build_goalkeeper_view,
}
CLIPS = {slug: clip_event(builder) for slug, builder in TABS.items()}
