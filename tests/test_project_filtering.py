"""Filtering works the same over one match or several: a project uses all its saved matches at once."""
import json
import re
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import imageio_ffmpeg

from packaging.clipmaker_api_server import create_server

HEADER = "minute,second,type,team,period,playerName,x,y,outcomeType\n"
MATCH_A = HEADER + "1,0,Goal,Home A,1,Ann,90,50,Successful\n2,0,Pass,Home A,1,Bob,40,50,Successful\n3,0,Pass,Away A,1,Dan,30,50,Successful\n"
MATCH_B = HEADER + "1,30,Goal,Home B,1,Ann,90,50,Successful\n2,30,Shot,Away B,1,Cat,80,50,Unsuccessful\n3,30,Pass,Home B,1,Eve,40,50,Successful\n"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def make_video(path: Path, seconds: int, colour: str) -> None:
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=160x90:r=10", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=mono", "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True)


def duration_of(path: Path) -> float:
    text = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


class ProjectFilteringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.root / "data")
        self.store = self.server.match_store
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.video_a, self.video_b = self.root / "a.mp4", self.root / "b.mp4"
        make_video(self.video_a, 150, "red")
        make_video(self.video_b, 150, "blue")
        (self.root / "a.csv").write_text(MATCH_A, encoding="utf-8")
        (self.root / "b.csv").write_text(MATCH_B, encoding="utf-8")
        project = self.store.create("Two games")
        self.project_id = project["id"]
        first = self.store.upsert({"id": self.project_id, "home_team": "Home A", "away_team": "Away A",
                                   "csv_path": str(self.root / "a.csv"), "video_path": str(self.video_a),
                                   "markers": {"1H": "00:00:10", "2H": "00:01:50"}})
        self.match_a = first["match_id"]
        second = self.store.add_match(self.project_id)
        second = self.store.upsert({"id": self.project_id, "home_team": "Home B", "away_team": "Away B",
                                    "csv_path": str(self.root / "b.csv"), "video_path": str(self.video_b),
                                    "markers": {"1H": "00:00:20", "2H": "00:02:00"}})
        self.match_b = second["match_id"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def post(self, path, payload):
        request = Request(self.base + path, data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as response:
            return json.loads(response.read())

    def error(self, path, payload):
        with self.assertRaises(HTTPError) as context:
            self.post(path, payload)
        message = json.loads(context.exception.read())["error"]
        context.exception.close()
        return message

    def finish(self, job):
        for _ in range(240):
            job = self.get(f"/api/jobs/{job['id']}")["job"]
            if job["status"] in {"complete", "failed", "cancelled"}:
                return job
            time.sleep(0.5)
        self.fail("export did not finish")

    OPTIONS = {"filter_types": ["Goal"], "half_filter": "1st half only", "before_buffer": 5, "after_buffer": 8}

    def test_the_filter_lists_cover_every_match_of_the_project(self):
        options = self.post("/api/filter-options", {"match_id": self.project_id})
        self.assertEqual(options["action_types"], ["Goal", "Pass", "Shot"])
        self.assertEqual(sorted(options["team_players"]), ["Away A", "Away B", "Home A", "Home B"])
        self.assertIn("Cat", options["team_players"]["Away B"])
        self.assertEqual([item["id"] for item in options["matches"]], [self.match_a, self.match_b])
        self.assertEqual(options["event_count"], 6)
        index = options["events"]
        self.assertEqual(index["matches"], [self.match_a, self.match_b])
        self.assertEqual(index["match"], [0, 0, 0, 1, 1, 1])  # each event knows its match
        self.assertEqual(len(index["type"]), 6)

    def test_a_single_match_project_has_one_entry_in_the_matches_list(self):
        solo = self.store.create("Solo")
        self.store.upsert({"id": solo["id"], "home_team": "H", "away_team": "A", "csv_path": str(self.root / "a.csv")})
        options = self.post("/api/filter-options", {"match_id": solo["id"]})
        self.assertEqual(len(options["matches"]), 1)
        self.assertEqual(options["event_count"], 3)

    def test_a_new_project_with_no_matches_opens_the_filter_page_empty(self):
        empty = self.store.create("Fresh")
        options = self.post("/api/filter-options", {"match_id": empty["id"]})
        self.assertEqual((options["event_count"], options["matches"], options["action_types"]), (0, [], []))
        self.assertEqual(options["project_matches"], [])

    def test_clips_are_found_in_every_match_each_with_its_own_kickoffs(self):
        windows = self.post("/api/previews", {"match_id": self.project_id, "options": self.OPTIONS})["windows"]
        self.assertEqual([(w["match_id"], w["match_title"]) for w in windows],
                         [(self.match_a, "Home A v Away A"), (self.match_b, "Home B v Away B")])
        # A kicks off at 10 s (goal at 1:00 -> 70 s), B at 20 s (goal at 1:30 -> 110 s); buffers 5 s before, 8 after.
        self.assertAlmostEqual(windows[0]["start"], 65, delta=1)
        self.assertAlmostEqual(windows[1]["start"], 105, delta=1)
        self.assertEqual([w["id"] for w in windows], [1, 2])

    def test_the_matches_filter_narrows_the_search(self):
        options = {**self.OPTIONS, "match_ids": [self.match_b]}
        windows = self.post("/api/previews", {"match_id": self.project_id, "options": options})["windows"]
        self.assertEqual([w["match_id"] for w in windows], [self.match_b])

    def test_player_filters_skip_matches_the_player_is_not_in(self):
        options = {**self.OPTIONS, "filter_types": [], "player_filters": ["Cat"]}
        windows = self.post("/api/previews", {"match_id": self.project_id, "options": options})["windows"]
        self.assertEqual([w["match_id"] for w in windows], [self.match_b])
        nobody = self.post("/api/previews", {"match_id": self.project_id,
                                             "options": {**options, "player_filters": ["Nobody"]}})
        self.assertEqual(nobody["windows"], [])  # no match has the player: nothing found, not an error

    def test_a_match_without_kickoffs_is_named_in_the_error(self):
        self.store.set_active_match(self.project_id, self.match_b)
        self.store.upsert({"id": self.project_id, "markers": {}})
        message = self.error("/api/previews", {"match_id": self.project_id, "options": self.OPTIONS})
        self.assertTrue(message.startswith("Home B v Away B: "), message)
        self.assertIn("kick-off", message)

    def colour_of(self, path, at=1):
        pixel = subprocess.run([FFMPEG, "-ss", str(at), "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                                "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return pixel[0], pixel[2]  # red, blue of the first pixel

    def test_a_clip_is_rendered_from_the_video_of_its_own_match(self):
        sources = {}
        for name, match_id in (("a", self.match_a), ("b", self.match_b)):
            result = self.post("/api/previews/render", {"match_id": self.project_id, "start": 70, "end": 76, "period": 1,
                                                        "source_match_id": match_id})
            with urlopen(self.base + result["file"]["url"], timeout=20) as response:
                clip = self.root / f"clip-{name}.mp4"
                clip.write_bytes(response.read())
            sources[name] = self.colour_of(clip)
        self.assertGreater(sources["a"][0], sources["a"][1])  # match A's red video
        self.assertGreater(sources["b"][1], sources["b"][0])  # match B's blue video
        self.assertEqual(self.error("/api/previews/render", {"match_id": self.project_id, "start": 1, "end": 3,
                                                             "period": 1, "source_match_id": "gone"}),
                         "That match is no longer in this project.")

    def test_the_player_opens_the_video_of_the_clips_own_match(self):
        for match_id, video in ((self.match_a, self.video_a), (self.match_b, self.video_b)):
            file = self.post("/api/files/reopen", {"match_id": self.project_id, "period": "1H",
                                                   "source_match_id": match_id})["file"]
            self.assertTrue(Path(file["path"]).samefile(video))
        self.assertEqual(self.error("/api/files/reopen", {"match_id": self.project_id, "source_match_id": "gone"}),
                         "That match is no longer in this project.")

    def windows(self):
        return self.post("/api/previews", {"match_id": self.project_id, "options": self.OPTIONS})["windows"]

    def export(self, **extra):
        out = self.root / "exports"
        options = {**self.OPTIONS, "dry_run": False, "output_dir": str(out), "output_filename": "Goals",
                   "clip_windows": self.windows(), **extra}
        return out, self.post("/api/jobs", {"match_id": self.project_id, "options": options})

    def test_one_reel_takes_each_clip_from_its_own_matchs_video(self):
        out, result = self.export()
        job = self.finish(result["job"])
        self.assertEqual(job["status"], "complete", job["logs"][-3:])
        [file] = job["files"]
        self.assertEqual(file["name"], "Goals.mp4")
        self.assertAlmostEqual(duration_of(Path(file["path"])), 26, delta=2.5)  # two 13 s clips
        shot = subprocess.run([FFMPEG, "-ss", "3", "-i", file["path"], "-frames:v", "1", "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        late = subprocess.run([FFMPEG, "-ss", "20", "-i", file["path"], "-frames:v", "1", "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        self.assertGreater(shot[0], shot[2])  # the first clip is match A's red video...
        self.assertGreater(late[2], late[0])  # ...the second is match B's blue one

    def test_one_reel_per_match_makes_a_file_for_each(self):
        out, result = self.export(export_mode="per_match")
        self.assertEqual(len(result["jobs"]), 2)
        jobs = [self.finish(job) for job in result["jobs"]]
        self.assertEqual([job["status"] for job in jobs], ["complete", "complete"])
        self.assertEqual(sorted(file["name"] for job in jobs for file in job["files"]),
                         ["Goals - Home A v Away A.mp4", "Goals - Home B v Away B.mp4"])
        for job in jobs:
            self.assertAlmostEqual(duration_of(Path(job["files"][0]["path"])), 13, delta=2)

    def test_export_names_the_match_whose_video_is_missing(self):
        self.video_b.unlink()
        message = self.error("/api/jobs", {"match_id": self.project_id, "options": {
            **self.OPTIONS, "dry_run": False, "output_dir": str(self.root / "exports"), "clip_windows": self.windows()}})
        self.assertIn("Home B v Away B", message)
        self.assertIn("video was not found", message)

    def test_clip_windows_cannot_name_a_malformed_match(self):
        windows = [{**self.windows()[0], "match_id": "../x"}]
        out, result = self.export(clip_windows=windows)
        job = self.finish(result["job"])
        self.assertEqual(job["status"], "complete")  # the bad id is dropped; the clip uses the project's own match


if __name__ == "__main__":
    unittest.main()
