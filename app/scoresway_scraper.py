import asyncio
import json
import os
import re
from collections import Counter
from urllib.parse import urljoin

import numpy as np
import pandas as pd

from whoscored_scraper import (
    _apply_xt_and_progressive,
    _depth_zone,
    _in_box,
    _pitch_zone,
    _is_box_entry_pass,
    _is_box_entry_carry,
    _is_deep_completion,
    _is_diagonal_long_ball,
    _is_final_third_entry_pass,
    _is_final_third_entry_carry,
    _is_switch_of_play,
    save_scraped_match_csv,
)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/javascript,text/html,*/*;q=0.1",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.scoresway.com/",
}

EXPECTED_COLUMNS = [
    "minute", "second", "type", "outcomeType", "period", "playerName", "team",
    "playerId", "player_position", "shirtNumber",
    "x", "y", "endX", "endY", "goal_mouth_y", "goal_mouth_z",
    "is_key_pass", "is_cross", "is_long_ball", "is_switch_of_play",
    "is_diagonal_long_ball", "is_box_entry_pass", "is_deep_completion",
    "is_box_entry_carry", "is_final_third_entry_pass",
    "is_final_third_entry_carry", "is_throw_in", "is_goal_kick",
    "is_keeper_throw", "is_gk_hoof", "is_gk_kick_from_hands", "is_pull_back",
    "is_lay_off", "is_flick_on", "is_launch", "is_assist",
    "is_attacking_pass", "is_scramble", "is_corner_situation",
    "is_throw_in_sp", "is_shot_strong", "is_shot_weak",
    "is_individual_play", "is_follows_dribble", "is_1on1", "is_deflected",
    "is_hit_woodwork", "is_back_heel", "is_1on1_chip", "is_def_block",
    "is_last_line", "is_forced_out", "is_blocked_cross",
    "is_error_led_to_shot", "is_error_led_to_goal", "is_through_ball",
    "is_corner", "is_freekick", "is_header", "is_own_goal",
    "is_big_chance", "is_big_chance_shot", "is_gk_save", "is_penalty",
    "is_volley", "is_chipped", "is_direct_from_corner", "is_left_foot",
    "is_right_foot", "is_fast_break", "is_touch_in_box",
    "is_assist_throughball", "is_assist_cross", "is_assist_corner",
    "is_assist_freekick", "is_intentional_assist", "is_yellow_card",
    "is_red_card", "is_second_yellow", "is_nutmeg", "is_success_in_box",
    "pitch_zone", "depth_zone", "xT", "prog_pass", "prog_carry",
    "matchName", "homeTeam", "awayTeam", "matchDate",
]

BOOLEAN_COLUMNS = [c for c in EXPECTED_COLUMNS if c.startswith("is_")]
NUMERIC_COLUMNS = {
    "minute", "second", "x", "y", "endX", "endY", "goal_mouth_y",
    "goal_mouth_z", "shirtNumber", "xT", "prog_pass", "prog_carry",
}

TYPE_ID_TO_EVENT = {
    1: "Pass", 2: "OffsidePass", 3: "TakeOn", 4: "Foul", 5: "Out",
    6: "CornerAwarded", 7: "Tackle", 8: "Interception", 10: "Save",
    11: "Claim", 12: "Clearance", 13: "MissedShot", 14: "ShotOnPost",
    15: "SavedShot", 16: "Goal", 17: "Card", 18: "SubstitutionOff",
    19: "SubstitutionOn", 20: "PlayerRetired", 21: "PlayerReturns",
    27: "StartDelay", 28: "EndDelay", 30: "End", 32: "Start",
    34: "TeamSetUp", 35: "PlayerChangedPosition", 37: "CollectionEnd",
    40: "FormationChange", 41: "Punch", 43: "DeletedEvent", 44: "Aerial",
    45: "Challenge", 49: "BallRecovery", 50: "Dispossessed", 51: "Error",
    52: "KeeperPickup", 53: "CrossNotClaimed", 54: "Smother",
    55: "OffsideProvoked", 56: "ShieldBallOpp", 57: "FoulThrowIn",
    58: "PenaltyFaced", 59: "KeeperSweeper", 60: "ChanceMissed",
    61: "BallTouch", 64: "Resume", 65: "ContentiousRefereeDecision",
    66: "PossessionData", 67: "FiftyFifty", 68: "RefereeDropBall",
    69: "FailedToBlock", 70: "InjuryTimeAnnouncement", 72: "CaughtOffside",
    73: "OtherBallContact", 74: "BlockedPass", 80: "KeeperBallDrop",
    83: "ShieldBallChallenge",
}

QUALIFIER_RULES = {
    1: "is_long_ball", 2: "is_cross", 4: "is_through_ball",
    5: "is_freekick", 6: "is_corner", 9: "is_penalty", 15: "is_header",
    20: "is_right_foot", 23: "is_fast_break", 28: "is_own_goal",
    31: "is_yellow_card", 32: "is_second_yellow", 33: "is_red_card",
    72: "is_left_foot", 89: "is_1on1", 94: "is_def_block",
    96: "is_corner_situation", 107: "is_throw_in", 112: "is_scramble",
    113: "is_shot_strong", 114: "is_shot_weak", 123: "is_keeper_throw",
    124: "is_goal_kick", 133: "is_deflected", 138: "is_hit_woodwork",
    154: "is_intentional_assist", 155: "is_chipped", 156: "is_lay_off",
    157: "is_launch", 168: "is_flick_on", 169: "is_error_led_to_shot",
    170: "is_error_led_to_goal", 185: "is_blocked_cross",
    195: "is_pull_back", 196: "is_switch_of_play", 198: "is_gk_hoof",
    199: "is_gk_kick_from_hands", 214: "is_big_chance_shot",
    215: "is_individual_play", 254: "is_follows_dribble",
    261: "is_1on1_chip", 262: "is_back_heel",
    263: "is_direct_from_corner",
}

KNOWN_QUALIFIERS = set(QUALIFIER_RULES) | {22, 24, 25, 26, 82, 102, 103, 132, 140, 141, 146, 147, 210}
SHOT_TYPES = {"MissedShot", "ShotOnPost", "SavedShot", "Goal", "BlockedShot"}
PERIOD_MAP = {
    1: "FirstHalf",
    2: "SecondHalf",
    3: "FirstPeriodOfExtraTime",
    4: "SecondPeriodOfExtraTime",
    5: "PenaltyShootout",
}


class MatchContext:
    def __init__(self):
        self.home_team = "Home"
        self.away_team = "Away"
        self.match_name = "Scoresway Match"
        self.match_date = ""
        self.team_id_to_name = {}
        self.player_id_to_name = {}
        self.player_id_to_team_id = {}
        self.player_id_to_position = {}
        self.player_id_to_shirt_number = {}
        self.goalkeeper_player_ids = set()


def log_to_queue(log_queue, msg):
    log_queue.put({"type": "log", "msg": msg})


def get_first(obj, *keys, default=None):
    for key in keys:
        if isinstance(obj, dict) and key in obj and obj[key] is not None:
            return obj[key]
    return default


def to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def to_float(value, default=np.nan):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def extract_match_id(url):
    patterns = [
        r"/match/(?:view/)?([A-Za-z0-9]+)",
        r"/view/([A-Za-z0-9]+)",
        r"/([A-Za-z0-9]+)(?:/[^/?#]*)?(?:[?#].*)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_season_id(url):
    match = re.search(r"/soccer/[^/]+/([A-Za-z0-9]+)/match/", str(url))
    return match.group(1) if match else None


def parse_json_or_jsonp(text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("Empty PerformFeeds response")
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    start = text.find("(")
    end = text.rfind(")")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start + 1:end].strip())
    raise ValueError("Could not parse PerformFeeds response as JSON or JSONP")


def _iter_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_dicts(value)


def _iter_lists(obj):
    if isinstance(obj, list):
        yield obj
        for value in obj:
            yield from _iter_lists(value)
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_lists(value)


def normalize_qualifiers(raw_qualifiers):
    q = {}
    if not raw_qualifiers:
        return q

    if isinstance(raw_qualifiers, dict):
        for key, value in raw_qualifiers.items():
            try:
                q[int(key)] = value
            except Exception:
                continue
        return q

    if isinstance(raw_qualifiers, list):
        for item in raw_qualifiers:
            if not isinstance(item, dict):
                continue
            qid = (
                item.get("qualifierId")
                or item.get("id")
                or item.get("typeId")
                or get_first(item.get("type", {}), "id", "value")
            )
            value = item.get("value", item.get("qualifierValue", ""))
            try:
                q[int(qid)] = value
            except Exception:
                continue
    return q


def q_value(q, qid, default=None):
    return q.get(int(qid), default)


def normalize_outcome(value):
    if isinstance(value, dict):
        value = get_first(value, "displayName", "name", "value", "id")
    if value in [1, "1", True, "true", "True", "successful", "Successful", "success", "won"]:
        return "Successful"
    if value in [0, "0", False, "false", "False", "unsuccessful", "Unsuccessful", "fail", "lost"]:
        return "Unsuccessful"
    return str(value) if value is not None else ""


def normalize_period(value):
    if isinstance(value, dict):
        value = get_first(value, "id", "value", "periodId", "displayName")
    if isinstance(value, str):
        if value in PERIOD_MAP.values():
            return value
        try:
            return PERIOD_MAP.get(int(value), value)
        except Exception:
            return value
    return PERIOD_MAP.get(to_int(value, 1), "FirstHalf")


def _name_from_obj(obj):
    if not isinstance(obj, dict):
        return ""
    value = get_first(
        obj,
        "matchName", "knownName", "shortName", "name", "displayName",
        "firstName", "lastName",
        default="",
    )
    if value:
        return str(value)
    first = str(obj.get("firstName") or "").strip()
    last = str(obj.get("lastName") or "").strip()
    return f"{first} {last}".strip()


def _date_from_json(obj):
    for item in _iter_dicts(obj):
        for key in ("startTime", "matchDate", "date", "kickOffTime", "dtStamp", "localDate"):
            value = item.get(key) if isinstance(item, dict) else None
            if value and isinstance(value, str) and len(value) >= 10:
                match = re.search(r"\d{4}-\d{2}-\d{2}", value)
                return match.group(0) if match else value[:10]
    return ""


def build_match_context(match_json):
    context = MatchContext()
    context.match_date = _date_from_json(match_json)

    for obj in _iter_dicts(match_json):
        obj_id = get_first(obj, "contestantId", "teamId", "id", default="")
        name = _name_from_obj(obj)
        side = str(get_first(obj, "side", "position", "homeAway", default="")).lower()
        is_playerish = any(k in obj for k in ("playerId", "personId", "shirtNumber", "matchName"))
        is_teamish = bool(name and obj_id and (
            side in {"home", "away"}
            or (any(k in obj for k in ("contestantId", "teamId")) and not is_playerish)
            or obj.get("type") in {"team", "contestant"}
        ))
        if is_teamish:
            context.team_id_to_name[str(obj_id)] = name
            if side == "home":
                context.home_team = name
            elif side == "away":
                context.away_team = name

    for obj in _iter_dicts(match_json):
        pid = get_first(obj, "playerId", "personId", "player_id", "id", default="")
        name = _name_from_obj(obj)
        if not pid or not name:
            continue
        looks_player = any(k in obj for k in ("playerId", "personId", "shirtNumber", "position", "matchName"))
        if not looks_player:
            continue
        pid = str(pid)
        context.player_id_to_name[pid] = name
        team_id = get_first(obj, "contestantId", "teamId", default="")
        if team_id:
            context.player_id_to_team_id[pid] = str(team_id)
        pos = str(get_first(obj, "position", "positionName", "type", default="")).upper()
        if pos:
            context.player_id_to_position[pid] = str(get_first(obj, "position", "positionName", "type", default=""))
        shirt_number = get_first(obj, "shirtNumber", "jerseyNumber", "shirt", default="")
        if shirt_number != "":
            context.player_id_to_shirt_number[pid] = shirt_number
        if pos in {"GK", "GOALKEEPER"}:
            context.goalkeeper_player_ids.add(pid)

    for lineup in _iter_dicts(match_json):
        team_id = get_first(lineup, "contestantId", "teamId", default="")
        players = get_first(lineup, "player", "players", "lineup", default=None)
        if not team_id or not isinstance(players, list):
            continue
        for player in players:
            if not isinstance(player, dict):
                continue
            pid = get_first(player, "playerId", "personId", "id", default="")
            name = _name_from_obj(player)
            if pid and name:
                context.player_id_to_name[str(pid)] = name
                context.player_id_to_team_id[str(pid)] = str(team_id)
            pos = str(get_first(player, "position", "positionName", default="")).upper()
            if pid and pos:
                context.player_id_to_position[str(pid)] = str(get_first(player, "position", "positionName", default=""))
            shirt_number = get_first(player, "shirtNumber", "jerseyNumber", "shirt", default="")
            if pid and shirt_number != "":
                context.player_id_to_shirt_number[str(pid)] = shirt_number
            if pid and pos in {"GK", "GOALKEEPER"}:
                context.goalkeeper_player_ids.add(str(pid))

    if not context.home_team or context.home_team == "Home":
        context.home_team = next(iter(context.team_id_to_name.values()), "Home")
    if not context.away_team or context.away_team == "Away":
        teams = [v for v in context.team_id_to_name.values() if v != context.home_team]
        context.away_team = teams[0] if teams else "Away"
    context.match_name = f"{context.home_team} vs {context.away_team}"
    return context


def enrich_match_context_from_squads(context, squad_jsons, log=lambda msg: None):
    before = len(context.goalkeeper_player_ids)
    for squad_json in squad_jsons or []:
        for squad in _iter_dicts(squad_json):
            team_id = get_first(squad, "contestantId", "teamId", default="")
            team_name = get_first(squad, "contestantName", "contestantShortName", "contestantClubName", default="")
            if team_id and team_name:
                context.team_id_to_name[str(team_id)] = str(team_name)

        for player in _iter_dicts(squad_json):
            pid = get_first(player, "playerId", "personId", "id", default="")
            if not pid:
                continue
            looks_player = any(k in player for k in ("playerId", "personId", "id", "shirtNumber", "position", "matchName"))
            if not looks_player:
                continue
            pid = str(pid)
            name = _name_from_obj(player)
            if name:
                context.player_id_to_name[pid] = name
            team_id = get_first(player, "contestantId", "teamId", default="")
            if team_id:
                context.player_id_to_team_id[pid] = str(team_id)
            pos = str(get_first(player, "position", "positionName", default="")).strip()
            if pos:
                context.player_id_to_position[pid] = pos
                if pos.upper() in {"GK", "GOALKEEPER"}:
                    context.goalkeeper_player_ids.add(pid)
            shirt_number = get_first(player, "shirtNumber", "jerseyNumber", "shirt", default="")
            if shirt_number != "":
                context.player_id_to_shirt_number[pid] = shirt_number

    added = len(context.goalkeeper_player_ids) - before
    if added > 0:
        log(f"Loaded {len(context.goalkeeper_player_ids)} goalkeeper IDs from Scoresway squad feeds.")
    return context


def extract_event_list(event_json):
    best = []
    for candidate in _iter_lists(event_json):
        if not candidate or not all(isinstance(item, dict) for item in candidate[: min(5, len(candidate))]):
            continue
        score = 0
        for item in candidate[: min(20, len(candidate))]:
            if any(k in item for k in ("typeId", "type_id", "eventTypeId")):
                score += 2
            if any(k in item for k in ("timeMin", "minute", "min", "periodId")):
                score += 1
            if any(k in item for k in ("contestantId", "teamId", "playerId", "personId")):
                score += 1
        if score and len(candidate) > len(best):
            best = candidate
    return best


def make_empty_row():
    row = {}
    for col in EXPECTED_COLUMNS:
        if col in BOOLEAN_COLUMNS:
            row[col] = False
        elif col in NUMERIC_COLUMNS:
            row[col] = np.nan
        else:
            row[col] = ""
    row["minute"] = 0
    row["second"] = 0
    return row


def resolve_player_name(event, context, player_id):
    return (
        get_first(event, "playerName", "player_name", "personName", default="")
        or _name_from_obj(event.get("player", {}))
        or context.player_id_to_name.get(str(player_id), "")
    )


def resolve_team_name(event, context, team_id, player_id):
    return (
        get_first(event, "teamName", "contestantName", default="")
        or context.team_id_to_name.get(str(team_id), "")
        or context.team_id_to_name.get(context.player_id_to_team_id.get(str(player_id), ""), "")
    )


def apply_qualifier_flags(row, q, event_type, outcome, home_team):
    for qid, column in QUALIFIER_RULES.items():
        if qid in q and column in row:
            row[column] = True

    q210 = to_int(q_value(q, 210), default=None)
    row["is_key_pass"] = q210 in {13, 14, 15, 16}
    row["is_assist"] = q210 == 16

    row["is_cross"] = row["is_cross"] and event_type == "Pass"
    row["is_long_ball"] = row["is_long_ball"] and event_type == "Pass"
    row["is_corner"] = row["is_corner"] and event_type == "Pass"
    row["is_freekick"] = row["is_freekick"] and event_type == "Pass"
    row["is_throw_in"] = row["is_throw_in"] and event_type == "Pass"
    row["is_goal_kick"] = row["is_goal_kick"] and event_type == "Pass"
    row["is_keeper_throw"] = row["is_keeper_throw"] and event_type == "Pass"
    row["is_gk_hoof"] = row["is_gk_hoof"] and event_type == "Pass"
    row["is_gk_kick_from_hands"] = row["is_gk_kick_from_hands"] and event_type == "Pass"
    row["is_pull_back"] = row["is_pull_back"] and event_type == "Pass"
    row["is_launch"] = row["is_launch"] and event_type == "Pass"
    row["is_attacking_pass"] = row["is_attacking_pass"] and event_type == "Pass"

    row["is_switch_of_play"] = (
        row["is_switch_of_play"]
        or (
            event_type == "Pass"
            and row["is_long_ball"]
            and _is_switch_of_play(row["y"], row["endY"], home_team)
        )
    )
    row["is_diagonal_long_ball"] = (
        event_type == "Pass"
        and row["is_long_ball"]
        and _is_diagonal_long_ball(row["x"], row["y"], row["endX"], row["endY"])
    )
    row["is_box_entry_pass"] = (
        event_type == "Pass"
        and _is_box_entry_pass(
            row["x"], row["y"], row["endX"], row["endY"],
            row["is_corner"], row["is_freekick"],
        )
    )
    row["is_deep_completion"] = (
        event_type == "Pass"
        and _is_deep_completion(
            row["endX"], row["endY"], row["is_cross"],
            row["is_corner"], row["is_freekick"], outcome,
        )
    )
    row["is_final_third_entry_pass"] = (
        event_type == "Pass"
        and _is_final_third_entry_pass(
            row["x"], row["endX"], row["is_corner"], row["is_freekick"],
        )
    )
    row["is_touch_in_box"] = _in_box(row["x"], row["y"])
    row["is_success_in_box"] = event_type == "TakeOn" and outcome == "Successful" and _in_box(row["x"], row["y"])
    row["is_assist_cross"] = row["is_assist"] and row["is_cross"]
    row["is_assist_corner"] = row["is_assist"] and row["is_corner"]
    row["is_assist_freekick"] = row["is_assist"] and row["is_freekick"]
    row["is_assist_throughball"] = row["is_assist"] and row["is_through_ball"]


def is_scoresway_gk_save(event_type, player_id, qualifiers, context):
    if event_type != "Save":
        return False
    if 94 in qualifiers:
        return False
    if player_id in context.goalkeeper_player_ids:
        return True
    return not context.goalkeeper_player_ids


SCORESWAY_NON_CARRY_EVENT_TYPES = {
    "BlockedShot", "Card", "CollectionEnd", "CornerAwarded", "DeletedEvent",
    "End", "EndDelay", "Foul", "FoulThrowIn", "FormationChange", "Goal",
    "MissedShot", "MissedShots", "Out", "PlayerChangedPosition",
    "PlayerOff", "PlayerOn", "PlayerRetired", "PlayerReturns",
    "RefereeDropBall", "SubstitutionOff", "SubstitutionOn",
    "SavedShot", "ShotOnPost", "Start", "StartDelay", "Substitution",
    "TeamSetUp",
}

SCORESWAY_NON_CARRY_RESTART_FLAGS = {
    "is_corner", "is_freekick", "is_throw_in", "is_goal_kick", "is_keeper_throw",
    "is_gk_hoof", "is_gk_kick_from_hands", "is_penalty",
}


def _truthy_flag(value):
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _is_scoresway_dead_ball_or_restart_event(event):
    if event.get("type", "") in SCORESWAY_NON_CARRY_EVENT_TYPES:
        return True
    return any(_truthy_flag(event.get(flag, False)) for flag in SCORESWAY_NON_CARRY_RESTART_FLAGS)


def insert_scoresway_ball_carries(events_df, log_func=None, home_team=None):
    if log_func is None:
        log_func = lambda x: None

    if home_team is None:
        if "homeTeam" in events_df.columns:
            ht = events_df["homeTeam"].dropna()
            home_team = ht.iloc[0] if len(ht) > 0 else ""
        else:
            home_team = ""

    try:
        match_events = events_df.copy().reset_index(drop=True)
        if "cumulative_mins" not in match_events.columns:
            match_events["cumulative_mins"] = match_events["minute"] + (match_events["second"] / 60)

        for col in ["x", "y", "endX", "endY", "minute", "second"]:
            if col in match_events.columns:
                match_events[col] = pd.to_numeric(match_events[col], errors="coerce")

        match_events.loc[match_events["endX"].isna(), "endX"] = match_events.loc[match_events["endX"].isna(), "x"]
        match_events.loc[match_events["endY"].isna(), "endY"] = match_events.loc[match_events["endY"].isna(), "y"]

        match_carries = pd.DataFrame()
        for idx in range(len(match_events) - 1):
            match_event = match_events.iloc[idx]
            prev_evt_team = match_event.get("team", "")
            next_evt_idx = idx + 1
            init_next_evt = match_events.iloc[next_evt_idx]
            incorrect_next_evt = True

            while incorrect_next_evt and next_evt_idx < len(match_events):
                next_evt = match_events.iloc[next_evt_idx]
                if (
                    next_evt.get("type") == "TakeOn"
                    and next_evt.get("outcomeType") == "Successful"
                ):
                    incorrect_next_evt = True
                elif (
                    (
                        next_evt.get("type") == "TakeOn"
                        and next_evt.get("outcomeType") == "Unsuccessful"
                    )
                    or (next_evt.get("type") == "Foul")
                    or (next_evt.get("type") == "Card")
                ):
                    incorrect_next_evt = True
                else:
                    incorrect_next_evt = False
                next_evt_idx += 1

            if next_evt_idx >= len(match_events):
                continue

            next_evt = match_events.iloc[next_evt_idx - 1]
            try:
                dx = 105 * (match_event.get("endX", 0) - next_evt.get("x", 0)) / 100
                dy = 68 * (match_event.get("endY", 0) - next_evt.get("y", 0)) / 100
                dt = 60 * (
                    next_evt.get("cumulative_mins", 0) - match_event.get("cumulative_mins", 0)
                )
            except (TypeError, ValueError):
                continue

            carry_distance_sq = dx**2 + dy**2
            valid_carry = (
                prev_evt_team == next_evt.get("team", "")
                and not _is_scoresway_dead_ball_or_restart_event(match_event)
                and not _is_scoresway_dead_ball_or_restart_event(next_evt)
                and match_event.get("type") != "BallTouch"
                and carry_distance_sq >= 3.0**2
                and carry_distance_sq <= 60.0**2
                and dt >= 1.0
                and dt <= 10.0
                and match_event.get("period") == next_evt.get("period")
            )

            if valid_carry:
                carry = {
                    "minute": int(np.floor((((init_next_evt.get("minute", 0) * 60 + init_next_evt.get("second", 0))
                                             + (match_event.get("minute", 0) * 60 + match_event.get("second", 0))) / 2) / 60)),
                    "second": int((((init_next_evt.get("minute", 0) * 60 + init_next_evt.get("second", 0))
                                    + (match_event.get("minute", 0) * 60 + match_event.get("second", 0))) / 2) % 60),
                    "type": "Carry",
                    "outcomeType": "Successful",
                    "period": next_evt.get("period", ""),
                    "playerName": next_evt.get("playerName", ""),
                    "team": next_evt.get("team", ""),
                    "x": match_event.get("endX", ""),
                    "y": match_event.get("endY", ""),
                    "endX": next_evt.get("x", ""),
                    "endY": next_evt.get("y", ""),
                    "goal_mouth_y": "",
                    "goal_mouth_z": "",
                    "is_key_pass": False,
                    "is_cross": False,
                    "is_long_ball": False,
                    "is_switch_of_play": False,
                    "is_diagonal_long_ball": False,
                    "is_box_entry_pass": False,
                    "is_deep_completion": False,
                    "is_box_entry_carry": _is_box_entry_carry(
                        match_event.get("endX", ""), match_event.get("endY", ""),
                        next_evt.get("x", ""), next_evt.get("y", ""),
                    ),
                    "is_final_third_entry_pass": False,
                    "is_final_third_entry_carry": _is_final_third_entry_carry(
                        match_event.get("endX", ""), next_evt.get("x", ""),
                    ),
                    "is_through_ball": False,
                    "is_corner": False,
                    "is_freekick": False,
                    "is_header": False,
                    "is_own_goal": False,
                    "is_big_chance": False,
                    "is_big_chance_shot": False,
                    "is_gk_save": False,
                    "is_penalty": False,
                    "is_volley": False,
                    "is_chipped": False,
                    "is_direct_from_corner": False,
                    "is_left_foot": False,
                    "is_right_foot": False,
                    "is_fast_break": False,
                    "is_touch_in_box": False,
                    "is_assist_throughball": False,
                    "is_assist_cross": False,
                    "is_assist_corner": False,
                    "is_assist_freekick": False,
                    "is_intentional_assist": False,
                    "is_yellow_card": False,
                    "is_red_card": False,
                    "is_second_yellow": False,
                    "is_nutmeg": False,
                    "is_success_in_box": False,
                    "pitch_zone": _pitch_zone(match_event.get("endY", ""), flip=(home_team != "")),
                    "depth_zone": _depth_zone(match_event.get("endX", "")),
                    "xT": np.nan,
                    "prog_pass": np.nan,
                    "prog_carry": np.nan,
                    "matchName": next_evt.get("matchName", ""),
                    "homeTeam": next_evt.get("homeTeam", ""),
                    "awayTeam": next_evt.get("awayTeam", ""),
                    "matchDate": next_evt.get("matchDate", ""),
                }
                match_carries = pd.concat([match_carries, pd.DataFrame([carry])], ignore_index=True, sort=False)

        if len(match_carries) > 0:
            result_df = pd.concat([events_df, match_carries], ignore_index=True, sort=False)
            result_df = result_df.sort_values(["period", "minute", "second"]).reset_index(drop=True)
            log_func(f"  Inserted {len(match_carries)} Scoresway synthetic Carry events.")
            return result_df
    except Exception as exc:
        log_func(f"  Warning: Could not insert Scoresway carry events: {exc}")
    return events_df


def enforce_expected_schema(df):
    df = df.copy()
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            if col in BOOLEAN_COLUMNS:
                df[col] = False
            elif col in NUMERIC_COLUMNS:
                df[col] = np.nan
            else:
                df[col] = ""

    for col in BOOLEAN_COLUMNS:
        df[col] = df[col].fillna(False).astype(bool)
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["minute"] = df["minute"].fillna(0).astype(int)
    df["second"] = df["second"].fillna(0).astype(int)
    return df[EXPECTED_COLUMNS]


def reclassify_shots_and_saves(df, context):
    df = df.copy()
    keeper_save_names = set(
        df.loc[(df["type"] == "Save") & (df["is_gk_save"]), "playerName"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    keeper_save_names.discard("")
    if keeper_save_names:
        df.loc[
            (df["type"] == "Save")
            & df["playerName"].astype(str).str.strip().isin(keeper_save_names),
            "is_gk_save",
        ] = True

    save_events = df[df["type"] == "Save"][
        ["minute", "second", "period", "is_gk_save", "is_def_block"]
    ].copy()
    ball_touches = df[df["type"] == "BallTouch"][
        ["minute", "second", "period", "team"]
    ].copy()

    def paired_save(row):
        minute = int(row["minute"])
        second = int(row["second"])
        period = str(row["period"])
        return save_events[
            (save_events["minute"].astype(int) == minute)
            & (save_events["period"].astype(str) == period)
            & (save_events["second"].astype(int).isin([second, second + 1]))
        ]

    def followed_by_own_ball_touch(row):
        minute = int(row["minute"])
        second = int(row["second"])
        period = str(row["period"])
        team = str(row.get("team", ""))
        touches = ball_touches[
            (ball_touches["minute"].astype(int) == minute)
            & (ball_touches["period"].astype(str) == period)
            & (ball_touches["second"].astype(int).isin([second + 1, second + 2]))
            & (ball_touches["team"].astype(str) == team)
        ]
        return not touches.empty

    def shot_type(row):
        if row["type"] not in {"SavedShot", "BlockedShot"}:
            return row["type"]
        paired = paired_save(row)
        if not paired.empty and paired["is_gk_save"].astype(bool).any():
            return "SavedShot"
        if not paired.empty and (
            (~paired["is_gk_save"].astype(bool)).any()
            or paired["is_def_block"].astype(bool).any()
        ):
            return "BlockedShot"
        if followed_by_own_ball_touch(row):
            return "BlockedShot"
        return row["type"]

    def save_type(row):
        if row["type"] != "Save":
            return row["type"]
        return "Save" if row["is_gk_save"] else "Block"

    df["type"] = df.apply(shot_type, axis=1)
    df["type"] = df.apply(save_type, axis=1)
    return df


def normalise_scoresway_events(match_json, event_json, app_dir, enrich_xg=True, log=lambda msg: None, squad_jsons=None):
    context = build_match_context(match_json)
    enrich_match_context_from_squads(context, squad_jsons, log=log)
    raw_events = extract_event_list(event_json)
    if not raw_events:
        raise ValueError("No PerformFeeds event list found.")

    unknown_type_ids = Counter()
    unknown_qualifier_ids = Counter()
    unresolved_players = 0
    unresolved_teams = 0
    rows = []

    for event in raw_events:
        q = normalize_qualifiers(get_first(event, "qualifiers", "qualifier", "q", default=None))
        unknown_qualifier_ids.update(qid for qid in q if qid not in KNOWN_QUALIFIERS)

        type_id = to_int(get_first(event, "typeId", "type_id", "eventTypeId"), default=-1)
        event_type = TYPE_ID_TO_EVENT.get(type_id)
        if event_type is None:
            event_type = f"Unknown_{type_id}"
            unknown_type_ids[type_id] += 1

        outcome = normalize_outcome(get_first(event, "outcome", "outcomeType", "outcomeId", "outcomeValue"))
        player_id = str(get_first(event, "playerId", "personId", "player_id", default=""))
        team_id = str(get_first(event, "contestantId", "teamId", "team_id", default=""))
        player_name = resolve_player_name(event, context, player_id)
        team_name = resolve_team_name(event, context, team_id, player_id)
        if not player_name and player_id:
            unresolved_players += 1
        if not team_name:
            unresolved_teams += 1

        if event_type == "SavedShot" and 82 in q:
            event_type = "BlockedShot"

        row = make_empty_row()
        row.update({
            "minute": to_int(get_first(event, "timeMin", "minute", "min")),
            "second": to_int(get_first(event, "timeSec", "second", "sec")),
            "type": event_type,
            "outcomeType": outcome,
            "period": normalize_period(get_first(event, "periodId", "period", "period_id")),
            "playerName": player_name,
            "team": team_name,
            "playerId": player_id,
            "player_position": context.player_id_to_position.get(str(player_id), ""),
            "shirtNumber": context.player_id_to_shirt_number.get(str(player_id), np.nan),
            "x": to_float(get_first(event, "x", "xCoord", "x_coordinate")),
            "y": to_float(get_first(event, "y", "yCoord", "y_coordinate")),
            "endX": to_float(q_value(q, 140)),
            "endY": to_float(q_value(q, 141)),
            "goal_mouth_y": to_float(q_value(q, 102)),
            "goal_mouth_z": to_float(q_value(q, 103)),
            "is_gk_save": is_scoresway_gk_save(event_type, player_id, q, context),
            "is_big_chance": 214 in q,
            "pitch_zone": "",
            "depth_zone": "",
            "matchName": context.match_name,
            "homeTeam": context.home_team,
            "awayTeam": context.away_team,
            "matchDate": context.match_date,
        })
        if np.isnan(row["endX"]):
            row["endX"] = row["x"]
        if np.isnan(row["endY"]):
            row["endY"] = row["y"]

        apply_qualifier_flags(row, q, event_type, outcome, context.home_team)
        row["pitch_zone"] = "" if np.isnan(row["y"]) else _pitch_zone(row["y"], flip=(context.home_team != ""))
        row["depth_zone"] = "" if np.isnan(row["x"]) else _depth_zone(row["x"])
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("No events were normalized from PerformFeeds data.")

    period_order = {
        "FirstHalf": 1, "SecondHalf": 2,
        "FirstPeriodOfExtraTime": 3, "ExtraTimeFirstHalf": 3,
        "SecondPeriodOfExtraTime": 4, "ExtraTimeSecondHalf": 4,
        "PenaltyShootout": 5,
    }
    df["_period_order"] = df["period"].map(period_order).fillna(99)
    df = df.sort_values(["_period_order", "minute", "second"]).drop(columns=["_period_order"]).reset_index(drop=True)
    df = reclassify_shots_and_saves(df, context)

    log(f"Built base Scoresway dataframe with {len(df)} rows.")
    if enrich_xg:
        df = _apply_xt_and_progressive(
            df,
            app_dir,
            log,
            carry_inserter=insert_scoresway_ball_carries,
        )

    for col in ("pitch_zone", "depth_zone"):
        if col not in df.columns:
            df[col] = ""
    df["pitch_zone"] = df.apply(
        lambda row: _pitch_zone(row.get("y", ""), flip=(context.home_team != "")) if row.get("y", "") == row.get("y", "") else "",
        axis=1,
    )
    df["depth_zone"] = df["x"].apply(_depth_zone)
    df = enforce_expected_schema(df)

    if unknown_type_ids:
        summary = ", ".join(f"{tid} x{count}" for tid, count in unknown_type_ids.most_common())
        log(f"Warning: Unknown Scoresway/Opta event typeIds detected: {summary}")
    if unknown_qualifier_ids:
        summary = ", ".join(f"{qid} x{count}" for qid, count in unknown_qualifier_ids.most_common(20))
        log(f"Info: Unmapped Scoresway qualifier IDs detected: {summary}")
    if unresolved_players:
        log(f"Warning: Could not resolve player name for {unresolved_players} events.")
    if unresolved_teams:
        log(f"Warning: Could not resolve team name for {unresolved_teams} events.")

    return df, context.home_team, context.away_team, context.match_name


def _solve_scoresway_interstitial(session, url, html):
    if "bm-verify" not in html or "/_sec/verify" not in html:
        return html

    i_match = re.search(r"var\s+i\s*=\s*(\d+)", html)
    parts_match = re.search(r'var\s+j\s*=\s*i\s*\+\s*Number\("(\d+)"\s*\+\s*"(\d+)"\)', html)
    bm_match = re.search(r'xhr\.send\(JSON\.stringify\(\{"bm-verify":\s*"([^"]+)"', html)
    if not (i_match and parts_match and bm_match):
        return html

    pow_value = int(i_match.group(1)) + int(parts_match.group(1) + parts_match.group(2))
    payload = {"bm-verify": bm_match.group(1), "pow": pow_value}
    verify_url = urljoin(url, "/_sec/verify?provider=interstitial")
    session.post(
        verify_url,
        json=payload,
        headers={"Content-Type": "application/json", "Referer": url},
        timeout=30,
    )
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def _fetch_url(url):
    try:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome120")
    except Exception:
        import requests as cffi_requests
        session = cffi_requests.Session()
    session.headers.update(HEADERS)
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return _solve_scoresway_interstitial(session, url, response.text)


def discover_scoresway_feed_urls(url, log=lambda msg: None):
    html = _fetch_url(url)
    feed_re = re.compile(r"https?://api\.performfeeds\.com/soccerdata/(match|matchevent)/[^\"'\\)<>\s]+")
    rel_re = re.compile(r"/soccerdata/(match|matchevent)/[^\"'\\)<>\s]+")
    found = {"match": None, "matchevent": None}

    for match in feed_re.finditer(html):
        kind = match.group(1)
        found[kind] = found[kind] or match.group(0)
    for match in rel_re.finditer(html):
        kind = match.group(1)
        found[kind] = found[kind] or urljoin("https://api.performfeeds.com", match.group(0))

    if found["match"] and found["matchevent"]:
        log("Static PerformFeeds URL discovery succeeded.")
        return found

    outlet_match = re.search(r'sdapi_outlet_key:\s*"([^"]+)"', html)
    widget_match = re.search(r'<opta-widget[^>]+match="([^"]+)"', html, re.I)
    outlet_key = outlet_match.group(1) if outlet_match else ""
    match_id = widget_match.group(1) if widget_match else extract_match_id(url)
    if outlet_key and match_id:
        base = "https://api.performfeeds.com/soccerdata"
        found["match"] = f"{base}/match/{outlet_key}/{match_id}?_rt=c&live=yes&_lcl=en&_fmt=json"
        found["matchevent"] = f"{base}/matchevent/{outlet_key}/{match_id}?_rt=c&_lcl=en&_fmt=json"
        log("Static Opta widget config discovery succeeded.")
    return found


def extract_outlet_key_from_feed_url(feed_url):
    match = re.search(r"/soccerdata/(?:match|matchevent)/([^/?#]+)/", str(feed_url or ""))
    return match.group(1) if match else None


def fetch_scoresway_squad_data(url, context, feeds=None, log=lambda msg: None):
    season_id = extract_season_id(url)
    outlet_key = extract_outlet_key_from_feed_url((feeds or {}).get("match"))
    if not season_id:
        log("Info: Could not derive Scoresway season ID for squad feed enrichment.")
        return []
    if not outlet_key:
        log("Info: Could not derive Scoresway outlet key for squad feed enrichment.")
        return []

    team_ids = []
    for team_id in context.team_id_to_name:
        if team_id and team_id not in team_ids:
            team_ids.append(team_id)

    squad_jsons = []
    for team_id in team_ids:
        squad_url = (
            "https://api.performfeeds.com/soccerdata/squads/"
            f"{outlet_key}?tmcl={season_id}&ctst={team_id}&_rt=c&_lcl=en&_fmt=json"
        )
        try:
            squad_text = _fetch_url(squad_url)
            squad_jsons.append(parse_json_or_jsonp(squad_text))
            team_name = context.team_id_to_name.get(team_id, team_id)
            log(f"Loaded Scoresway squad feed for {team_name}.")
        except Exception as exc:
            team_name = context.team_id_to_name.get(team_id, team_id)
            log(f"Info: Could not load Scoresway squad feed for {team_name}: {exc}")
    return squad_jsons


async def _discover_with_playwright_async(url, match_id=None, log=lambda msg: None):
    from playwright.async_api import async_playwright

    captured = {"match": None, "matchevent": None}
    tasks = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(extra_http_headers=HEADERS)

        async def capture_response(response):
            response_url = response.url
            kind = None
            if "api.performfeeds.com/soccerdata/matchevent/" in response_url:
                kind = "matchevent"
            elif "api.performfeeds.com/soccerdata/match/" in response_url:
                kind = "match"
            if not kind:
                return
            if match_id and not response_url.rstrip("/").split("?")[0].endswith(match_id):
                return
            try:
                captured[kind] = await response.text()
                log(f"Captured {kind} feed.")
            except Exception:
                pass

        page.on("response", lambda response: tasks.append(asyncio.create_task(capture_response(response))))
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()
    return captured["match"], captured["matchevent"]


def discover_with_playwright(url, match_id=None, log=lambda msg: None):
    return asyncio.run(_discover_with_playwright_async(url, match_id=match_id, log=log))


def fetch_scoresway_feed_data(url, log=lambda msg: None):
    match_id = extract_match_id(url)
    if match_id:
        log(f"Detected Scoresway match ID: {match_id}")

    log("Trying static PerformFeeds URL discovery...")
    feeds = {}
    try:
        feeds = discover_scoresway_feed_urls(url, log=log)
    except Exception as exc:
        log(f"Static discovery failed: {exc}")

    match_text = None
    event_text = None
    if feeds.get("match") and feeds.get("matchevent"):
        match_text = _fetch_url(feeds["match"])
        event_text = _fetch_url(feeds["matchevent"])
    else:
        log("Trying Playwright network capture...")
        try:
            match_text, event_text = discover_with_playwright(url, match_id=match_id, log=log)
        except Exception as exc:
            raise ValueError(f"Could not locate Scoresway PerformFeeds data: {exc}") from exc

    if not match_text and not event_text:
        raise ValueError(
            "Could not locate Scoresway PerformFeeds data for this URL. "
            "Confirm the page loads match and matchevent requests in a browser."
        )
    if not match_text:
        raise ValueError("Found event feed but not match metadata feed. Player/team names may be incomplete.")
    if not event_text:
        raise ValueError("Found match metadata feed but not event data feed. The event feed may not be available for this match.")
    return match_text, event_text, feeds


def scrape_scoresway(url, log_queue, app_dir, enrich_xg=True):
    def log(msg):
        log_to_queue(log_queue, msg)

    try:
        log(f"Starting Scoresway scrape: {url}")
        match_text, event_text, feeds = fetch_scoresway_feed_data(url, log=log)
        log("Parsed match JSON.")
        match_json = parse_json_or_jsonp(match_text)
        squad_jsons = []
        try:
            squad_context = build_match_context(match_json)
            squad_jsons = fetch_scoresway_squad_data(url, squad_context, feeds=feeds, log=log)
        except Exception as exc:
            log(f"Info: Scoresway squad enrichment skipped: {exc}")
        log("Parsed matchevent JSON.")
        event_json = parse_json_or_jsonp(event_text)
        df, home_team, away_team, match_name = normalise_scoresway_events(
            match_json, event_json, app_dir, enrich_xg=enrich_xg, log=log, squad_jsons=squad_jsons
        )
        log(f"Final Scoresway dataframe: {len(df)} rows, {len(df.columns)} columns.")
        log_queue.put({
            "type": "data",
            "df": df,
            "home_team": home_team,
            "away_team": away_team,
            "match_name": match_name,
            "source": "scoresway",
        })
        log_queue.put({"type": "done"})
    except Exception as exc:
        log_queue.put({"type": "log", "msg": f"ERROR: {exc}"})
        log_queue.put({"type": "error", "msg": str(exc)})


__all__ = [
    "EXPECTED_COLUMNS",
    "TYPE_ID_TO_EVENT",
    "QUALIFIER_RULES",
    "parse_json_or_jsonp",
    "normalize_qualifiers",
    "normalise_scoresway_events",
    "scrape_scoresway",
    "save_scraped_match_csv",
]
