import json
import tempfile
import threading
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


if __name__ == "__main__":
    unittest.main()
