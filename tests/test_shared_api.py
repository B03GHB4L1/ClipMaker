import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from packaging.clipmaker_api_server import create_server, detect_source


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


if __name__ == "__main__":
    unittest.main()
