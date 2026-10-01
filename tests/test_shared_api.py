import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from packaging.clipmaker_api_server import (
    build_clip_config,
    create_server,
    detect_source,
    infer_score,
    normalize_period,
)


class SharedApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(self.temporary.name))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())

    def test_health_and_static_frontend(self):
        status, body = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        with urlopen(self.base_url + "/", timeout=3) as response:
            self.assertIn(b"Match Intake", response.read())

    def test_match_history_round_trip(self):
        status, body = self.request(
            "/api/matches",
            method="POST",
            payload={
                "home_team": "Arsenal",
                "away_team": "Newcastle",
                "event_count": 1486,
                "markers": {"1H": "00:03:18", "2H": "00:50:46"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["match"]["id"], "arsenal-vs-newcastle")
        _, history = self.request("/api/matches")
        self.assertEqual(len(history["matches"]), 1)
        self.assertEqual(history["matches"][0]["markers"]["2H"], "00:50:46")

    def test_invalid_scrape_url_is_rejected(self):
        with self.assertRaises(HTTPError) as context:
            self.request("/api/scrape", method="POST", payload={"url": "https://example.com"})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_source_detection(self):
        self.assertEqual(detect_source("https://www.scoresway.com/match/1"), "scoresway")
        self.assertEqual(detect_source("https://www.whoscored.com/Matches/1"), "whoscored")

    def test_score_is_inferred_from_goal_events(self):
        import pandas as pd

        frame = pd.DataFrame(
            [
                {"type": "Goal", "team": "Home", "period": 1},
                {"type": "Goal", "team": "Away", "period": 2},
                {"type": "Goal", "team": "Away", "period": 2, "is_own_goal": True},
                {"type": "Goal", "team": "Away", "period": 5},
            ]
        )
        self.assertEqual(infer_score(frame, "Home", "Away"), (2, 1))

    def test_named_periods_are_normalized(self):
        self.assertEqual(normalize_period("FirstHalf"), 1)
        self.assertEqual(normalize_period("SecondHalf"), 2)
        self.assertEqual(normalize_period("PenaltyShootout"), 5)

    def test_full_event_table_reads_saved_csv(self):
        csv_path = Path(self.temporary.name) / "events.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team,xT\n"
            "12,30,Goal,1,Player One,Home,0.5\n"
            "68,5,SavedShot,2,Player Two,Away,0.2\n",
            encoding="utf-8",
        )
        status, result = self.request(
            "/api/events",
            method="POST",
            payload={"csv_path": str(csv_path)},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["events"][1]["playerName"], "Player Two")
        self.assertEqual(result["events"][1]["period"], 2)

    def test_filter_options_follow_the_saved_scrape(self):
        csv_path = Path(self.temporary.name) / "filter-options.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team,outcomeType,is_cross,is_own_goal,prog_pass,xT\n"
            "1,0,Pass,1,Player One,Home,Successful,True,False,4.5,0.2\n"
            "2,0,Goal,1,Player Two,Away,Successful,False,False,0,0.8\n",
            encoding="utf-8",
        )
        _, saved = self.request(
            "/api/matches",
            method="POST",
            payload={
                "home_team": "Home",
                "away_team": "Away",
                "csv_path": str(csv_path),
                "markers": {"1H": "00:00:00", "2H": "00:48:00"},
            },
        )
        status, result = self.request(
            "/api/filter-options",
            method="POST",
            payload={"match_id": saved["match"]["id"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["action_types"], ["Goal", "Pass"])
        self.assertEqual(result["team_players"]["Home"], ["Player One"])
        qualifier_map = {item["flag"]: item for item in result["qualifiers"]}
        self.assertTrue(qualifier_map["crosses_only"]["available"])
        self.assertTrue(qualifier_map["progressive_only"]["available"])
        self.assertFalse(qualifier_map["own_goals_only"]["available"])

    def test_config_applies_team_players_and_extended_qualifiers(self):
        csv_path = Path(self.temporary.name) / "scope.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team,is_goal_kick\n"
            "1,0,Pass,1,Player One,Home,True\n"
            "2,0,Pass,1,Player Two,Home,False\n"
            "3,0,Pass,1,Player Three,Away,True\n",
            encoding="utf-8",
        )
        match = {
            "id": "home-vs-away",
            "csv_path": str(csv_path),
            "video_path": "",
            "markers": {"1H": "00:00:00", "2H": "00:48:00"},
        }
        config = build_clip_config(
            match,
            {
                "dry_run": True,
                "team_filter": "Home",
                "player_filters": ["Player One"],
                "qualifier_logic": "all",
                "goal_kicks_only": True,
            },
            Path(self.temporary.name),
        )
        import pandas as pd

        filtered = pd.read_csv(config["data_file"])
        self.assertEqual(filtered["playerName"].tolist(), ["Player One"])
        self.assertEqual(config["qualifier_logic"], "all")
        self.assertTrue(config["goal_kicks_only"])
        Path(config["_temporary_data_file"]).unlink()

    def test_dry_run_job_uses_saved_match_and_real_engine(self):
        csv_path = Path(self.temporary.name) / "events.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team\n"
            "12,30,Goal,1,Player One,Home\n"
            "68,5,SavedShot,2,Player Two,Away\n",
            encoding="utf-8",
        )
        _, saved = self.request(
            "/api/matches",
            method="POST",
            payload={
                "home_team": "Home",
                "away_team": "Away",
                "csv_path": str(csv_path),
                "event_count": 2,
                "markers": {"1H": "00:00:10", "2H": "00:48:00"},
            },
        )
        status, started = self.request(
            "/api/jobs",
            method="POST",
            payload={
                "match_id": saved["match"]["id"],
                "options": {
                    "dry_run": True,
                    "filter_types": ["Goal", "SavedShot"],
                    "before_buffer": 4,
                    "after_buffer": 7,
                },
            },
        )
        self.assertEqual(status, 202)

        job = started["job"]
        deadline = time.time() + 5
        while job["status"] not in {"complete", "failed", "cancelled"} and time.time() < deadline:
            time.sleep(0.05)
            _, result = self.request(f"/api/jobs/{job['id']}")
            job = result["job"]

        self.assertEqual(job["status"], "complete", "\n".join(job["logs"]))
        self.assertTrue(any("2 clips" in line for line in job["logs"]))
        self.assertTrue(any("DRY RUN complete" in line for line in job["logs"]))

    def test_render_job_requires_native_video_path(self):
        csv_path = Path(self.temporary.name) / "events.csv"
        csv_path.write_text("minute,second,type,period\n1,0,Goal,1\n", encoding="utf-8")
        _, saved = self.request(
            "/api/matches",
            method="POST",
            payload={
                "home_team": "Home",
                "away_team": "Away",
                "csv_path": str(csv_path),
                "markers": {"1H": "00:00:00", "2H": "00:48:00"},
            },
        )
        with self.assertRaises(HTTPError) as context:
            self.request(
                "/api/jobs",
                method="POST",
                payload={"match_id": saved["match"]["id"], "options": {"dry_run": False}},
            )
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_native_video_picker_returns_path_and_streams_ranges(self):
        video_path = Path(self.temporary.name) / "match.mp4"
        video_path.write_bytes(b"0123456789")
        with patch(
            "packaging.clipmaker_api_server.choose_video_file",
            return_value=video_path,
        ):
            status, result = self.request("/api/files/video", method="POST", payload={})

        self.assertEqual(status, 200)
        self.assertEqual(result["file"]["path"], str(video_path))
        request = Request(
            self.base_url + result["file"]["url"],
            headers={"Range": "bytes=2-5"},
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
            self.assertEqual(response.read(), b"2345")

    def test_saved_video_can_be_reopened(self):
        video_path = Path(self.temporary.name) / "saved-match.mp4"
        video_path.write_bytes(b"abcdefghij")
        _, saved = self.request(
            "/api/matches",
            method="POST",
            payload={
                "home_team": "Home",
                "away_team": "Away",
                "video_name": video_path.name,
                "video_path": str(video_path),
            },
        )
        status, result = self.request(
            "/api/files/reopen",
            method="POST",
            payload={"match_id": saved["match"]["id"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["file"]["path"], str(video_path))


if __name__ == "__main__":
    unittest.main()
