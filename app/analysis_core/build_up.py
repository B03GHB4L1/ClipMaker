"""Build-Up native view (ported from the classic Analyst Room tab).

Entry modes (final third, box) list entries like the other map tabs; chain
modes (progressive, possession) list sequences, show the selected one on the
pitch and clip it from its first to its last action.
"""
from __future__ import annotations

import pandas as pd

from .common import map_context, safe_bool
from .frames import SHOT_TYPES
from .views import as_index, badge, segmented, select, selected_panel, team_options, view

MODES = ["Progressive Chains", "Possession Chains", "Final 3rd Entries", "Box Entries"]
MIN_CHAIN = ["2", "3", "4", "5", "6"]
PERIOD_SHORT = {"FirstHalf": "1H", "SecondHalf": "2H", "FirstPeriodOfExtraTime": "ET1", "SecondPeriodOfExtraTime": "ET2"}


def _float(row, key, default=0.0):
    try:
        value = row.get(key, default)
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _end_coord(row, axis):
    keys = ("endX", "carry_end_x", "carryEndX") if axis == "x" else ("endY", "carry_end_y", "carryEndY")
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return _float(row, key)
    return _float(row, axis)


def _fallback_entry_mask(df, entry_mode):
    x = pd.to_numeric(df.get("x"), errors="coerce").fillna(0)
    y = pd.to_numeric(df.get("y"), errors="coerce").fillna(0)
    end_x = pd.to_numeric(df.get("endX"), errors="coerce").fillna(x)
    end_y = pd.to_numeric(df.get("endY"), errors="coerce").fillna(y)
    if entry_mode == "final_third":
        return (x < 67) & (end_x >= 67)
    start_in_box = (x > 83) & (y > 21) & (y < 79)
    end_in_box = (end_x > 83) & (end_y > 21) & (end_y < 79)
    return (~start_in_box) & end_in_box


def entry_events(df_source, team, entry_mode):
    if df_source is None or df_source.empty:
        return pd.DataFrame()
    pass_col, carry_col = (("is_final_third_entry_pass", "is_final_third_entry_carry") if entry_mode == "final_third"
                           else ("is_box_entry_pass", "is_box_entry_carry"))
    team_df = df_source[df_source["team"] == team].copy()
    if team_df.empty:
        return team_df
    if pass_col in team_df.columns:
        pass_mask = team_df[pass_col].map(safe_bool)
    else:
        pass_mask = (team_df["type"] == "Pass") & _fallback_entry_mask(team_df, entry_mode)
    if carry_col in team_df.columns:
        carry_mask = team_df[carry_col].map(safe_bool)
    else:
        carry_mask = (team_df["type"] == "Carry") & _fallback_entry_mask(team_df, entry_mode)
    entries = team_df[pass_mask | carry_mask].copy()
    if entries.empty:
        return entries
    entries["_entry_kind"] = entries["type"].apply(lambda t: "Carry" if str(t) == "Carry" else "Pass")
    entries["_end_x"] = entries.apply(lambda r: _end_coord(r, "x"), axis=1)
    entries["_end_y"] = entries.apply(lambda r: _end_coord(r, "y"), axis=1)
    return entries.sort_index()


def _entry_dict(idx, row, step, entry_label):
    return {
        "df_idx": int(idx), "step": int(step), "type": str(row.get("type", "")),
        "entry_kind": str(row.get("_entry_kind", row.get("type", ""))), "entry_label": entry_label,
        "playerName": str(row.get("playerName", "")), "minute": int(row.get("minute", 0) or 0),
        "second": int(row.get("second", 0) or 0), "x": _float(row, "x"), "y": _float(row, "y"),
        "endX": _float(row, "_end_x", _end_coord(row, "x")), "endY": _float(row, "_end_y", _end_coord(row, "y")),
    }


def entry_label_of(row):
    kind = row.get("_entry_kind", row.get("type", "Entry"))
    return f"{int(row.get('minute', 0))}'{int(row.get('second', 0)):02d}\"  {kind}  {row.get('playerName', 'Unknown')}"


def chain_label(chain):
    period = PERIOD_SHORT.get(str(chain.get("start_period", "")), "")
    return (f"{int(chain['start_minute'])}'{int(chain['start_second']):02d}\" "
            f"→ {int(chain['end_minute'])}'{int(chain['end_second']):02d}\" "
            f"{period}  ·  {chain['action_count']} actions")


def _build_up_args(actions, is_home, selected_idx, light_mode, entry_mode, height, context):
    return {"component_type": "build_up_map", "actions": actions, "is_home": bool(is_home),
            "selected_idx": selected_idx, "entry_mode": entry_mode or "", **context,
            "height": height, "light_mode": light_mode}


def _entries_view(frames, result, team, mode, controls, light_mode):
    entry_mode = "final_third" if mode == "Final 3rd Entries" else "box"
    entry_label = "Final 3rd Entry" if entry_mode == "final_third" else "Box Entry"
    plural = "Final 3rd Entries" if entry_mode == "final_third" else "Box Entries"
    entries = entry_events(frames.df_all, team, entry_mode)
    if entries.empty:
        result["empty"] = f"No {entry_label.lower()} passes or carries found for {team}."
        return result
    passes = int((entries["_entry_kind"] == "Pass").sum())
    carries = int((entries["_entry_kind"] == "Carry").sum())
    outcome = entries.get("outcomeType", pd.Series(index=entries.index, dtype=object))
    result["stats"] = [{"label": plural, "home": len(entries)}, {"label": "Pass / Carry", "home": f"{passes} / {carries}"},
                       {"label": "Successful Passes", "home": int((outcome == "Successful").sum())}]
    selected = as_index(controls.get("selected"), entries.index)
    result["controls"]["selected"] = selected
    actions = [_entry_dict(idx, row, step, entry_label) for step, (idx, row) in enumerate(entries.iterrows(), 1)]
    context = map_context(frames.df_all, f"{plural} - {team}", team=team, subset=plural, count=len(entries), unit="entry",
                          note=f"Subset: {entry_label.lower()} passes and carries for the selected team. Numbered markers follow event order; endpoints are clickable.")
    result["components"] = [{"role": "map", "args": _build_up_args(actions, team == frames.home_team, selected,
                                                                    light_mode, entry_mode, 680, context)}]
    result["legend"] = "Click an entry endpoint on the pitch to inspect it and cut the clip"
    result["picker"] = {"label": "Select entry", "placeholder": "— Select an entry to inspect —",
                        "items": [{"id": int(idx), "label": entry_label_of(row)} for idx, row in entries.iterrows()]}
    if selected is not None:
        row = entries.loc[selected].to_dict()
        kind = row.get("_entry_kind", row.get("type", "Entry"))
        outcome_text = str(row.get("outcomeType", "") or "")
        result["selected"] = selected_panel(frames, selected, row,
                                            [badge(f"{entry_label.upper()} · {str(kind).upper()}",
                                                   "good" if outcome_text == "Successful" else "info")],
                                            [{"label": "Outcome", "value": outcome_text or "Carry / movement"}])
    return result


def _chains(frames, team, mode, min_chain):
    from clipmaker_core import detect_possession_carries, detect_progressive_chains
    if mode == "Progressive Chains":
        chains = [c for c in detect_progressive_chains(frames.df_all, min_chain_length=min_chain) if c["team"] == team]
        return [c for c in chains if c["starts_in_own_half"] and c["reaches_opp_half"]]
    return [c for c in detect_possession_carries(frames.df_all) if c["team"] == team]


def _chains_view(frames, result, team, mode, controls, light_mode):
    df_all = frames.df_all
    min_chain = None
    if mode == "Progressive Chains":
        if "prog_pass" not in df_all.columns and "prog_carry" not in df_all.columns:
            result["empty"] = "No progressive action columns (prog_pass / prog_carry) found in the data."
            return result
        min_chain = int(controls.get("min_chain")) if str(controls.get("min_chain")) in MIN_CHAIN else 3
        result["filters"].append(select("min_chain", "Min actions per sequence", MIN_CHAIN, str(min_chain)))
        result["controls"]["min_chain"] = str(min_chain)
    chains = _chains(frames, team, mode, min_chain)
    if not chains:
        result["empty"] = (f"No progressive build-up sequences ({min_chain}+ actions) from own half to opposition half found for {team}."
                           if mode == "Progressive Chains" else
                           f"No possession chain sequences (own half → loss in opp half or shot) found for {team}.")
        return result
    average = sum(c["action_count"] for c in chains) / len(chains)
    if mode == "Progressive Chains":
        direct = sum(1 for c in chains if c["action_count"] <= 3) / len(chains) * 100
        result["stats"] = [{"label": "Build-Up Entries", "home": len(chains)}, {"label": "Avg Actions", "home": f"{average:.1f}"},
                           {"label": "Direct %", "home": f"{direct:.0f}%"}]
    else:
        shots = sum(1 for c in chains if c.get("terminal_type", "") in SHOT_TYPES) / len(chains) * 100
        result["stats"] = [{"label": "Possession Chains", "home": len(chains)}, {"label": "Avg Actions", "home": f"{average:.1f}"},
                           {"label": "Shot %", "home": f"{shots:.0f}%"}]
    selected = as_index(controls.get("selected"), range(len(chains)))
    result["controls"]["selected"] = selected
    result["picker"] = {"label": "Select a sequence", "placeholder": "— Select a sequence to inspect —",
                        "items": [{"id": index, "label": chain_label(chain)} for index, chain in enumerate(chains)]}
    if selected is None:
        result["notice"] = "Select a sequence to inspect it and cut its clip."
        return result
    from clipmaker_core import get_chain_actions
    chain = chains[selected]
    actions = []
    for step, (_, row) in enumerate(get_chain_actions(df_all, chain).iterrows(), 1):
        actions.append({"step": step, "type": str(row.get("type", "")), "playerName": str(row.get("playerName", "")),
                        "minute": int(row.get("minute", 0)), "second": int(row.get("second", 0)),
                        "x": float(row.get("x", 0) or 0), "y": float(row.get("y", 0) or 0),
                        "endX": float(row.get("endX", 0) or 0), "endY": float(row.get("endY", 0) or 0)})
    subset = (f"Sequence {int(chain['start_minute'])}:{int(chain.get('start_second', 0) or 0):02d}"
              f" to {int(chain['end_minute'])}:{int(chain.get('end_second', 0) or 0):02d}")
    context = map_context(df_all, f"{mode} - {team}", team=team, subset=subset, count=len(actions), unit="action",
                          note="Subset: the selected build-up sequence only. Numbered markers show action order and arrows show progression.")
    result["components"] = [{"role": "aux", "args": _build_up_args(actions, team == frames.home_team, None,
                                                                    light_mode, "", 520, context)}]
    start_row = df_all.loc[chain["start_idx"]]
    end_row = df_all.loc[chain["end_idx"]]
    title = f"Sequence Detail  ·  {int(chain['start_minute'])}' – {int(chain['end_minute'])}'"
    result["selected"] = {
        "id": selected, "kind": "sequence", "title": title, "is_home": team == frames.home_team,
        "subtitle": f"{team} · {chain_label(chain)}", "badges": [badge(mode.upper(), "info")],
        "fields": [{"label": "Actions", "value": chain["action_count"]}],
        # Classic timing: both ends use the start event's period.
        "event": {"minute": int(start_row.get("minute", 0) or 0), "second": int(start_row.get("second", 0) or 0),
                  "period": str(start_row.get("period", "FirstHalf")), "player": f"sequence_{selected}",
                  "end": {"minute": int(end_row.get("minute", 0) or 0), "second": int(end_row.get("second", 0) or 0)}},
    }
    return result


def build_view(frames, controls, light_mode=True):
    df_all = frames.df_all
    if df_all is None or df_all.empty:
        return view(empty="No match data loaded.")
    teams = team_options(df_all, frames.home_team, frames.away_team)
    team = controls.get("team") if controls.get("team") in teams else teams[0]
    mode = controls.get("mode") if controls.get("mode") in MODES else MODES[0]
    result = view(filters=[segmented("team", "Team", teams, team), segmented("mode", "Mode", MODES, mode)],
                  controls={"team": team, "mode": mode, "selected": None})
    if mode in ("Final 3rd Entries", "Box Entries"):
        return _entries_view(frames, result, team, mode, controls, light_mode)
    return _chains_view(frames, result, team, mode, controls, light_mode)


def clip(frames, controls):
    selected = build_view(frames, controls).get("selected")
    if not selected:
        raise ValueError("Select an entry or sequence before cutting its clip.")
    return selected["event"]
