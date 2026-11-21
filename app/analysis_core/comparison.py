"""Player Comparison native view (ported from the classic Analyst Room tab)."""
from __future__ import annotations

import json

from . import comparison_helpers as helpers
from .common import AWAY_COLOR, HOME_COLOR, match_export_context
from .views import segmented, select, team_options, view

ROLES = ["Attacker", "Midfielder", "Defender"]
OUTFIELD_AXES = ["Defensive", "Creative", "Progressive", "Shooting", "Danger", "Dribbling", "Aerial",
                 "Pass Completion %", "Involvement"]
GK_AXES = ["Saves", "Claiming", "Punching", "Sweeping", "Distribution", "Long Distribution", "Ball Recovery"]
ZONES = ["Left Wing", "Left Half Space", "Centre", "Right Half Space", "Right Wing"]


def _figure_json(fig):
    """Figure JSON for Plotly.js. The classic page sends Streamlit's placeholder
    template (replaced by its theme in the browser); every colour these charts
    show is set explicitly, so the native page uses the neutral "none" template."""
    from .st_shim import figure_json
    figure = figure_json(fig)
    figure.setdefault("layout", {})["template"] = {}
    return figure


def _zone_figure(ev, player_name, color, match_context, light):
    import plotly.graph_objects as go
    from clipmaker_core import _effective_pitch_zone_series
    zones = _effective_pitch_zone_series(ev).value_counts()
    counts = [zones.get(zone, 0) for zone in ZONES]
    fig = go.Figure(go.Bar(y=ZONES, x=counts, orientation="h", marker=dict(color=color)))
    fig.update_layout(xaxis_title="Event count", yaxis_title="Pitch zone", height=390,
                      margin=dict(t=118, b=44, l=90, r=30))
    helpers._plotly_header(fig, f"Pitch Zone Activity - {player_name}", subtitle=match_context, light=light, height=390)
    return helpers.brand_plotly_export(fig, light=light)


SHOT_TYPES = {"SavedShot", "MissedShot", "MissedShots", "Goal", "ShotOnPost", "BlockedShot", "AttemptSaved", "Attempt"}
XG_NOTE = ("VizorPlay xG, fitted on StatsBomb open data (Data: StatsBomb). Minutes come from substitutions. "
           "Penalties count; own goals do not.")


COUNTS = {"Minutes", "Shots", "Goals"}


def minutes_played(ev, df_all):
    """Minutes on the pitch, from the player's substitution events (whole match otherwise)."""
    import pandas as pd
    minutes = pd.to_numeric(df_all.get("minute"), errors="coerce")
    match_end = max(90.0, float(minutes.max()) if minutes.notna().any() else 90.0)
    types = ev["type"].astype(str)
    on = pd.to_numeric(ev.loc[types == "SubstitutionOn", "minute"], errors="coerce").dropna()
    off = pd.to_numeric(ev.loc[types == "SubstitutionOff", "minute"], errors="coerce").dropna()
    start = float(on.min()) if len(on) else 0.0
    end = float(off.max()) if len(off) else match_end
    if end <= start:  # inconsistent substitution events: count from kick-off
        start = 0.0
    return max(1.0, end - start)


def shooting_profile(ev, df_all):
    """Shots, goals and xG for one player in this match."""
    import pandas as pd
    shots = ev[ev["type"].isin(SHOT_TYPES)]
    if "is_own_goal" in shots:
        shots = shots[~shots["is_own_goal"].astype(str).str.lower().isin({"true", "1", "1.0"})]
    xg = float(pd.to_numeric(shots.get("xG"), errors="coerce").fillna(0).sum()) if len(shots) else 0.0
    goals = int((shots["type"] == "Goal").sum())
    minutes = minutes_played(ev, df_all)
    return {
        "Minutes": round(minutes),
        "Shots": int(len(shots)),
        "Goals": goals,
        "xG": round(xg, 2),
        "Goals - xG": round(goals - xg, 2),
        "xG per shot": round(xg / len(shots), 2) if len(shots) else 0.0,
    }


def _xg_figure(profile1, profile2, player1, player2, match_context, light):
    """Mirrored bars: player 1 to the left, player 2 to the right, each row scaled to its larger value."""
    import plotly.graph_objects as go
    metrics = list(profile1)[::-1]
    def scaled(value, other):
        top = max(abs(value), abs(other))
        return 0 if top == 0 else abs(value) / top
    left = [-scaled(profile1[m], profile2[m]) for m in metrics]
    right = [scaled(profile2[m], profile1[m]) for m in metrics]
    def shown(metric, value):
        if metric == "Goals - xG":
            return f"{value:+.2f}"
        return str(value) if metric in COUNTS else f"{value:.2f}"
    text1 = [shown(m, profile1[m]) for m in metrics]
    text2 = [shown(m, profile2[m]) for m in metrics]
    ink = "#1f241b" if light else "#e8e8e8"
    colors = ("#9bb81f" if light else "#E8FF4D", AWAY_COLOR)
    fig = go.Figure([
        go.Bar(y=metrics, x=values, orientation="h", name=name, marker=dict(color=color),
               customdata=texts, hovertemplate="%{y}: %{customdata}<extra>" + name + "</extra>")
        for values, texts, name, color in ((left, text1, player1, colors[0]), (right, text2, player2, colors[1]))
    ])
    # Values sit in a column at each edge, so zeros never pile up in the middle.
    font = dict(color=ink, family="Geist Mono, monospace", size=12)
    for metric, first, second in zip(metrics, text1, text2):
        fig.add_annotation(x=-1.58, y=metric, text=first, xanchor="left", showarrow=False, font=font)
        fig.add_annotation(x=1.58, y=metric, text=second, xanchor="right", showarrow=False, font=font)
    fig.update_layout(barmode="overlay", bargap=0.35, height=400, margin=dict(t=118, b=40, l=110, r=24),
                      xaxis=dict(range=[-1.6, 1.6], showticklabels=False, zeroline=True, showgrid=False),
                      # A spare row at the bottom keeps the VizorPlay mark off the last values.
                      yaxis=dict(title=None, range=[-1.4, len(metrics) - 0.5]),
                      legend=dict(orientation="h", x=1, xanchor="right", y=1.01, yanchor="bottom"))
    helpers._plotly_header(fig, f"Shooting & xG - {player1} vs {player2}", subtitle=match_context, note=XG_NOTE,
                           light=light, height=400)
    return helpers.brand_plotly_export(fig, light=light)


def top_moments(ev, role, is_gk):
    scored = helpers._score_gk_moments(ev) if is_gk else helpers._score_moments(ev, role)
    scored = scored[scored["moment_score"] > 0]
    top5 = scored.nlargest(5, "moment_score")
    shown = top5[["minute", "second", "type", "moment_score"]].copy().rename(columns={"moment_score": "Score"})
    shown["Score"] = shown["Score"].round(1)
    return top5, shown


def _players(df_all, team):
    return sorted(df_all[df_all["team"] == team]["playerName"].dropna().unique().tolist())


def _selection(frames, controls):
    """Validated teams, players and roles, as the classic tab resolves them."""
    df_all = frames.df_all
    teams = team_options(df_all, frames.home_team, frames.away_team)
    chosen = {}
    for side in ("1", "2"):
        team = controls.get(f"team{side}") if controls.get(f"team{side}") in teams else teams[0]
        players = _players(df_all, team)
        player = controls.get(f"player{side}") if controls.get(f"player{side}") in players else (players[0] if players else None)
        role = controls.get(f"role{side}") if controls.get(f"role{side}") in ROLES else ROLES[0]
        chosen[side] = {"team": team, "players": players, "player": player, "role": role}
    return teams, chosen


def build_view(frames, controls, light_mode=True):
    df_all = frames.df_all
    if df_all is None or df_all.empty:
        return view(empty="No match data loaded.")
    teams, chosen = _selection(frames, controls)
    filters = []
    for side in ("1", "2"):
        item = chosen[side]
        filters.append(segmented(f"team{side}", f"Team {side}", teams, item["team"]))
        if item["players"]:
            filters.append(select(f"player{side}", f"Player {side}", item["players"], item["player"]))
    result = view(filters=filters, controls={f"{key}{side}": chosen[side][key] for side in ("1", "2")
                                             for key in ("team", "player", "role")})
    result.update(warning=None, figures=[], moments=[])
    player1, player2 = chosen["1"]["player"], chosen["2"]["player"]
    if not player1 or not player2:
        result["notice"] = "Select two players to compare."
        return result

    p1_ev = df_all[df_all["playerName"] == player1].copy()
    p2_ev = df_all[df_all["playerName"] == player2].copy()
    p1_gk, p2_gk = helpers._is_gk(p1_ev), helpers._is_gk(p2_ev)
    if p1_gk != p2_gk:
        result["warning"] = (
            f"Role mismatch: {player1} is classified as {'a goalkeeper' if p1_gk else 'an outfield player'} and "
            f"{player2} is classified as {'a goalkeeper' if p2_gk else 'an outfield player'}. "
            "Radar uses outfield indexes — comparison may not be meaningful.")
    outfield_pool, _ = helpers._build_percentile_pools(df_all)
    if p1_gk and p2_gk:
        axes, p1_raw, p2_raw = GK_AXES, helpers._raw_gk(p1_ev), helpers._raw_gk(p2_ev)
        p1_pct, p2_pct = helpers._gk_head_to_head(p1_raw, p2_raw)
    else:
        axes, p1_raw, p2_raw = OUTFIELD_AXES, helpers._raw_outfield(p1_ev), helpers._raw_outfield(p2_ev)
        p1_pct = helpers._percentile_rank(p1_raw, outfield_pool)
        p2_pct = helpers._percentile_rank(p2_raw, outfield_pool)
    context = match_export_context(df_all)
    radar = helpers.brand_plotly_export(helpers._build_radar_figure(
        axes=axes, p1_pct=p1_pct, p2_pct=p2_pct, p1_raw=p1_raw, p2_raw=p2_raw, player1=player1, player2=player2,
        color1="#E8FF4D", color2=AWAY_COLOR, light=light_mode, match_context=context), light=light_mode)
    result["figures"] = [
        {"section": "Performance Radar", "figure": _figure_json(radar),
         "config": helpers.plotly_export_config("performance_radar", player1, "vs", player2, context)},
        {"section": "Pitch Zone Activity", "figure": _figure_json(_zone_figure(p1_ev, player1, HOME_COLOR, context, light_mode)),
         "config": helpers.plotly_clean_static_config("pitch_zone_activity", player1, context)},
        {"section": "Pitch Zone Activity", "figure": _figure_json(_zone_figure(p2_ev, player2, AWAY_COLOR, context, light_mode)),
         "config": helpers.plotly_clean_static_config("pitch_zone_activity", player2, context)},
        # Index 3 (drawn into the section under the radar).
        {"section": "Shooting & xG", "figure": _figure_json(_xg_figure(
            shooting_profile(p1_ev, df_all), shooting_profile(p2_ev, df_all), player1, player2, context, light_mode)),
         "config": helpers.plotly_export_config("shooting_xg", player1, "vs", player2, context)},
    ]
    for side, ev, is_gk in (("1", p1_ev, p1_gk), ("2", p2_ev, p2_gk)):
        player = chosen[side]["player"]
        role = None if is_gk else chosen[side]["role"]
        if not is_gk:
            # Keep each player's team, player and role together.
            position = next(i for i, item in enumerate(result["filters"]) if item["key"] == f"player{side}") + 1
            result["filters"].insert(position, select(f"role{side}", f"Role — {player}", ROLES, chosen[side]["role"]))
        _, shown = top_moments(ev, role.lower() if role else None, is_gk)
        result["moments"].append({
            "reel": int(side), "player": player, "is_gk": is_gk, "role": "Goalkeeper" if is_gk else role,
            "columns": list(shown.columns), "rows": shown.values.tolist(),
            "empty": "No qualifying moments found for this player." if shown.empty else None,
        })
    return result


def clip(frames, controls):
    """The events of one player's Top 5 Moments reel, in ranking order."""
    reel = str(controls.get("reel"))
    if reel not in {"1", "2"}:
        raise ValueError("Choose which player's reel to generate.")
    _, chosen = _selection(frames, controls)
    player = chosen[reel]["player"]
    if not player:
        raise ValueError("Select two players to compare.")
    ev = frames.df_all[frames.df_all["playerName"] == player].copy()
    is_gk = helpers._is_gk(ev)
    top5, _ = top_moments(ev, None if is_gk else chosen[reel]["role"].lower(), is_gk)
    if top5.empty:
        raise ValueError("No qualifying moments found for this player.")
    period_col = "period" if "period" in top5.columns else "resolved_period"
    events = [{"minute": int(row["minute"]), "second": int(row["second"]),
               "period": str(row[period_col]) if period_col in row.index else "FirstHalf"}
              for _, row in top5.iterrows()]
    return {"reel": events, "player": f"{player}_top5_moments"}
