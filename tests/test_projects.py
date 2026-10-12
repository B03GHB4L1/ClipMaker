import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from packaging.clipmaker_api_server import JobManager, MatchStore, build_clip_config, create_server, detect_source, video_for_period
from app.project_analysis import project_session


class ProjectStoreTests(unittest.TestCase):
    def test_build_helpers_do_not_hide_dependency_packaging_modules(self):
        from packaging.requirements import Requirement
        from packaging.version import Version
        self.assertEqual(Requirement("streamlit>=1.55").name, "streamlit")
        self.assertGreater(Version("1.55"), Version("1.54"))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = MatchStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_same_match_sessions_are_independent_and_survive_restart(self):
        first, second = self.store.create("Session A"), self.store.create("Session B")
        self.assertNotEqual(first["id"], second["id"])
        for project in (first, second):
            self.store.upsert({"id": project["id"], "home_team": "Home", "away_team": "Away"})
        self.store.upsert({"id": first["id"], "markers": {"1H": "00:03:18"},
                           "filter_settings": {"filter_types": ["Goal"], "video_crf": 24}})
        restarted = MatchStore(self.root)
        self.assertEqual(len(restarted.list()), 2)
        self.assertEqual(restarted.get(first["id"])["markers"], {"1H": "00:03:18"})
        self.assertEqual(restarted.get(second["id"])["markers"], {})
        self.assertTrue(self.store.project_path(first["id"]).is_file())

    def test_patch_preserves_filters_when_intake_saves(self):
        project = self.store.create()
        self.store.upsert({"id": project["id"], "filter_settings": {"xt_min": .2}})
        saved = self.store.upsert({"id": project["id"], "video_path": "match.mp4"})
        self.assertEqual(saved["filter_settings"], {"xt_min": .2})

    def test_snapshots_survive_ports_restarts_and_delete_is_recoverable(self):
        self.store.update_snapshot("Goals", {"filter_types": ["Goal"]})
        restarted = MatchStore(self.root)
        self.assertEqual(restarted.snapshots()["Goals"]["filter_types"], ["Goal"])
        restarted.update_snapshot("Goals", None)
        self.assertEqual(restarted.snapshots(), {})
        trash = list((self.root / "snapshot-trash").glob("*.json"))
        self.assertEqual(len(trash), 1)
        self.assertEqual(json.loads(trash[0].read_text())["Goals"]["filter_types"], ["Goal"])

    def test_legacy_history_remains_available_without_overwriting_original(self):
        original = [{"id": "old-match", "home_team": "Home", "markers": {"1H": "00:01:00"}}]
        self.store.path.write_text(json.dumps(original), encoding="utf-8")
        self.store.upsert({"id": "old-match", "project_name": "Reopened"})
        self.assertEqual(json.loads(self.store.path.read_text()), original)
        self.assertEqual(self.store.get("old-match")["markers"], original[0]["markers"])
        self.assertEqual(len(self.store.list()), 1)

    def test_rejects_path_traversal_and_invalid_clock_without_destroying_project(self):
        project = self.store.create()
        for identifier in ("../escape", "a/b", "a\\b", ""):
            with self.assertRaises(ValueError):
                self.store.project_path(identifier)
        with self.assertRaises(ValueError):
            self.store.upsert({"id": project["id"], "markers": {"1H": "00:99:00"}})
        self.assertEqual(self.store.get(project["id"])["markers"], {})

    def test_corrupt_history_does_not_get_silently_replaced(self):
        self.store.path.write_text("invalid json", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            self.store.create()
        self.assertEqual(self.store.path.read_text(), "invalid json")

    def test_source_detection_rejects_lookalike_hosts(self):
        for url in ("https://scoresway.com.evil.test/match", "file://scoresway.com/match", "https://fakewhoscored.com/match"):
            with self.assertRaises(ValueError):
                detect_source(url)

    def test_split_period_sources_and_analysis_state_agree(self):
        project = {"video_path": "first.mp4", "period_videos": {"2H": "second.mp4", "ET1": "extra.mp4", "PEN": "penalties.mp4"},
                   "markers": {"1H": "00:00:01", "2H": "00:00:02", "ET1": "00:00:03"},
                   "filter_settings": {"timeline_corrections": [{"period": 2, "seconds": -10}]}}
        self.assertEqual(video_for_period(project, 3), "extra.mp4")
        self.assertEqual(video_for_period(project, 4), "extra.mp4")
        self.assertEqual(video_for_period(project, 5), "penalties.mp4")
        state = project_session(project)
        self.assertTrue(state["split_video"])
        self.assertEqual(state["video3_path"], "extra.mp4")
        self.assertEqual(state["half2_time"], "00:00:02")
        self.assertEqual(state["timeline_corrections"], project["filter_settings"]["timeline_corrections"])

    def test_extra_time_file_does_not_require_a_separate_second_half(self):
        csv = self.root / "events.csv"
        csv.write_text("minute,second,type,period\n91,0,Goal,3\n", encoding="utf-8")
        project = {"csv_path": str(csv), "video_path": "regular.mp4",
                   "period_videos": {"ET1": "extra.mp4", "PEN": "penalties.mp4"},
                   "markers": {"1H": "00:00:00", "2H": "00:50:00", "ET1": "00:00:00"}}
        self.assertEqual(video_for_period(project, 2), "regular.mp4")
        self.assertEqual(video_for_period(project, 3), "extra.mp4")
        self.assertEqual(video_for_period(project, 4), "extra.mp4")
        self.assertEqual(video_for_period(project, 5), "penalties.mp4")
        config = build_clip_config(project, {}, self.root)
        state = project_session(project)
        self.assertTrue(config["split_video"])
        self.assertTrue(state["split_video"])
        self.assertEqual(config["video2_file"], state["video2_path"])
        self.assertEqual(config["video4_file"], state["video4_path"])

    def test_active_exports_reserve_names_and_cancel(self):
        def blocked_engine(config, logs, progress, cancellation):
            cancellation.wait(timeout=5)
            logs.put({"type": "cancelled"})

        manager = JobManager()
        config = {"dry_run": False, "output_dir": str(self.root), "output_filename": "reel.mp4"}
        with patch("clipmaker_core.run_clip_maker", side_effect=blocked_engine):
            first, second = manager.start(config), manager.start(config)
            self.assertNotEqual(first["output_filename"], second["output_filename"])
            for job in (first, second):
                self.assertTrue(manager.cancel(job["id"]))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and any(not manager.get(job["id"]).get("finished_at") for job in (first, second)):
                time.sleep(.05)
            for job in (first, second):
                self.assertEqual(manager.get(job["id"])["status"], "cancelled")
                self.assertIn("finished_at", manager.get(job["id"]))


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
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

    def request(self, path, body=None, headers=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", **(headers or {})})
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def test_create_update_reopen_project_api(self):
        project = self.request("/api/projects", {})["project"]
        self.request(f"/api/projects/{project['id']}", {"markers": {"2H": "00:45:00"}, "project_name": "My session"})
        reopened = self.request(f"/api/projects/{project['id']}")["project"]
        self.assertEqual(reopened["project_name"], "My session")
        self.assertEqual(reopened["markers"], {"2H": "00:45:00"})
        self.assertIn("directory", self.request("/api/projects"))

    def test_import_csv_is_saved_with_project(self):
        project = self.request("/api/projects", {})["project"]
        csv = b"minute,second,type,period,team,playerName\n1,0,Goal,1,Home,One\n46,0,Pass,2,Away,Two\n"
        request = Request(f"{self.url}/api/files/upload?project={project['id']}", data=csv,
                          headers={"Content-Type": "application/octet-stream", "X-File-Name": "match.csv"})
        with urlopen(request, timeout=5) as response:
            imported = json.loads(response.read())["match"]
        self.assertEqual(imported["event_count"], 2)
        self.assertEqual(imported["home_score"], 1)
        self.assertEqual(imported["id"], project["id"])
        self.assertTrue(Path(imported["csv_path"]).is_relative_to(self.root / "projects" / project["id"]))

    def test_cross_origin_request_is_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/projects", {}, {"Origin": "https://untrusted.test"})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_event_api_does_not_open_unregistered_files(self):
        path = self.root / "private.csv"
        path.write_text("minute,second,type\n1,0,Pass\n", encoding="utf-8")
        with self.assertRaises(HTTPError) as error:
            self.request("/api/events", {"csv_path": str(path)})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_media_suffix_and_unsatisfiable_range(self):
        path = self.root / "video.mp4"
        path.write_bytes(b"0123456789")
        self.server.media_files["test"] = path
        with urlopen(Request(self.url + "/api/media/test", headers={"Range": "bytes=-3"})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"789")
        for value in ("bytes=99-100", "bytes=8-3", "bytes=x-y", "bytes=-0"):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url + "/api/media/test", headers={"Range": value}))
            self.assertEqual(error.exception.code, 416)
            error.exception.close()
