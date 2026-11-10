"""Small helpers shared by the Analyst Room views (moved unchanged from the page)."""
from __future__ import annotations

import os

import pandas as pd

from .frames import PERIOD_MAP

HOME_COLOR = "#7ab4ff"
AWAY_COLOR = "#ff7351"

OUTCOME_ICON = {"Goal": "●", "SavedShot": "◉", "ShotOnPost": "◎",
                "BlockedShot": "■", "MissedShot": "✕"}
OUTCOME_LABEL = {"Goal": "[GOAL] GOAL", "SavedShot": "[SAVE] SAVED", "ShotOnPost": "[POST] POST",
                 "BlockedShot": "[DEF] BLOCKED", "MissedShot": "[ERR] MISSED"}
OUTCOME_CLASS = {"Goal": "badge badge-goal", "SavedShot": "badge badge-saved",
                 "ShotOnPost": "badge badge-post", "BlockedShot": "badge badge-blocked",
                 "MissedShot": "badge badge-missed"}

PITCH_ZONE_OPTIONS = ["", "Entire Left Side", "Left Wing", "Left Half Space", "Centre",
                      "Right Half Space", "Right Wing", "Entire Right Side"]


def safe_float(v):
    try:
        out = float(v)
        if pd.isna(out) or out == float("inf") or out == float("-inf"):
            return None
        return out
    except Exception:
        return None


def safe_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    try:
        return bool(int(v))
    except Exception:
        return False


def reclassify_shot(row):
    t = row.get("type", "")
    if t == "AttemptSaved":
        return "SavedShot"
    if t in ("MissedShots", "Attempt"):
        return "MissedShot"
    return t


def fmt_time(minute, second, period):
    p = PERIOD_MAP.get(period, 1)
    label = {1: "1H", 2: "2H", 3: "ET1", 4: "ET2", 5: "PSO"}.get(p, "UNK")
    return f"{minute}'{int(second):02d}\" {label}"


def filter_by_pitch_zone(df, selected_zone):
    from clipmaker_core import _effective_pitch_zone_series
    if df is None or df.empty or not selected_zone:
        return df
    zone_series = _effective_pitch_zone_series(df)
    combined_pitch_zones = {
        "Entire Left Side": ["Left Wing", "Left Half Space"],
        "Entire Right Side": ["Right Wing", "Right Half Space"],
    }
    if selected_zone in combined_pitch_zones:
        return df[zone_series.isin(combined_pitch_zones[selected_zone])]
    return df[zone_series == selected_zone]


def first_nonempty(df, columns):
    for col in columns:
        if col in df.columns:
            values = df[col].dropna().astype(str)
            values = values[values.str.strip() != ""]
            if not values.empty:
                return values.iloc[0].strip()
    return ""


def match_export_context(df):
    if df is None or df.empty:
        return ""
    match_name = first_nonempty(df, ["matchName"])
    if match_name.lower().endswith(".csv") or "_all_events" in match_name:
        match_name = os.path.basename(match_name)
        match_name = match_name.replace("whoscored_", "").replace("scoresway_", "")
        match_name = match_name.replace("_all_events.csv", "").replace(".csv", "")
        match_name = match_name.replace("_", " ")
    if not match_name:
        home = first_nonempty(df, ["homeTeam"])
        away = first_nonempty(df, ["awayTeam"])
        match_name = f"{home} vs {away}".strip(" vs ")

    match_date = first_nonempty(df, ["matchDate", "match_date", "date", "startTime", "kickOffTime", "dtStamp"])
    if match_date:
        match_date = match_date[:10]

    parts = [part for part in [match_name, match_date] if part]
    return " · ".join(parts)


def scope_line(*parts):
    cleaned = []
    for part in parts:
        text = str(part or "").strip()
        if text:
            cleaned.append(text)
    return " | ".join(cleaned)


def count_scope(count, singular="event", plural=None):
    irregular = {
        "pass": "passes",
        "entry": "entries",
        "penalty": "penalties",
    }
    plural = plural or irregular.get(singular, f"{singular}s")
    try:
        value = int(count)
    except (TypeError, ValueError):
        return ""
    return f"{value} {singular if value == 1 else plural}"


def zone_scope(pitch_zone="", depth_zone=""):
    return scope_line(
        pitch_zone or "Any pitch zone",
        depth_zone or "Any depth zone",
    )


def map_context(df_all, title, team="", player="", subset="", pitch_zone="", depth_zone="",
                count=None, unit="event", note=""):
    match = match_export_context(df_all)
    subtitle = scope_line(match, team, player, subset, zone_scope(pitch_zone, depth_zone), count_scope(count, unit))
    return {
        "context_title": title,
        "context_subtitle": subtitle,
        "context_note": note,
    }
