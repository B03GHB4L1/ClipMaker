"""Opta qualifiers both scrapers read (2026-11-22). Checked against one WhoScored
and one Scoresway match: WhoScored marked a goal's last pass IntentionalGoalAssist, not
Assist, so Assists never matched there; and both feeds carry shot situation, first-time
shots, save kinds, duels, goal-line clearances and a shot's assisting pass, which the
scrapers dropped. WhoScored qualifiers carry the same Opta ids as Scoresway's, so the
new columns are read by id in both (whoscored_scraper.OPTA_QUALIFIER_COLUMNS)."""
from __future__ import annotations

import json
import queue
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from packaging.clipmaker_api_server import load_filter_options  # first: it puts app/ on the path
import clipmaker_core as core  # noqa: E402
from app import whoscored_scraper  # noqa: E402
from app.scoresway_scraper import (  # noqa: E402
    EXPECTED_COLUMNS, add_keeper_save_zones, apply_qualifier_flags, make_empty_row, normalise_scoresway_events,
    normalize_qualifiers,
)
from app.whoscored_scraper import OPTA_COLUMNS, OPTA_VALUE_COLUMNS, opta_flags, opta_values  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def qualifier(name, opta_id, value=None):
    item = {"type": {"displayName": name, "value": opta_id}}
    if value is not None:
        item["value"] = value
    return item


def ws_event(event_id, kind, player, team, minute, *qualifiers, outcome="Successful", x=50, y=50,
             period=(1, "FirstHalf")):
    return {"id": event_id * 10, "eventId": event_id, "minute": minute, "second": 0, "teamId": team, "playerId": player,
            "x": x, "y": y, "period": {"value": period[0], "displayName": period[1]}, "type": {"displayName": kind},
            "outcomeType": {"displayName": outcome}, "qualifiers": list(qualifiers), "isTouch": True}


def whoscored_page():
    events = [
        ws_event(60, "Pass", 1, 10, 2, qualifier("FreekickTaken", 5), qualifier("IndirectFreekickTaken", 241)),
        ws_event(61, "Pass", 1, 10, 3, qualifier("Cross", 2), qualifier("IntentionalGoalAssist", 11111), qualifier("KeyPass", 11113),
                 x=80, y=90),
        ws_event(62, "Goal", 2, 10, 3, qualifier("Assisted", 29), qualifier("RelatedEventId", 55, "61"),
                 qualifier("FirstTouch", 328), qualifier("RegularPlay", 22), qualifier("Head", 15), x=94, y=50),
        ws_event(70, "Save", 3, 20, 3, qualifier("DivingSave", 179), qualifier("Hands", 182), qualifier("ParriedSafe", 173), x=4),
        ws_event(71, "Aerial", 4, 20, 5, qualifier("Defensive", 285)),
        ws_event(63, "Aerial", 2, 10, 5, qualifier("Offensive", 286)),
        ws_event(64, "MissedShots", 2, 10, 7, qualifier("SetPiece", 24), qualifier("FromCorner", 25), x=90),
        ws_event(65, "SavedShot", 1, 10, 9, qualifier("DirectFreekick", 26), qualifier("SavedOffline", 101), x=75),
        # Names and ids as the second live check found them (PSG v Slovan Bratislava).
        ws_event(66, "MissedShots", 2, 10, 10, qualifier("OneOnOne", 89), x=92),
        ws_event(67, "SavedShot", 2, 10, 13, qualifier("SixYardBlock", 100), qualifier("BlockedX", 146, "86.4"),
                 qualifier("BlockedY", 147, "51.4"), x=90),
        ws_event(68, "TakeOn", 1, 10, 14, qualifier("OverRun", 211), outcome="Unsuccessful"),
        ws_event(69, "SubstitutionOn", 1, 10, 60, qualifier("FormationSlot", 145, "7")),
        ws_event(72, "OffsidePass", 4, 20, 54, qualifier("PlayerCaughtOffside", 7, "2"), qualifier("GoalDisallowed", 8)),
        ws_event(73, "Save", 3, 20, 11, qualifier("StandingSave", 178), qualifier("KeeperSaveObox", 11117), x=1.2),
        ws_event(74, "Tackle", 4, 20, 15, qualifier("StandingSave", 178)),
        ws_event(75, "Claim", 3, 20, 16, qualifier("HighClaim", 88), x=6),
        ws_event(76, "Interception", 4, 20, 17, qualifier("LastMan", 14)),
        ws_event(77, "FormationSet", None, 20, 0, qualifier("TeamFormation", 130, "4"),
                 qualifier("TeamPlayerFormation", 131, "1, 2, 0"), qualifier("InvolvedPlayers", 30, "3, 4, 9"),
                 qualifier("CaptainPlayerId", 194, "3"), period=(16, "PreMatch")),
        ws_event(78, "End", None, 20, 0, period=(14, "PostGame")),
        ws_event(79, "DeletedEvent", 3, 20, 18, qualifier("HighClaim", 88)),
    ]
    data = {"events": events, "playerIdNameDictionary": {"1": "Ann", "2": "Bea", "3": "Cat", "4": "Dee"},
            "home": {"teamId": 10, "name": "Home", "players": [{"playerId": 1}, {"playerId": 2}]},
            "away": {"teamId": 20, "name": "Away", "players": [{"playerId": 3, "position": "GK"}, {"playerId": 4}]},
            "startTime": "2026-11-22T15:00:00"}
    return f"<script>var matchCentreData = {json.dumps(data)};</script>"


def scrape(html):
    session = Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.text = html
    messages = queue.Queue()
    with patch("curl_cffi.requests.Session", return_value=session), patch.object(whoscored_scraper.time, "sleep"):
        whoscored_scraper.scrape_whoscored("https://www.whoscored.com/matches/1/live/x", messages, str(ROOT / "app"), enrich_xg=False)
    items = list(messages.queue)
    data = [item for item in items if item["type"] == "data"]
    assert data, [item.get("msg") for item in items][-3:]
    frame = data[0]["df"]
    return frame[frame["event_id"].astype(str) != ""].set_index("event_id")


def yes(value):
    return str(value).strip().lower() in {"true", "1"}


class WhoScoredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = scrape(whoscored_page())

    def flag(self, event_id, column):
        return yes(self.rows.loc[str(event_id), column])

    def test_a_goals_last_pass_is_an_assist_and_says_what_kind(self):
        self.assertTrue(self.flag(61, "is_assist"))
        self.assertTrue(self.flag(61, "is_assist_cross"))
        self.assertFalse(self.flag(61, "is_assist_corner"))
        self.assertFalse(self.flag(60, "is_assist"))

    def test_an_assisted_shot_points_at_its_pass(self):
        self.assertEqual(self.rows.loc["62", "assist_event_id"], "61")
        self.assertEqual(self.rows.loc["64", "assist_event_id"], "")
        for column in ("is_assisted", "is_first_time", "is_regular_play", "is_header"):
            self.assertTrue(self.flag(62, column), column)

    def test_indirect_free_kicks_are_free_kicks(self):
        self.assertTrue(self.flag(60, "is_freekick"))

    def test_shot_situations_saves_and_duels(self):
        self.assertTrue(self.flag(64, "is_set_piece_shot") and self.flag(64, "is_from_corner"))
        self.assertTrue(self.flag(65, "is_direct_freekick") and self.flag(65, "is_saved_off_line"))
        self.assertEqual(self.rows.loc["70", "type"], "Save")
        for column in ("is_diving_save", "is_save_hands", "is_parried"):
            self.assertTrue(self.flag(70, column), column)
        self.assertFalse(self.flag(70, "is_caught"))
        self.assertTrue(self.flag(63, "is_attacking_duel") and not self.flag(63, "is_defending_duel"))
        self.assertTrue(self.flag(71, "is_defending_duel"))

    def test_disallowed_goals_and_who_was_caught_offside(self):
        self.assertTrue(self.flag(72, "is_goal_disallowed"))
        self.assertEqual(self.rows.loc["72", "caught_offside_player"], "Bea")

    def test_save_kind_and_where_the_saved_shot_came_from(self):
        self.assertTrue(self.flag(73, "is_standing_save") and self.flag(73, "is_keeper_save_outside_box"))
        self.assertFalse(self.flag(73, "is_keeper_save_in_box"))
        self.assertFalse(self.flag(74, "is_standing_save"))  # tackles carry Opta 178 too
        self.assertTrue(self.flag(75, "is_high_claim"))

    def test_one_on_one_and_last_man_read_by_id(self):
        self.assertTrue(self.flag(66, "is_1on1"))
        self.assertTrue(self.flag(76, "is_last_line"))

    def test_six_yard_blocks_record_where_the_shot_was_blocked(self):
        self.assertTrue(self.flag(67, "is_six_yard_block"))
        self.assertEqual((float(self.rows.loc["67", "blocked_x"]), float(self.rows.loc["67", "blocked_y"])), (86.4, 51.4))
        self.assertTrue(self.flag(68, "is_overrun"))

    def test_the_starting_formation_is_kept_at_kick_off(self):
        start = self.rows.loc["77"]
        self.assertEqual((start["period"], int(start["minute"]), start["team"]), ("FirstHalf", 0, "Away"))
        self.assertEqual((start["formation"], start["formation_lineup"], start["captain"]), ("4-3-3", "1 Cat; 2 Dee", "Cat"))
        self.assertEqual(str(self.rows.loc["69", "formation_slot"]), "7")
        self.assertNotIn("78", self.rows.index)  # post-game events are still left out
        self.assertNotIn("79", self.rows.index)  # deleted events are left out

    def test_team_level_events_start_or_end_no_carry(self):
        events = [
            ws_event(1, "FormationSet", None, 10, 0, period=(16, "PreMatch")),
            ws_event(2, "Pass", 1, 10, 0, x=20, y=50),
            ws_event(3, "Pass", 2, 10, 0, x=60, y=50),
            ws_event(4, "FormationChange", None, 10, 1),
        ]
        for item, second in zip(events, (0, 5, 20, 40)):
            item["second"] = second
        events[1]["qualifiers"] = [qualifier("PassEndX", 140, "40"), qualifier("PassEndY", 141, "50")]
        events[1]["endX"], events[1]["endY"] = 40, 50
        data = {"events": events * 2, "playerIdNameDictionary": {"1": "Ann", "2": "Bea"},
                "home": {"teamId": 10, "name": "Home", "players": [{"playerId": 1}, {"playerId": 2}]},
                "away": {"teamId": 20, "name": "Away", "players": []}, "startTime": "2026-11-22T15:00:00"}
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.text = f"<script>var matchCentreData = {json.dumps(data)};</script>"
        messages = queue.Queue()
        with patch("curl_cffi.requests.Session", return_value=session), patch.object(whoscored_scraper.time, "sleep"):
            whoscored_scraper.scrape_whoscored("https://www.whoscored.com/matches/1/live/x", messages, str(ROOT / "app"))
        frame = next(item["df"] for item in messages.queue if item["type"] == "data")
        carries = frame[frame["type"] == "Carry"]
        self.assertFalse(carries.empty)  # the pass-to-pass carry still appears
        self.assertTrue((carries["playerName"].astype(str).str.strip() != "").all())
        self.assertEqual(set(carries["playerName"]), {"Bea"})


class ScoreswayTests(unittest.TestCase):
    def flags(self, event_type, *qualifiers):
        row = make_empty_row()
        apply_qualifier_flags(row, normalize_qualifiers(list(qualifiers)), event_type, "Successful", "Home")
        return row

    def test_the_shared_columns_are_in_the_scoresway_table(self):
        self.assertTrue(set(OPTA_COLUMNS) | {"event_id", "assist_event_id"} <= set(EXPECTED_COLUMNS))

    def test_scoresway_reads_the_same_ids(self):
        shot = self.flags("Goal", {"qualifierId": 29}, {"qualifierId": 55, "value": "37"}, {"qualifierId": 328},
                          {"qualifierId": 25}, {"qualifierId": 101})
        self.assertEqual(shot["assist_event_id"], "37")
        for column in ("is_assisted", "is_first_time", "is_from_corner", "is_saved_off_line"):
            self.assertTrue(shot[column], column)
        save = self.flags("Save", {"qualifierId": 176}, {"qualifierId": 183})
        self.assertTrue(save["is_caught"] and save["is_save_feet"] and not save["is_parried"])
        self.assertTrue(self.flags("Pass", {"qualifierId": 241})["is_freekick"])  # indirect free kick
        self.assertFalse(self.flags("Foul", {"qualifierId": 241})["is_freekick"])  # only passes are free kicks

    def test_a_related_event_without_assisted_is_not_an_assist_link(self):
        self.assertEqual(opta_flags({55: "12"})["assist_event_id"], "")

    def test_scoresway_reads_the_newer_ids(self):
        self.assertTrue(self.flags("Save", {"qualifierId": 178})["is_standing_save"])
        self.assertFalse(self.flags("Tackle", {"qualifierId": 178})["is_standing_save"])
        self.assertTrue(self.flags("Interception", {"qualifierId": 14})["is_last_line"])
        self.assertTrue(self.flags("OffsidePass", {"qualifierId": 8})["is_goal_disallowed"])
        for qid, column in ((88, "is_high_claim"), (100, "is_six_yard_block"), (211, "is_overrun")):
            self.assertTrue(self.flags("Pass", {"qualifierId": qid})[column], column)
        self.assertTrue(set(OPTA_VALUE_COLUMNS) <= set(EXPECTED_COLUMNS))

    def test_unmapped_event_types_and_qualifiers_are_not_read(self):
        def sw_event(event_id, type_id, *qualifiers):
            return {"eventId": event_id, "typeId": type_id, "periodId": 1, "timeMin": 1, "timeSec": event_id,
                    "contestantId": "t1", "playerId": "p1", "x": 50, "y": 50, "outcome": 1, "qualifier": list(qualifiers)}
        events = [sw_event(1, 1, {"qualifierId": 140, "value": "70"}, {"qualifierId": 9999, "value": "x"}),
                  sw_event(2, 90, {"qualifierId": 41}), sw_event(3, 84), sw_event(4, 43, {"qualifierId": 88})]
        logs = []
        with patch("app.scoresway_scraper.normalize_qualifiers", wraps=normalize_qualifiers) as read:
            frame, *_ = normalise_scoresway_events({}, {"liveData": {"event": events}}, str(ROOT / "app"),
                                                   enrich_xg=False, log=logs.append)
        self.assertEqual(frame["type"].tolist(), ["Pass"])
        self.assertEqual(float(frame["endX"].iloc[0]), 70.0)
        self.assertEqual(read.call_count, 1)  # the skipped events' qualifiers are never read
        self.assertIn("Skipped 2 events with unmapped Scoresway/Opta typeIds", " ".join(logs))
        self.assertIn("Skipped 1 DeletedEvent events.", logs)
        self.assertFalse(any("Unmapped" in line or "Unknown" in line for line in logs))

    def test_value_qualifiers_name_players_and_formations(self):
        names = {"p1": "Ann", "p2": "Bea"}.get
        values = opta_values({7: "p2", 130: "8", 131: "2, 1, 0", 30: "p1, p2, p3", 194: "p1", 146: "86.4", 147: "x"},
                             lambda pid: names(pid, ""))
        self.assertEqual(values, {"blocked_x": 86.4, "caught_offside_player": "Bea", "formation": "4-2-3-1",
                                  "formation_lineup": "1 Bea; 2 Ann", "captain": "Ann"})
        self.assertEqual(opta_values({130: "99", 194: "p9"})["formation"], "99")  # unknown ids stay raw
        self.assertEqual(opta_values({194: "p9"})["captain"], "p9")

    def test_keeper_saves_take_the_box_zone_of_their_shot(self):
        def row(event_type, team, minute, second, x=np.nan, y=np.nan, gk=False):
            item = make_empty_row()
            item.update(type=event_type, team=team, period="FirstHalf", minute=minute, second=second, x=x, y=y, is_gk_save=gk)
            return item
        frame = pd.DataFrame([
            row("SavedShot", "A", 5, 10, 91, 44), row("Save", "B", 5, 11, 2, 50, gk=True),     # in the box
            row("SavedShot", "A", 20, 0, 78, 50), row("Save", "B", 20, 0, 2, 50, gk=True),     # outside
            row("Goal", "B", 30, 0, 96, 50), row("Save", "A", 30, 1, 1, 50, gk=True),          # six-yard box
            row("Save", "A", 40, 0, 1, 50, gk=True),                                           # no shot to pair
            row("SavedShot", "A", 50, 0, 91, 50), row("Block", "B", 50, 0, 10, 50),            # outfield block
        ])
        zones = add_keeper_save_zones(frame)[["is_keeper_save_in_box", "is_keeper_save_six_yard",
                                              "is_keeper_save_outside_box"]].astype(bool).values.tolist()
        self.assertEqual(zones[1], [True, False, False])
        self.assertEqual(zones[3], [False, False, True])
        self.assertEqual(zones[5], [True, True, False])
        self.assertEqual(zones[6], [False, False, False])
        self.assertEqual(zones[8], [False, False, False])


class FilterTests(unittest.TestCase):
    def test_new_qualifiers_keep_only_their_own_event_types(self):
        rows = pd.DataFrame([
            {"id": "dive", "type": "Save", "is_diving_save": True},
            {"id": "dive on a penalty", "type": "PenaltyFaced", "is_diving_save": True},
            {"id": "aerial", "type": "Aerial", "is_attacking_duel": True},
            {"id": "pass", "type": "Pass", "is_attacking_duel": True},
            {"id": "first time", "type": "Goal", "is_first_time": True},
        ]).assign(minute=1, second=0, period=1, team="Home", playerName="One", outcomeType="Successful")
        kept = lambda config: core.apply_filters(rows.copy(), config)[0]["id"].tolist()
        self.assertEqual(kept({"diving_saves_only": True}), ["dive"])
        self.assertEqual(kept({"attacking_duels_only": True}), ["aerial"])
        self.assertEqual(kept({"first_time_shots_only": True}), ["first time"])

    def test_disallowed_goals_keep_the_offside_pass_and_high_claims_keep_claims(self):
        rows = pd.DataFrame([
            {"id": "offside", "type": "OffsidePass", "is_goal_disallowed": True, "is_high_claim": False},
            {"id": "claim", "type": "Claim", "is_goal_disallowed": False, "is_high_claim": True},
            {"id": "pass", "type": "Pass", "is_goal_disallowed": False, "is_high_claim": True},
        ]).assign(minute=1, second=0, period=1, team="Home", playerName="One", outcomeType="Successful")
        kept = lambda config: core.apply_filters(rows.copy(), config)[0]["id"].tolist()
        self.assertEqual(kept({"disallowed_goals_only": True}), ["offside"])
        self.assertEqual(kept({"high_claims_only": True}), ["claim"])

    def test_filter_lists_the_new_groups(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            pd.DataFrame([{"minute": 1, "second": 0, "period": 1, "type": "Aerial", "is_defending_duel": True}]).to_csv(path, index=False)
            options = load_filter_options({"id": "duels", "csv_path": str(path)})
        by_flag = {item["flag"]: item for item in options["qualifiers"]}
        self.assertEqual((by_flag["defending_duels_only"]["group"], by_flag["defending_duels_only"]["count"]), ("Duels", 1))
        self.assertEqual(by_flag["diving_saves_only"]["group"], "Goalkeeping")


if __name__ == "__main__":
    unittest.main()
