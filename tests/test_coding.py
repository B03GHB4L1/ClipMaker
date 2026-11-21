"""Coding on recorded footage, milestone C1 (docs/CODING_AND_PITCH_PLAN.md):
coded events saved in video time, the derived event table, and a coded-only
project going through Filter's plan and an export."""
from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.coding import store, to_events
from app.clipmaker_core import assign_periods, match_clock_to_video_time, read_csv_safe, to_seconds
from packaging.clipmaker_api_server import _find_ffmpeg, create_server, video_for_period

MARKERS = {"1H": "0:05:00", "2H": "0:55:00", "ET1": "1:50:00", "ET2": "2:08:00"}
OFFSETS = {1: (0, 0), 2: (45, 0), 3: (90, 0), 4: (105, 0), 5: (120, 0)}
PERIOD_NUMBER = {"FirstHalf": 1, "SecondHalf": 2, "FirstPeriodOfExtraTime": 3, "SecondPeriodOfExtraTime": 4}


def event(event_id, t, code="goal", team="home", src="1H"):
    return {"id": event_id, "code": code, "team": team, "src": src, "t": t}


def single_video(_period):
    return "match.mp4"


class ClockTests(unittest.TestCase):
    def test_round_trip_across_halves_and_extra_time(self):
        times = [300.0, 301.4, 2999.6, 3300.0, 3301.2, 6599.0, 6600.0, 7000.7, 7680.0, 8000.2]
        document = {"events": [event(f"c{index:06d}", t) for index, t in enumerate(times)]}
        table, unplaced = to_events.rows(document, MARKERS, single_video)
        self.assertEqual(unplaced, [])
        starts = {number: to_seconds(MARKERS[key]) for number, key in ((1, "1H"), (2, "2H"), (3, "ET1"), (4, "ET2"))}
        for row in table:
            period = PERIOD_NUMBER[row["period"]]
            back = match_clock_to_video_time(row["minute"], row["second"], period, starts, OFFSETS)
            self.assertLessEqual(abs(back - row["video_time"]), 0.5, row)
        self.assertEqual([row["period"] for row in table][:3], ["FirstHalf"] * 3)
        self.assertEqual((table[3]["minute"], table[3]["second"]), (45, 0))  # 2H kick-off
        self.assertEqual(table[-1]["period"], "SecondPeriodOfExtraTime")

    def test_events_on_a_period_video_belong_to_that_file(self):
        project = {"video_path": "first.mp4", "period_videos": {"2H": "second.mp4"},
                   "markers": {"1H": "0:01:00", "2H": "0:00:10"}}
        document = {"events": [event("c000001", 3000, src="1H"), event("c000002", 30, src="2H")]}
        table, _ = to_events.rows(document, project["markers"], lambda period: video_for_period(project, period))
        # 3000 s into the first file is late in the first half, though it is after the 2H marker's second.
        self.assertEqual([(row["period"], row["minute"], row["second"]) for row in table],
                         [("FirstHalf", 49, 0), ("SecondHalf", 45, 20)])

    def test_codes_before_kick_off_are_left_out_and_named(self):
        document = {"events": [event("c000001", 120), event("c000002", 400)]}
        table, unplaced = to_events.rows(document, {"1H": "0:05:00"}, single_video)
        self.assertEqual(unplaced, ["c000001"])
        self.assertEqual(len(table), 1)
        _, unplaced = to_events.rows(document, {}, single_video)
        self.assertEqual(unplaced, ["c000001", "c000002"])

    def test_markers_parse_like_the_intake_clock(self):
        self.assertEqual(to_events.parse_marker("1:02:03"), 3723)
        self.assertEqual(to_events.parse_marker("62:03"), 3723)
        for bad in ("", None, "a:b", "-1:00", "1:2:3:4"):
            self.assertIsNone(to_events.parse_marker(bad), bad)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_add_update_delete_and_reopen(self):
        store.apply(self.folder, {"add": [event("c000002", 90.5), event("c000001", 10, code="corner", team="away")]})
        store.apply(self.folder, {"update": [{"id": "c000002", "t": 91}], "delete": ["c000001", "c000404"]})
        saved = store.read(self.folder)
        self.assertEqual(saved["events"], [event("c000002", 91.0)])

    def test_bad_events_are_refused_and_nothing_is_written(self):
        store.apply(self.folder, {"add": [event("c000001", 10)]})
        before = store.path_for(self.folder).read_bytes()
        bad = [
            {"add": [event("c000002", 5), event("c000003", 6, code="dance")]},
            {"add": [event("x1", 5)]},
            {"add": [{**event("c000002", 5), "path": "C:/secret"}]},
            {"add": [event("c000002", -1)]},
            {"add": [event("c000002", float("nan"))]},
            {"add": [event("c000002", 5, team="referee")]},
            {"add": [event("c000002", 5, src="3H")]},
            {"add": [event("c000001", 5)]},
            {"update": [{"id": "c000009", "t": 3}]},
            {"move": []},
            {"add": [event(f"c{n:06d}", 1) for n in range(2, store.MAX_CHANGES + 3)]},
        ]
        for changes in bad:
            with self.subTest(changes=str(changes)[:80]), self.assertRaises(ValueError):
                store.apply(self.folder, changes)
            self.assertEqual(store.path_for(self.folder).read_bytes(), before)

    def test_unreadable_saved_codes_are_not_overwritten(self):
        store.path_for(self.folder).write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(ValueError):
            store.apply(self.folder, {"add": [event("c000001", 1)]})
        self.assertEqual(store.path_for(self.folder).read_text(encoding="utf-8"), "[1, 2]")

    def test_codes_use_feed_type_names_and_distinct_keys(self):
        keys = [code["key"] for code in store.CODES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse({"h", "a", " "} & set(keys), "H and A choose the team; Space plays")
        self.assertTrue({"Goal", "SavedShot", "MissedShot", "CornerAwarded"} <= {code["type"] for code in store.CODES})


class DerivedTableTests(unittest.TestCase):
    def test_table_matches_the_scraped_schema_and_reads_back(self):
        with tempfile.TemporaryDirectory() as folder:
            document = {"events": [event("c000001", 400, team="home"), event("c000002", 3400, code="corner", team="away")]}
            table, _ = to_events.rows(document, MARKERS, single_video, "Reims", "Lens")
            path = to_events.write_csv(Path(folder) / "coded.csv", table)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                header = next(csv.reader(handle))
            for column in ("minute", "second", "type", "outcomeType", "period", "playerName", "team", "x", "y"):
                self.assertIn(column, header)
            frame = assign_periods(read_csv_safe(str(path)), "period", None)
            self.assertEqual(frame["resolved_period"].tolist(), [1, 2])
            self.assertEqual(frame["team"].tolist(), ["Reims", "Lens"])
            self.assertEqual(frame["type"].tolist(), ["Goal", "CornerAwarded"])


    def test_shot_map_counts_coded_shots_without_drawing_them(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
        from analysis_core import FrameCache, shot_map
        with tempfile.TemporaryDirectory() as folder:
            table, _ = to_events.rows({"events": [event("c000001", 400)]}, MARKERS, single_video, "Reims", "Lens")
            path = to_events.write_csv(Path(folder) / "coded.csv", table)
            view = shot_map.build_view(FrameCache().get(str(path)), {})
        self.assertIn("no pitch location", view["empty"])
        self.assertEqual(view["stats"][2], {"label": "Goals", "home": 1, "away": 0})
        self.assertFalse(view.get("components"))


class CodesApiTests(unittest.TestCase):
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
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def coded_project(self, video: Path):
        project = self.request("/api/projects", {})["project"]
        self.request(f"/api/projects/{project['id']}", {"video_path": str(video), "markers": {"1H": "0:00:05", "2H": "0:00:40"},
                                                        "home_team": "Reims", "away_team": "Lens"})
        return project["id"]

    def test_coded_only_project_filters_and_plans_clips(self):
        video = self.root / "match.mp4"
        video.write_bytes(b"not decoded by these requests")
        project_id = self.coded_project(video)
        result = self.request(f"/api/projects/{project_id}/codes", {"add": [
            event("c000001", 20.0, code="goal"), event("c000002", 50.0, code="corner", team="away"), event("c000003", 2.0)]})
        self.assertEqual(result["unplaced"], ["c000003"])
        project = result["project"]
        self.assertEqual((project["source"], project["event_count"]), ("coded", 2))
        self.assertTrue(Path(project["csv_path"]).is_file())
        self.assertEqual(len(self.request(f"/api/projects/{project_id}/codes")["events"]), 3)

        options = self.request("/api/filter-options", {"match_id": project_id})
        self.assertIn("Goal", json.dumps(options))
        self.assertIn("Lens", json.dumps(options))
        plan = self.request("/api/previews", {"match_id": project_id, "options": {"before_buffer": 3, "after_buffer": 2,
                                                                                    "filter_types": ["Goal"]}})
        self.assertEqual(len(plan["windows"]), 1)
        self.assertAlmostEqual(plan["windows"][0]["start"], 17.0, delta=0.6)

        # Moving a kick-off re-times the table: the codes themselves stay in video time.
        moved = self.request(f"/api/projects/{project_id}", {"markers": {"1H": "0:00:10", "2H": "0:00:40"}})["project"]
        with open(moved["csv_path"], encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual((rows[0]["minute"], rows[0]["second"]), ("0", "10"))

    def test_scraped_projects_keep_their_event_table(self):
        project = self.request("/api/projects", {})["project"]
        table = self.root / "scraped.csv"
        table.write_text("minute,second,type,period\n1,0,Pass,FirstHalf\n", encoding="utf-8")
        self.server.match_store.upsert({"id": project["id"], "csv_path": str(table), "source": "whoscored"})  # type: ignore[attr-defined]
        result = self.request(f"/api/projects/{project['id']}/codes", {"add": [event("c000001", 3)]})
        self.assertEqual(result["project"]["csv_path"], str(table))
        self.assertEqual(result["project"]["source"], "whoscored")
        with self.assertRaises(HTTPError) as error:
            self.request(f"/api/projects/{project['id']}", {"source": "coded"})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_bad_requests_are_refused(self):
        project = self.request("/api/projects", {})["project"]
        for path, body in ((f"/api/projects/{project['id']}/codes", {"add": [event("c000001", 1, code="dance")]}),
                           ("/api/projects/missing/codes", {"add": []}),
                           (f"/api/projects/{project['id']}/x/codes", {})):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.request(path, body)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request("/api/projects/missing/codes")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()

    def test_coded_moments_export_from_the_video(self):
        try:
            ffmpeg = _find_ffmpeg()
        except Exception:
            self.skipTest("ffmpeg is not available")
        video = self.root / "match.mp4"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=160x90:rate=25:duration=60", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                        "-preset", "ultrafast", str(video)], check=True)
        project_id = self.coded_project(video)
        self.request(f"/api/projects/{project_id}/codes", {"add": [event("c000001", 20.0), event("c000002", 50.0, code="corner")]})
        job = self.request("/api/jobs", {"match_id": project_id, "options": {
            "dry_run": False, "before_buffer": 2, "after_buffer": 2, "output_dir": str(self.root / "out"),
            "output_filename": "Coded.mp4", "video_encoder": "software", "encoder_preset": "ultrafast"}})["job"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = self.request(f"/api/jobs/{job['id']}")["job"]
            if job.get("finished_at"):
                break
            time.sleep(0.2)
        self.assertEqual(job["status"], "complete", job.get("logs", job)[-5:] if isinstance(job.get("logs"), list) else job)
        outputs = list((self.root / "out").rglob("*.mp4"))
        self.assertTrue(outputs and outputs[0].stat().st_size > 0, outputs)


if __name__ == "__main__":
    unittest.main()
