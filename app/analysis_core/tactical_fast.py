"""Faster equivalents of the Tactical Lab's transition detectors.

The classic detectors filter the whole match for every loss or recovery and
re-parse string flags for each window. These versions compute the row flags
once per frame and slice windows by position, which is valid because the
prepared frame is sorted by match, period and clock with ``event_id`` in that
order (``_prepare_df``). Results are identical; tests/test_tactical_native.py
compares them with the verbatim originals.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import tactical_page as page

_original = {
    "detect_defensive_transitions": page.detect_defensive_transitions,
    "detect_attacking_transitions": page.detect_attacking_transitions,
}


def _context(df, team):
    team_rows = df["team"].astype(str).eq(team).to_numpy()
    danger = page._danger_mask(df).to_numpy()
    progression = page._progression_mask(df).to_numpy()
    win = page._def_win_mask(df, team).to_numpy()
    shot = df["type"].isin(page.SHOT_TYPES).to_numpy()
    xt = df["xT"].clip(lower=0).to_numpy()
    seconds = df["event_seconds"].to_numpy()
    period = df["period_order"].to_numpy()
    match = df["match_id"].to_numpy() if "match_id" in df.columns else np.zeros(len(df), dtype=int)
    return team_rows, danger, progression, win, shot, xt, seconds, period, match


def _window(position, start_offset, max_events, seconds, period, match, window_seconds):
    """Positions of the classic window: next events in the same match and period."""
    end = min(len(seconds), position + start_offset + max_events)
    span = np.arange(position + start_offset, end)
    same = (period[span] == period[position]) & (match[span] == match[position])
    span = span[same]
    elapsed = seconds[span] - seconds[position]
    return span[(elapsed >= 0) & (elapsed <= window_seconds)]


def _ordered(df):
    return bool(df["event_id"].is_monotonic_increasing) and bool(df["event_id"].is_unique)


def detect_defensive_transitions(df, team, window_seconds=8, max_events=8):
    if df.empty or not _ordered(df):
        return _original["detect_defensive_transitions"](df, team, window_seconds, max_events)
    team_rows, danger, progression, win, shot, xt, seconds, period, match = _context(df, team)
    rows = []
    loss_positions = np.flatnonzero(page._loss_mask(df, team).to_numpy())
    for position in loss_positions:
        loss = df.iloc[position]
        span = _window(position, 1, max_events, seconds, period, match, window_seconds)
        opp = span[~team_rows[span]]
        own = span[team_rows[span]]
        recovered = bool(win[own].any()) if len(own) else False
        shot_conceded = bool(shot[opp].any())
        box_entry = bool(danger[opp].any()) if len(opp) else False
        progressed = bool(progression[opp].any()) if len(opp) else False
        if recovered:
            outcome = "Recovered"
        elif shot_conceded:
            outcome = "Shot conceded"
        elif box_entry:
            outcome = "Box entry conceded"
        elif progressed:
            outcome = "Progression conceded"
        else:
            outcome = "Slowed"
        rows.append({
            "event_id": loss["event_id"], "match_id": loss.get("match_id", None),
            "match_label": loss.get("match_label", ""), "source_csv": loss.get("source_csv", ""),
            "team": team, "playerName": loss.get("playerName", ""), "type": loss.get("type", ""),
            "outcomeType": loss.get("outcomeType", ""), "period": loss.get("period", ""),
            "minute": loss["minute"], "second": loss["second"], "x": loss["x"], "y": loss["y"],
            "outcome": outcome, "opp_events": len(opp),
            "opp_xT": xt[opp].sum() if len(opp) else 0.0,
            "recovered": recovered, "shot_conceded": shot_conceded,
            "box_entry_conceded": box_entry, "progression_conceded": progressed,
        })
    return pd.DataFrame(rows)


def detect_attacking_transitions(df, team, window_seconds=10, max_events=8):
    if df.empty or not _ordered(df):
        return _original["detect_attacking_transitions"](df, team, window_seconds, max_events)
    team_rows, danger, progression, win, shot, xt, seconds, period, match = _context(df, team)
    rows = []
    for position in np.flatnonzero(win):
        recovery = df.iloc[position]
        span = _window(position, 0, max_events, seconds, period, match, window_seconds)
        own = span[team_rows[span]]
        took_shot = bool(shot[own].any())
        box_entry = bool(danger[own].any()) if len(own) else False
        progressed = bool(progression[own].any()) if len(own) else False
        retained = len(own) >= 3
        if took_shot:
            outcome = "Shot"
        elif box_entry:
            outcome = "Box entry"
        elif progressed:
            outcome = "Progression"
        elif retained:
            outcome = "Retained"
        else:
            outcome = "Stalled"
        rows.append({
            "event_id": recovery["event_id"], "match_id": recovery.get("match_id", None),
            "match_label": recovery.get("match_label", ""), "source_csv": recovery.get("source_csv", ""),
            "team": team, "playerName": recovery.get("playerName", ""), "type": recovery.get("type", ""),
            "outcomeType": recovery.get("outcomeType", ""), "period": recovery.get("period", ""),
            "minute": recovery["minute"], "second": recovery["second"], "x": recovery["x"], "y": recovery["y"],
            "outcome": outcome, "own_events": len(own),
            "xT_created": xt[own].sum() if len(own) else 0.0,
            "shot": took_shot, "box_entry": box_entry, "progression": progressed,
        })
    return pd.DataFrame(rows)


def install():
    """Use the fast detectors inside the copied Tactical functions."""
    page.detect_defensive_transitions = detect_defensive_transitions
    page.detect_attacking_transitions = detect_attacking_transitions
