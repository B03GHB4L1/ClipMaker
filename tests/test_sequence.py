"""Annotate sequences (docs/CODING_AND_PITCH_PLAN.md, T2): a session's clips in order, exported as one video.

The pieces are real ffmpeg clips of different sizes, one without sound, so the
join is checked for what an analyst would notice: every clip is there, in order,
at the first clip's size, and the sound stays in step.
"""
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.telestration import export
from app.telestration.tracker import read_frames
from packaging.clipmaker_api_server import create_server, _find_ffmpeg, save_to_user_folder


def colour_clip(path: Path, colour: str, size=(160, 120), fps=10, seconds=1, sound=True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", f"color=c={colour}:s={size[0]}x{size[1]}:r={fps}:d={seconds}"]
    if sound:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
    command += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10"]
    command += ["-c:a", "aac", "-shortest"] if sound else []
    subprocess.run(command + [str(path)], check=True)
    return path


def piece(width=160, height=120, fps=10, seconds=1.0, sound=True):
    return {"width": width, "height": height, "fps": fps, "seconds": seconds, "sound": sound}


class JoinPlanTests(unittest.TestCase):
    def test_matching_pieces_are_copied(self):
        plan = export.join_plan([piece(), piece(seconds=2)])
        self.assertTrue(plan["copy"])
        self.assertEqual((plan["width"], plan["height"], plan["fps"], plan["seconds"]), (160, 120, 10.0, 3.0))

    def test_first_clip_sets_the_size_and_others_are_fitted(self):
        plan = export.join_plan([piece(), piece(width=320, height=180)])
        self.assertFalse(plan["copy"])
        graph = export.join_filter([piece(), piece(width=320, height=180)], plan)
        self.assertIn("[1:v]scale=160:120:force_original_aspect_ratio=decrease,pad=160:120", graph)
        self.assertTrue(graph.endswith("concat=n=2:v=1:a=1[v][a]"))

    def test_a_clip_without_sound_gets_silence(self):
        pieces = [piece(), piece(sound=False, seconds=1.5)]
        plan = export.join_plan(pieces)
        self.assertFalse(plan["copy"])  # sound in one, none in the other: cannot copy
        self.assertIn("anullsrc=r=48000:cl=stereo,atrim=duration=1.500000", export.join_filter(pieces, plan))

    def test_no_sound_anywhere_joins_picture_only(self):
        pieces = [piece(sound=False), piece(sound=False, fps=25)]
        plan = export.join_plan(pieces)
        self.assertFalse(plan["sound"])
        self.assertTrue(export.join_filter(pieces, plan).endswith("concat=n=2:v=1:a=0[v]"))

    def test_odd_sizes_are_made_even(self):
        self.assertEqual(export.join_plan([piece(width=161, height=121)])["width"], 160)

    def test_an_empty_sequence_is_refused(self):
        with self.assertRaises(ValueError):
            export.join_plan([])


class SequenceRenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def session(self, name, clip, size, sound=True, frames=10):
        folder = self.root / "exports" / name
        folder.mkdir(parents=True)
        record = {"fps": 10, "width": size[0], "height": size[1], "duration": 1, "frames": 10}
        return {"folder": folder, "video": clip, "record": record, "freezes": [], "frames": frames}

    def test_clips_of_different_sizes_join_in_order(self):
        red = colour_clip(self.root / "red.mp4", "red")
        blue = colour_clip(self.root / "blue.mp4", "blue", size=(320, 180), sound=False)
        sessions = [self.session("a", red, (160, 120)), self.session("b", blue, (320, 180), sound=False)]
        shares = []
        result = export.run_sequence(_find_ffmpeg(), sessions, self.root / "out", "Two clips", save_to_user_folder,
                                     lambda path: "id", threading.Event(), lambda done, total: shares.append(done / total),
                                     "software")
        output = self.root / "out" / "Two clips.mp4"
        self.assertEqual(result["clips"], 2)
        frames = list(read_frames(_find_ffmpeg(), output, 10, 0, 30, (160, 120)))
        self.assertEqual(len(frames), 20)
        self.assertGreater(int(frames[3][60, 80][2]), 200)  # red first (BGR)
        self.assertGreater(int(frames[15][60, 80][0]), 200)  # then blue, fitted to 160x120
        self.assertTrue(export.has_audio(_find_ffmpeg(), output))
        self.assertEqual(shares, sorted(shares))
        self.assertFalse(any(session["folder"].exists() for session in sessions))

    def test_cancel_leaves_no_file_and_no_overlays(self):
        red = colour_clip(self.root / "red.mp4", "red")
        sessions = [self.session("a", red, (160, 120)), self.session("b", red, (160, 120))]
        cancel = threading.Event()
        out = self.root / "cancelled"
        with self.assertRaises(export.Cancelled):
            export.run_sequence(_find_ffmpeg(), sessions, out, "Never", save_to_user_folder, lambda path: "id", cancel,
                                lambda done, total: done > 100 and cancel.set(), "software")
        self.assertFalse(out.exists() and any(out.iterdir()))
        self.assertFalse(any(session["folder"].exists() for session in sessions))


class SequenceApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.data)
        self.server.default_export_dir = self.data / "Videos"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.project = self.server.match_store.create("Sequence test")["id"]
        self.clips = []
        for name, colour in (("Red", "red"), ("Blue", "blue"), ("Green", "green")):
            self.server.media_files[name] = colour_clip(self.data / "previews" / f"{name}.mp4", colour)
            body = {"project_id": self.project, "media": name, "name": name}
            if self.clips:
                body["session_id"] = self.session_id
            status, created = self.call("/api/editor/clips", body)
            self.assertEqual(status, 201, created)
            self.clips.append(created["clip"]["id"])
            self.session_id = created["session"]["id"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def call(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base + path, data=data, method="POST" if data is not None else "GET",
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def sessions(self):
        return self.call(f"/api/editor-sessions/{self.project}")[1]["sessions"]

    def test_reorder_is_saved_and_checked(self):
        path = f"/api/editor-sessions/{self.project}/reorder"
        order = [self.clips[2], self.clips[0], self.clips[1]]
        status, body = self.call(path, {"session_id": self.session_id, "clips": order})
        self.assertEqual(status, 200, body)
        self.assertEqual([clip["id"] for clip in self.sessions()[0]["clips"]], order)
        self.assertEqual(self.call(path, {"session_id": self.session_id, "clips": order[:2]})[0], 400)  # one missing
        self.assertEqual(self.call(path, {"session_id": self.session_id, "clips": [order[0]] * 3})[0], 400)
        self.assertEqual(self.call(path, {"session_id": self.session_id, "clips": ["../x"] * 3})[0], 400)
        self.assertEqual(self.call(path, {"session_id": "s" + "0" * 16, "clips": order})[0], 404)

    def test_sessions_report_each_clips_exported_length(self):
        clip = self.clips[0]
        document = {"version": 1, "freezes": [{"atFrame": 5, "seconds": 2.0}], "items": []}
        self.assertEqual(self.call(f"/api/editor/{self.project}/{clip}", {"annotations": document})[0], 200)
        seconds = {c["id"]: c["seconds"] for c in self.sessions()[0]["clips"]}
        self.assertAlmostEqual(seconds[clip], 3.0)

    def test_a_clip_moves_in_from_another_session(self):
        self.server.media_files["Other"] = colour_clip(self.data / "previews" / "Other.mp4", "white")
        other = self.call("/api/editor/clips", {"project_id": self.project, "media": "Other", "name": "Other"})[1]
        status, _ = self.call(f"/api/editor-sessions/{self.project}/move-clip",
                              {"session_id": self.session_id, "clip_id": other["clip"]["id"]})
        self.assertEqual(status, 200)
        sessions = self.sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["clips"][-1]["id"], other["clip"]["id"])

    def test_sequence_renders_every_clip_in_order(self):
        ids = []
        for clip in self.clips:
            status, body = self.call(f"/api/editor/{self.project}/{clip}/export", {})
            self.assertEqual(status, 201, body)
            ids.append(body["export"]["id"])
        status, body = self.call("/api/editor-sequences/render", {"exports": ids, "name": "Whole session"})
        self.assertEqual(status, 202, body)
        job = body["job"]
        for _ in range(600):
            job = self.call(f"/api/editor-jobs/{job['id']}")[1]["job"]
            if job["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "done", job)
        output = self.data / "Videos" / job["result"]["saved"]["name"]
        frames = list(read_frames(_find_ffmpeg(), output, 10, 0, 40, (160, 120)))
        self.assertEqual(len(frames), 30)
        self.assertGreater(int(frames[5][60, 80][2]), 200)  # red, blue, green
        self.assertGreater(int(frames[15][60, 80][0]), 200)
        self.assertGreater(int(frames[25][60, 80][1]), 100)
        self.assertFalse(any((self.data / "editor-exports").iterdir()))
        self.assertEqual(self.call("/api/editor-sequences/render", {"exports": ids})[0], 404)  # renders once

    def test_sequence_requests_are_checked(self):
        render = lambda body: self.call("/api/editor-sequences/render", body)[0]
        self.assertEqual(render({"exports": []}), 400)
        self.assertEqual(render({"exports": ["../../etc"]}), 400)
        self.assertEqual(render({"exports": ["0123456789abcdef"]}), 404)
        one = self.call(f"/api/editor/{self.project}/{self.clips[0]}/export", {})[1]["export"]["id"]
        self.assertEqual(render({"exports": [one, one]}), 400)


if __name__ == "__main__":
    unittest.main()
