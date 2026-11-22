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

import pandas as pd

from packaging.clipmaker_api_server import load_filter_options  # first: it puts app/ on the path
import clipmaker_core as core  # noqa: E402
from app import whoscored_scraper  # noqa: E402
from app.scoresway_scraper import EXPECTED_COLUMNS, apply_qualifier_flags, make_empty_row, normalize_qualifiers  # noqa: E402
from app.whoscored_scraper import OPTA_COLUMNS, opta_flags  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def qualifier(name, opta_id, value=None):
    item = {"type": {"displayName": name, "value": opta_id}}
    if value is not None:
        item["value"] = value
    return item


def ws_event(event_id, kind, player, team, minute, *qualifiers, outcome="Successful", x=50, y=50):
    return {"id": event_id * 10, "eventId": event_id, "minute": minute, "second": 0, "teamId": team, "playerId": player,
            "x": x, "y": y, "period": {"value": 1, "displayName": "FirstHalf"}, "type": {"displayName": kind},
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
