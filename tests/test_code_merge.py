"""Coding milestone C4 (docs/CODING_AND_PITCH_PLAN.md): pitch locations on coded
events, and a project's source "both", where coded rows join a scraped or
imported event table without changing it."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

from app.coding import store, to_events
from app.whoscored_scraper import _depth_zone, _pitch_zone
from packaging.clipmaker_api_server import analysis_view, create_server

MARKERS = {"1H": "0:00:05", "2H": "0:00:40"}
FEED = (
    "minute,second,type,outcomeType,period,playerName,team,x,y,homeTeam,awayTeam,eventId\n"
    "0,10,Pass,Successful,FirstHalf,Ali,Reims,50,50,Reims,Lens,1\n"
    "0,20,Goal,Successful,FirstHalf,Ali,Reims,90,50,Reims,Lens,2\n"
    "46,5,Pass,Successful,SecondHalf,Ben,Lens,40,30,Reims,Lens,3\n"
)


def event(event_id, t, code="goal", team="home", **extra):
    return {"id": event_id, "code": code, "team": team, "src": "1H", "t": t, **extra}


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_locations_are_saved_checked_and_cleared(self):
        document = store.apply(self.folder, {"add": [event("c000001", 10, code="won", x=40.04, y=80, endX=70, endY=55.55)]})
        self.assertEqual({key: document["events"][0][key] for key in ("x", "y", "endX", "endY")},
                         {"x": 40.0, "y": 80.0, "endX": 70.0, "endY": 55.5})
        for bad in ({"x": 101, "y": 5}, {"x": 5, "y": None}, {"x": None, "y": None, "endX": 5, "endY": 5}, {"x": "5", "y": 5},
                    {"x": True, "y": 5}, {"endX": 5, "endY": None}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                store.apply(self.folder, {"update": [{"id": "c000001", **bad}]})
        cleared = store.apply(self.folder, {"update": [{"id": "c000001", "x": None, "y": None, "endX": None, "endY": None}]})
        self.assertFalse({"x", "y", "endX", "endY"} & set(cleared["events"][0]))

    def test_zones_match_the_scraped_tables(self):
        for value in (0, 19.9, 20, 33.9, 34, 36.9, 37, 62.9, 63, 66.9, 67, 79.9, 80, 100):
            self.assertEqual(to_events.depth_zone(value), _depth_zone(value), value)
            self.assertEqual(to_events.pitch_zone(value), _pitch_zone(value, flip=True), value)

    def test_locations_reach_the_table(self):
        document = store.empty()
        document["events"] = [event("c000001", 10, code="won", x=80, y=90, endX=95, endY=50), event("c000002", 12)]
        placed, bare = to_events.rows(document, MARKERS, lambda _: "match.mp4")[0]
        self.assertEqual((placed["x"], placed["y"], placed["endX"], placed["endY"]), (80, 90, 95, 50))
        self.assertEqual((placed["depth_zone"], placed["pitch_zone"]), ("Attacking Third", "Left Wing"))
        self.assertEqual((bare["x"], bare["depth_zone"]), ("", ""))


class MergeTests(unittest.TestCase):
    def test_coded_rows_join_the_feed_in_clock_order_and_the_feed_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            feed = Path(folder) / "feed.csv"
            feed.write_text(FEED, encoding="utf-8")
            document = store.empty()
            document["events"] = [event("c000001", 20), event("c000002", 50, code="corner", team="away")]
            table, _ = to_events.rows(document, MARKERS, lambda _: "match.mp4", "Reims", "Lens")
            count = to_events.write_merged(feed, table, Path(folder) / "merged.csv")
            merged = pd.read_csv(Path(folder) / "merged.csv", encoding="utf-8-sig")
            self.assertEqual(count, 5)
            self.assertEqual(feed.read_text(encoding="utf-8"), FEED)
            # 0:10 feed, 0:15 coded, 0:20 feed; second half 45:10 coded, 46:05 feed.
            self.assertEqual(merged["source"].tolist(), ["feed", "coded", "feed", "coded", "feed"])
            self.assertEqual(merged["type"].tolist(), ["Pass", "Goal", "Goal", "CornerAwarded", "Pass"])
            self.assertEqual(merged.loc[merged["source"] == "feed", "eventId"].tolist(), [1, 2, 3])  # feed columns kept


class BothSourceApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        video = self.root / "match.mp4"
        video.write_bytes(b"not decoded by these requests")
        self.feed = self.root / "feed.csv"
        self.feed.write_text(FEED, encoding="utf-8")
        self.project_id = self.request("/api/projects", {})["project"]["id"]
        self.request(f"/api/projects/{self.project_id}", {"video_path": str(video), "markers": MARKERS,
                                                          "home_team": "Reims", "away_team": "Lens"})
        self.server.match_store.upsert({"id": self.project_id, "csv_path": str(self.feed), "source": "whoscored",  # type: ignore[attr-defined]
                                        "event_count": 3, "home_score": 1, "away_score": 0})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def codes(self, body):
        return self.request(f"/api/projects/{self.project_id}/codes", body)

    def test_codes_merge_into_the_feed_and_leave_with_the_last_code(self):
        project = self.codes({"add": [event("c000001", 30, code="moment", x=85, y=90)]})["project"]
        self.assertEqual((project["source"], project["feed_csv_path"], project["feed_source"]),
                         ("both", str(self.feed), "whoscored"))
        self.assertEqual(project["event_count"], 4)
        self.assertNotEqual(project["csv_path"], str(self.feed))
        self.assertEqual(self.feed.read_text(encoding="utf-8"), FEED)

        # Filter sees both; a lane filter works on the clicked location.
        options = self.request("/api/filter-options", {"match_id": self.project_id})
        self.assertIn("Key moment", options["action_types"])
        self.assertIn("Pass", options["action_types"])
        self.assertEqual(options["unlocated"], 0)
        plan = self.request("/api/previews", {"match_id": self.project_id,
                                              "options": {"filter_types": ["Key moment"], "pitch_zone_filter": "Left Wing"}})
        self.assertEqual(len(plan["windows"]), 1)

        # The Analyst Room and the score read the feed only, so a coded Goal is not counted twice.
        self.codes({"add": [event("c000002", 34, code="goal")]})
        project = self.server.match_store.get(self.project_id)  # type: ignore[attr-defined]
        self.assertEqual(analysis_view(project)["csv_path"], str(self.feed))
        rows = self.request("/api/events", {"csv_path": project["csv_path"]})
        self.assertEqual((rows["home_score"], rows["away_score"]), (1, 0))
        self.assertEqual(rows["event_count"], 5)
        self.assertEqual(self.request("/api/filter-options", {"match_id": self.project_id})["unlocated"], 1)

        # New kick-offs re-time the merged table; deleting every code goes back to the feed.
        moved = self.request(f"/api/projects/{self.project_id}", {"markers": {"1H": "0:00:10", "2H": "0:00:40"}})["project"]
        merged = pd.read_csv(moved["csv_path"], encoding="utf-8-sig")
        self.assertEqual(merged.loc[merged["coded_id"] == "c000001", "second"].tolist(), [20])
        back = self.codes({"delete": ["c000001", "c000002"]})["project"]
        self.assertEqual((back["csv_path"], back["source"], back["feed_csv_path"], back["event_count"]),
                         (str(self.feed), "whoscored", "", 3))

    def test_the_browser_cannot_point_a_project_at_another_feed(self):
        self.codes({"add": [event("c000001", 30, code="moment")]})
        for body in ({"feed_csv_path": str(self.root / "other.csv")}, {"feed_source": "csv"}, {"source": "coded"}):
            with self.subTest(body=body), self.assertRaises(HTTPError) as caught:
                self.request(f"/api/projects/{self.project_id}", body)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()


if __name__ == "__main__":
    unittest.main()
