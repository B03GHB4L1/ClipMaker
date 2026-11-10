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

    def test_pressing_markers_carry_their_event_ids(self):
        # Without ids, clicks on the pressing map could never select a win.
        from analysis_core.pressing import pressing_option
        wins = [{"idx": 7, "press_zone": "High", "x": 80, "y": 40, "type": "Tackle", "minute": 3, "second": 4,
                 "period": "FirstHalf", "playerName": "A"},
                {"idx": 12, "press_zone": "Mid", "x": 60, "y": 20, "type": "BallRecovery", "minute": 9, "second": 0,
                 "period": "SecondHalf", "playerName": "B"}]
        markers = [point for series in pressing_option(wins, selected_idx=12)["series"] if series.get("name")
                   for point in series["data"]]
        self.assertEqual(sorted(point["customdata"] for point in markers), [7, 12])
        self.assertEqual(next(p for p in markers if p["customdata"] == 12)["symbolSize"], 22)
        frontend = (ROOT / "app" / "smp_component" / "frontend" / "index.html").read_text(encoding="utf-8")
        start = frontend.index("function renderEchartsOption")
        self.assertIn("Streamlit.setValue([id, Date.now()])", frontend[start:frontend.index("function cmNewPlot", start)])

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
        cases = {"": ("native", "native"), "native": ("native", "native"), "classic": ("classic", "classic"),
                 "analyst=classic": ("classic", "native"), "tactical=classic": ("native", "classic"),
                 "analyst=native,tactical=streamlit": ("native", "classic"), "bogus": ("native", "native")}
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
        self.assertEqual((views["analyst"]["mode"], views["tactical"]["mode"]), ("native", "native"))
        with patch.dict(os.environ, {"VIZORPLAY_ANALYSIS_UI": "analyst=classic"}):
            views = json.loads(self.request("/api/analysis/config")[1])["views"]
        self.assertEqual((views["analyst"]["mode"], views["tactical"]["mode"]), ("classic", "native"))

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
        # Every tab is native now; a tab marked classic still answers 501.
        from analysis_core import TABS
        entry = next(tab for tab in TABS["tactical"] if tab["slug"] == "style-profile")
        with patch.dict(entry, {"native": False}):
            code, payload = self.error("/api/analysis/tactical/style-profile", {"project_id": self.project["id"]})
        self.assertEqual((code, payload.get("classic")), (501, True))
        _, body = self.request("/api/analysis/tactical/style-profile", {"project_id": self.project["id"]})
        view = json.loads(body)["view"]
        self.assertEqual((view["team"], view["scope"]["multi"]), ("Northbridge", False))
        self.assertTrue(any(element["kind"] == "plotly" for element in view["elements"]))
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

    def test_shot_map_view_and_clip_validation(self):
        project_id = self.project["id"]
        _, body = self.request("/api/analysis/analyst/shot-map", {"project_id": project_id, "controls": {"team": "Southport"}})
        view = json.loads(body)["view"]
        self.assertEqual(view["controls"]["team"], "Southport")
        self.assertEqual(view["components"][-1]["args"]["component_type"], "shot_map")
        self.assertEqual(view["clip_defaults"], {"before": 5, "after": 8})
        selected = view["picker"]["items"][0]["id"]
        clip = "/api/analysis/analyst/shot-map/clip"
        bad = [({"controls": {"selected": selected}, "before": 61, "after": 8}, "between 0 and 60"),
               ({"controls": {"selected": selected}, "before": "x", "after": 8}, "between 0 and 60"),
               ({"controls": {"selected": None}, "before": 5, "after": 8}, "No video file"),
               ]
        for extra, message in bad:
            with self.subTest(extra=extra):
                code, payload = self.error(clip, {"project_id": project_id, **extra})
                self.assertEqual(code, 400)
                self.assertIn(message, payload["error"])
        self.assertEqual(self.error("/api/analysis/analyst/shot-map/other", {"project_id": project_id})[0], 400)
        code, payload = self.error("/api/analysis/tactical/style-profile/clip", {"project_id": project_id})
        self.assertEqual(code, 400)
        self.assertIn("Video Lab", payload["error"])

    def test_shot_map_clip_uses_classic_timing(self):
        import subprocess

        import imageio_ffmpeg
        video = self.root / "match.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=5",
                        "-t", "1500", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video)],
                       check=True, capture_output=True, timeout=300)
        MatchStore(self.root).upsert({"id": self.project["id"], "video_path": str(video),
                                      "markers": {"1H": "00:00:30", "2H": "00:00:30"}})
        _, body = self.request("/api/analysis/analyst/shot-map", {"project_id": self.project["id"], "controls": {}})
        # A first-half shot well inside the 25-minute test video.
        shot = next({"id": item["df_idx"]} for item in json.loads(body)["view"]["components"][-1]["args"]["shots"]
                    if item["period"] == "FirstHalf" and 1 <= item["minute"] < 20)
        code, payload = self.error("/api/analysis/analyst/shot-map/clip",
                                   {"project_id": self.project["id"], "controls": {"selected": None}, "before": 3, "after": 4})
        self.assertIn("Select an event", payload["error"])
        _, body = self.request("/api/analysis/analyst/shot-map/clip",
                               {"project_id": self.project["id"], "controls": {"selected": shot["id"]}, "before": 3, "after": 4})
        file = json.loads(body)["file"]
        self.assertEqual((file["before"], file["after"]), (3, 4))
        status, data = self.request(file["url"])
        self.assertEqual(status, 200)
        clip = self.root / "clip.mp4"
        clip.write_bytes(data)
        probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(clip)], capture_output=True, text=True)
        match = __import__("re").search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr)
        seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
        self.assertAlmostEqual(seconds, 7.0, delta=0.6)

    def test_classic_workspace_url_carries_known_tab_only(self):
        with patch.object(self.server.analysis, "start", return_value=9999):
            _, body = self.request("/api/analysis", {"project_id": self.project["id"], "view": "analyst", "tab": "goalkeeper"})
            self.assertTrue(json.loads(body)["url"].endswith("&tab=goalkeeper"))
            _, body = self.request("/api/analysis", {"project_id": self.project["id"], "view": "analyst", "tab": "x&y=1"})
            self.assertNotIn("tab=", json.loads(body)["url"])


if __name__ == "__main__":
    unittest.main()
