"""Phase 1 foundation: analysis_core, its cache, saved state and the analysis API."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

from analysis_core import FrameCache, build_analyst_frames, validate_tab  # noqa: E402
from packaging.clipmaker_api_server import (  # noqa: E402
    MatchStore, analysis_ui_modes, clean_analysis_state, create_server,
)
from tests.analysis_fixture import build_fixture, write_fixture  # noqa: E402


class AnalysisCoreTests(unittest.TestCase):
    def test_package_never_imports_streamlit(self):
        code = ("import sys; sys.path.insert(0, 'app'); import analysis_core, analysis_core.frames, "
                "analysis_core.registry; assert 'streamlit' not in sys.modules, 'streamlit imported'")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frames_split_shootout_and_resolve_short_labels(self):
        frame = build_fixture(events=400)
        frame["homeTeam"], frame["awayTeam"] = "North", "South"  # short labels, as in Scoresway files
        frames = build_analyst_frames(frame)
        summary = frames.summary()
        self.assertEqual((frames.home_team, frames.away_team), ("Northbridge", "Southport"))
        self.assertTrue(summary["has_penalty_shootout"])
        self.assertEqual(len(frames.pso_shots_df), 10)
        self.assertNotIn("PenaltyShootout", set(frames.df_all["period"]))
        self.assertEqual(summary["event_count"], len(frames.df_all) + 10)
        self.assertGreater(summary["counts"]["shots"], 0)

    def test_cache_reuses_until_file_changes_and_evicts(self):
        with tempfile.TemporaryDirectory() as name:
            paths = [Path(name) / f"m{index}.csv" for index in range(3)]
            for path in paths:
                write_fixture(path)
            cache = FrameCache(capacity=2)
            first = cache.get(str(paths[0]))
            self.assertIs(cache.get(str(paths[0])), first)
            self.assertEqual(cache.loads, 1)
            build_fixture(events=300, seed=3).to_csv(paths[0], index=False)
            stat = paths[0].stat()
            os.utime(paths[0], ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            self.assertIsNot(cache.get(str(paths[0])), first)
            cache.get(str(paths[1]))
            cache.get(str(paths[2]))  # evicts paths[0]
            loads = cache.loads
            cache.get(str(paths[0]))
            self.assertEqual(cache.loads, loads + 1)
            with self.assertRaises(ValueError):
                cache.get(str(Path(name) / "missing.csv"))

    def test_registry_rejects_unknown_names(self):
        self.assertEqual(validate_tab("analyst", "shot-map")["label"], "Shot Map")
        for view, tab in (("analyst", "../x"), ("other", "shot-map"), ("tactical", "shot-map")):
            with self.subTest(view=view, tab=tab), self.assertRaises(ValueError):
                validate_tab(view, tab)

    def test_saved_state_validation(self):
        state = {"analyst": {"tab": "shot-map", "controls": {"shot-map": {"team": "Home", "zones": ["A", "B"], "n": 3}}}}
        self.assertEqual(clean_analysis_state(state), state)
        self.assertEqual(clean_analysis_state(None), {})
        for bad in ({"other": {}}, {"analyst": {"tab": "../x"}}, {"analyst": {"controls": {"t": {"k": {"nested": 1}}}}},
                    {"analyst": {"controls": {"t": {f"k{i}": "x" * 200 for i in range(200)}}}}):
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(ValueError):
                clean_analysis_state(bad)

    def test_ui_mode_setting(self):
        cases = {"": ("classic", "classic"), "native": ("native", "native"), "analyst=native": ("native", "classic"),
                 "analyst=native,tactical=streamlit": ("native", "classic"), "bogus": ("classic", "classic")}
        for setting, expected in cases.items():
            with self.subTest(setting=setting), patch.dict(os.environ, {"VIZORPLAY_ANALYSIS_UI": setting}):
                modes = analysis_ui_modes()
                self.assertEqual((modes["analyst"], modes["tactical"]), expected)


class AnalysisApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.csv = self.root / "match.csv"
        write_fixture(self.csv)
        store = MatchStore(self.root)
        self.project = store.create("API fixture")
        store.upsert({"id": self.project["id"], "csv_path": str(self.csv), "home_team": "Northbridge", "away_team": "Southport"})
        self.empty = store.create("No match yet")
        self.server = create_server("127.0.0.1", 0, self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.analysis.close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()

    def error(self, path, body=None):
        with self.assertRaises(HTTPError) as caught:
            self.request(path, body)
        payload = json.loads(caught.exception.read())
        caught.exception.close()
        return caught.exception.code, payload

    def test_config_lists_views_tabs_and_modes(self):
        _, body = self.request("/api/analysis/config")
        views = json.loads(body)["views"]
        self.assertEqual([tab["slug"] for tab in views["analyst"]["tabs"]][:2], ["shot-map", "pass-map"])
        self.assertEqual(len(views["tactical"]["tabs"]), 5)
        self.assertEqual(views["analyst"]["mode"], "classic")
        with patch.dict(os.environ, {"VIZORPLAY_ANALYSIS_UI": "analyst=native"}):
            views = json.loads(self.request("/api/analysis/config")[1])["views"]
        self.assertEqual((views["analyst"]["mode"], views["tactical"]["mode"]), ("native", "classic"))

    def test_summary_loads_once_and_reports_match(self):
        started = time.monotonic()
        _, body = self.request(f"/api/analysis/summary?project={self.project['id']}")
        cold = time.monotonic() - started
        summary = json.loads(body)["summary"]
        self.assertEqual((summary["home_team"], summary["away_team"]), ("Northbridge", "Southport"))
        started = time.monotonic()
        self.request(f"/api/analysis/summary?project={self.project['id']}")
        warm = time.monotonic() - started
        self.assertEqual(self.server.analysis_frames._cache.loads, 1)
        self.assertLess(warm, max(cold, 0.5))

    def test_summary_and_tab_requests_are_validated(self):
        for query in ("", "?project=../../etc", "?project=unknown", f"?project={self.empty['id']}"):
            with self.subTest(query=query):
                code, payload = self.error(f"/api/analysis/summary{query}")
                self.assertEqual(code, 400)
                self.assertTrue(payload["error"])
        for path in ("/api/analysis/other/shot-map", "/api/analysis/analyst/unknown", "/api/analysis/analyst/shot-map/x"):
            with self.subTest(path=path):
                self.assertEqual(self.error(path, {"project_id": self.project["id"]})[0], 400)
        code, payload = self.error("/api/analysis/analyst/shot-map", {"project_id": self.project["id"]})
        self.assertEqual((code, payload.get("classic")), (501, True))
        self.assertEqual(self.error("/api/analysis/analyst/shot-map", {"project_id": "nope"})[0], 400)

    def test_component_assets_are_served_without_escaping_their_folder(self):
        status, body = self.request("/analysis-component/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"streamlit:componentReady", body)
        for path in ("/analysis-component/../clipmaker_core.py", "/analysis-component/%2e%2e/clipmaker_core.py",
                     "/analysis-component/..%5Cclipmaker_core.py", "/analysis-component/missing.js"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.request(path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()

    def test_analysis_state_round_trips_and_rejects_bad_input(self):
        state = {"analyst": {"tab": "pass-map", "controls": {"pass-map": {"team": "Southport"}}}}
        self.request(f"/api/projects/{self.project['id']}", {"analysis_state": state})
        _, body = self.request(f"/api/analysis/summary?project={self.project['id']}")
        self.assertEqual(json.loads(body)["analysis_state"], state)
        self.assertEqual(self.error(f"/api/projects/{self.project['id']}", {"analysis_state": {"analyst": {"tab": "../x"}}})[0], 400)
        _, body = self.request(f"/api/projects/{self.project['id']}")
        self.assertEqual(json.loads(body)["project"]["analysis_state"], state)

    def test_classic_workspace_url_carries_known_tab_only(self):
        with patch.object(self.server.analysis, "start", return_value=9999):
            _, body = self.request("/api/analysis", {"project_id": self.project["id"], "view": "analyst", "tab": "goalkeeper"})
            self.assertTrue(json.loads(body)["url"].endswith("&tab=goalkeeper"))
            _, body = self.request("/api/analysis", {"project_id": self.project["id"], "view": "analyst", "tab": "x&y=1"})
            self.assertNotIn("tab=", json.loads(body)["url"])


if __name__ == "__main__":
    unittest.main()
