"""Deterministic synthetic match used as the committed analysis parity oracle.

Real scraped match files stay out of the repository (``match data/`` is
ignored). This generator mirrors the scraped column schema and approximate
event mix so that every Analyst Room and Tactical Lab tab and mode has data,
including extra time and a penalty shootout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HOME, AWAY = "Northbridge", "Southport"

# Approximate per-match event mix observed in scraped WhoScored files.
EVENT_WEIGHTS = {
    "Pass": 895, "Carry": 350, "BallRecovery": 63, "Aerial": 58, "BallTouch": 58,
    "Clearance": 48, "Foul": 29, "Tackle": 21, "Interception": 17, "CornerAwarded": 16,
    "BlockedPass": 15, "Dispossessed": 14, "TakeOn": 13, "KeeperPickup": 13,
    "SavedShot": 12, "Save": 12, "Block": 8, "BlockedShot": 7, "Challenge": 6,
    "MissedShot": 6, "Card": 4, "Claim": 5, "Goal": 4, "OffsidePass": 3, "Error": 3,
    "Smother": 2, "ShotOnPost": 1, "Punch": 2,
}
SHOTS = {"Goal", "SavedShot", "MissedShot", "BlockedShot", "ShotOnPost"}
KEEPER = {"Save", "KeeperPickup", "Claim", "Smother", "Punch"}

FLAG_COLUMNS = [
    "is_key_pass", "is_cross", "is_long_ball", "is_switch_of_play", "is_diagonal_long_ball",
    "is_box_entry_pass", "is_deep_completion", "is_box_entry_carry", "is_final_third_entry_pass",
    "is_final_third_entry_carry", "is_throw_in", "is_goal_kick", "is_keeper_throw", "is_gk_hoof",
    "is_gk_kick_from_hands", "is_pull_back", "is_lay_off", "is_flick_on", "is_launch", "is_assist",
    "is_attacking_pass", "is_scramble", "is_corner_situation", "is_throw_in_sp", "is_shot_strong",
    "is_shot_weak", "is_individual_play", "is_follows_dribble", "is_1on1", "is_deflected",
    "is_hit_woodwork", "is_back_heel", "is_1on1_chip", "is_def_block", "is_last_line",
    "is_forced_out", "is_blocked_cross", "is_error_led_to_shot", "is_error_led_to_goal",
    "is_through_ball", "is_corner", "is_freekick", "is_header", "is_own_goal", "is_big_chance",
    "is_big_chance_shot", "is_gk_save", "is_penalty", "is_volley", "is_chipped",
    "is_direct_from_corner", "is_left_foot", "is_right_foot", "is_fast_break", "is_touch_in_box",
    "is_assist_throughball", "is_assist_cross", "is_assist_corner", "is_assist_freekick",
    "is_intentional_assist", "is_yellow_card", "is_red_card", "is_second_yellow", "is_nutmeg",
    "is_success_in_box",
]

PERIODS = [  # (name, first minute, last minute, share of events)
    ("FirstHalf", 0, 47, .40), ("SecondHalf", 45, 94, .42),
    ("FirstPeriodOfExtraTime", 90, 106, .09), ("SecondPeriodOfExtraTime", 105, 121, .09),
]


def _pitch_zone(y):
    return ("Right Wing" if y < 18 else "Right Half Space" if y < 37 else "Centre" if y < 63
            else "Left Half Space" if y < 82 else "Left Wing")


def _depth_zone(x):
    return "Defensive Third" if x < 33.4 else "Middle Third" if x < 66.7 else "Attacking Third"


def build_fixture(events: int = 1400, seed: int = 20261109, home: str = HOME, away: str = AWAY) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    names = list(EVENT_WEIGHTS)
    weights = np.array(list(EVENT_WEIGHTS.values()), dtype=float)
    players = {team: [f"{team} {role}" for role in
                      ("Keeper", "Back A", "Back B", "Back C", "Back D", "Mid A", "Mid B", "Mid C",
                       "Wing A", "Wing B", "Striker")] for team in (home, away)}
    rows = []
    for period, start, end, share in PERIODS:
        count = int(events * share)
        clock = np.sort(rng.uniform(start * 60, end * 60, count))
        possession = home
        for seconds in clock:
            if rng.random() < .12:
                possession = away if possession == home else home
            event = names[rng.choice(len(names), p=weights / weights.sum())]
            team = possession if event not in {"Tackle", "Interception", "Clearance", "Save", "Claim",
                                               "Punch", "Smother", "KeeperPickup", "Block"} else (
                away if possession == home else home)
            player = players[team][0] if event in KEEPER else players[team][int(rng.integers(1, 11))]
            x = float(rng.uniform(80, 99)) if event in SHOTS else float(rng.uniform(1, 30)) if event in KEEPER else float(rng.uniform(2, 98))
            y = float(rng.uniform(30, 70)) if event in SHOTS else float(rng.uniform(2, 98))
            end_x = min(100.0, x + float(rng.normal(12, 14))) if event in {"Pass", "Carry"} else (100.0 if event in SHOTS else np.nan)
            end_y = float(np.clip(y + rng.normal(0, 16), 0, 100)) if event in {"Pass", "Carry"} else (float(rng.uniform(45, 55)) if event in SHOTS else np.nan)
            row = {
                "minute": int(seconds // 60), "second": int(seconds % 60), "type": event,
                "outcomeType": "Successful" if rng.random() < (.84 if event == "Pass" else .65) else "Unsuccessful",
                "period": period, "playerName": player, "team": team, "playerId": players[team].index(player) + (100 if team == away else 0),
                "player_position": "GK" if player.endswith("Keeper") else "DC" if "Back" in player else "MC" if "Mid" in player else "FW",
                "shirtNumber": players[team].index(player) + 1,
                "x": round(x, 1), "y": round(y, 1),
                "endX": round(end_x, 1) if not np.isnan(end_x) else np.nan,
                "endY": round(end_y, 1) if not np.isnan(end_y) else np.nan,
                "goal_mouth_y": round(float(rng.uniform(44, 56)), 1) if event in SHOTS else np.nan,
                "goal_mouth_z": round(float(rng.uniform(0, 38)), 1) if event in SHOTS else np.nan,
                "pitch_zone": _pitch_zone(y), "depth_zone": _depth_zone(x),
                "xT": round(float(rng.uniform(-.02, .08)), 4) if event in {"Pass", "Carry"} else 0.0,
                "prog_pass": round(max(0.0, end_x - x), 1) if event == "Pass" and not np.isnan(end_x) else 0.0,
                "prog_carry": round(max(0.0, end_x - x), 1) if event == "Carry" and not np.isnan(end_x) else 0.0,
                "matchName": f"{home} vs {away}", "homeTeam": home, "awayTeam": away, "matchDate": "2026-09-06",
            }
            flags = dict.fromkeys(FLAG_COLUMNS, False)
            if event == "Pass":
                flags["is_long_ball"] = rng.random() < .14
                flags["is_cross"] = (y < 20 or y > 80) and x > 70 and rng.random() < .3
                flags["is_key_pass"] = x > 60 and rng.random() < .05
                flags["is_through_ball"] = x > 55 and rng.random() < .02
                flags["is_switch_of_play"] = rng.random() < .02
                flags["is_box_entry_pass"] = end_x > 83 and 21 < end_y < 79
                flags["is_final_third_entry_pass"] = x < 66.7 <= end_x
                flags["is_throw_in"] = rng.random() < .03
                flags["is_goal_kick"] = player.endswith("Keeper") and rng.random() < .5
                flags["is_freekick"] = rng.random() < .03
                flags["is_corner"] = x > 98 and rng.random() < .5
                flags["is_chipped"] = rng.random() < .07
                flags["is_intentional_assist"] = flags["is_key_pass"]
            elif event == "Carry":
                flags["is_box_entry_carry"] = end_x > 83 and 21 < end_y < 79 and x <= 83
                flags["is_final_third_entry_carry"] = x < 66.7 <= end_x
            elif event in SHOTS:
                flags["is_header"] = rng.random() < .2
                flags["is_left_foot"] = not flags["is_header"] and rng.random() < .45
                flags["is_right_foot"] = not flags["is_header"] and not flags["is_left_foot"]
                flags["is_big_chance"] = flags["is_big_chance_shot"] = rng.random() < .25
                flags["is_touch_in_box"] = x > 83
                flags["is_fast_break"] = rng.random() < .1
                flags["is_hit_woodwork"] = event == "ShotOnPost"
                flags["is_gk_save"] = event == "SavedShot"
            elif event == "Card":
                flags["is_yellow_card"] = True
            row.update(flags)
            rows.append(row)
    # Penalty shootout: five alternating kicks per side.
    for kick in range(10):
        team = home if kick % 2 == 0 else away
        player = players[team][10 - kick // 2]
        event = "Goal" if kick not in {3, 6} else ("SavedShot" if kick == 3 else "MissedShot")
        row = {column: rows[0].get(column) for column in rows[0]}
        row.update(dict.fromkeys(FLAG_COLUMNS, False))
        row.update({"minute": 121, "second": kick * 30 % 60, "type": event, "outcomeType": "Successful",
                    "period": "PenaltyShootout", "playerName": player, "team": team,
                    "playerId": players[team].index(player) + (100 if team == away else 0),
                    "player_position": "FW", "shirtNumber": players[team].index(player) + 1,
                    "x": 88.5, "y": 50.0, "endX": 100.0, "endY": 47.0 + kick % 3 * 3,
                    "goal_mouth_y": 46.0 + kick % 4 * 2.5, "goal_mouth_z": 6.0 + kick % 3 * 9,
                    "pitch_zone": "Centre", "depth_zone": "Attacking Third", "xT": 0.0,
                    "prog_pass": 0.0, "prog_carry": 0.0, "is_penalty": True,
                    "is_gk_save": event == "SavedShot", "is_right_foot": True})
        rows.append(row)
    frame = pd.DataFrame(rows)
    return frame[["minute", "second", "type", "outcomeType", "period", "playerName", "team", "playerId",
                  "player_position", "shirtNumber", "x", "y", "endX", "endY", "goal_mouth_y", "goal_mouth_z",
                  *FLAG_COLUMNS, "pitch_zone", "depth_zone", "xT", "prog_pass", "prog_carry",
                  "matchName", "homeTeam", "awayTeam", "matchDate"]]


def write_fixture(path) -> None:
    build_fixture().to_csv(path, index=False, lineterminator="\n")
