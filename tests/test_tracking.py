"""Analyst editor player tracking (docs/TELESTRATION_PLAN.md, M3).

The clips are generated: a "player" (red shirt, light collar) running across
grass-coloured noise, optionally with a scene cut, so results are exact and
need no real footage.
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

import numpy as np

from app.telestration import annotations, segments, tracker
from packaging.clipmaker_api_server import create_server, _find_ffmpeg

W, H, FPS = 320, 240, 25
SEED = [(40 + 11) / W, 150 / H, 22 / W, 50 / H]  # footX, footY, width, height of the player at frame 0


def player_clip(path: Path, frames=50, cut_at=None) -> Path:
    rng = np.random.default_rng(7)
    grass = rng.integers(0, 60, (H, W, 3), dtype=np.uint8) + np.array([20, 110, 30], np.uint8)
    other = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt",
                                "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                                "-preset", "ultrafast", "-crf", "12", str(path)], stdin=subprocess.PIPE)
    for index in range(frames):
        frame = (other if cut_at is not None and index >= cut_at else grass).copy()
        x = 40 + 3 * index  # runs right, 3 px a frame
        frame[100:150, x:x + 22] = (40, 40, 220)
        frame[100:115, x + 4:x + 18] = (200, 200, 200)
        process.stdin.write(frame.tobytes())
    process.stdin.close()
    process.wait()
    return path


CLIP = {"fps": FPS, "width": W, "height": H, "frames": 50, "duration": 2.0}


class FlaggerTests(unittest.TestCase):
    def test_first_frame_is_the_keyframe(self):
        flagger = segments.Flagger(25)
        self.assertEqual(flagger.push((0.5, 0.5, 0.1, 0.2)), ("row", [0.5, 0.5, 0.1, 0.2, 1.0, segments.KEYFRAME]))
        self.assertEqual(flagger.push((0.5, 0.5, 0.1, 0.2), confidence=0.8, colour=0.1)[1][4:], [0.8, segments.TRACKED])

    def test_loss_and_edge_need_review(self):
        flagger = segments.Flagger(25)
        flagger.push((0.5, 0.5, 0.1, 0.2))
        self.assertEqual(flagger.push((0.5, 0.5, 0.1, 0.2), ok=False)[1][5], segments.REVIEW)
        self.assertEqual(flagger.push((0.5, 0.5, 0.1, 0.2), edge=True)[1][5], segments.REVIEW)
        self.assertEqual(flagger.push((0.5, 0.5, 0.1, 0.2), colour=0.0)[1][5], segments.TRACKED)

    def test_shirt_colour_must_stay_different_before_it_counts(self):
        flagger = segments.Flagger(25)  # 0.2 s = 5 frames
        flagger.push((0.5, 0.5, 0.1, 0.2))
        states = [flagger.push((0.5, 0.5, 0.1, 0.2), colour=1.0)[1][5] for _ in range(6)]
        self.assertEqual(states, [0, 0, 0, 0, 2, 2])  # one odd frame (a passing arm) is not enough

    def test_scene_cut_stops_at_once_and_a_second_of_doubt_stops(self):
        flagger = segments.Flagger(25)
        flagger.push((0.5, 0.5, 0.1, 0.2))
        self.assertEqual(flagger.push((0.5, 0.5, 0.1, 0.2), cut=True), ("stop", "scene-cut"))
        flagger = segments.Flagger(25)
        flagger.push((0.5, 0.5, 0.1, 0.2))
        results = [flagger.push((0.5, 0.5, 0.1, 0.2), ok=False)[0] for _ in range(25)]
        self.assertEqual(results.index("stop"), 24)

    def test_span_ends_before_the_next_keyframe(self):
        self.assertEqual(segments.span_end({10: 0, 40: 0, 90: 0}, 10, 200), 39)
        self.assertEqual(segments.span_end({10: 0}, 10, 200), 200)
        self.assertEqual(segments.span_end({10: 0, 40: 0}, 40, 60), 60)


def at(frame, dx=0):
    """The generated player's box on `frame`, optionally shifted `dx` pixels."""
    return [(40 + 3 * frame + 11 + dx) / W, 150 / H, 22 / W, 50 / H]


class BoxSizeTests(unittest.TestCase):
    """A real clip (2026-11-18): the tracker let its box swell over a crowd of players and nothing noticed."""

    def test_a_box_much_bigger_or_smaller_than_the_seed_is_doubted_then_stopped(self):
        flagger = segments.Flagger(25)
        flagger.push((0.5, 0.5, 0.05, 0.1))  # the seed: area 0.005
        states = lambda w, h: flagger.push((0.5, 0.5, w, h), colour=0.0)
        self.assertEqual(states(0.06, 0.11)[1][5], segments.TRACKED)  # a player coming nearer
        self.assertEqual(states(0.07, 0.14)[1][5], segments.REVIEW)  # twice the area: may be wrong
        self.assertEqual(states(0.04, 0.02)[1][5], segments.REVIEW)  # shrunk to a limb
        self.assertEqual(states(0.12, 0.2), ("stop", "lost"))  # nearly five times: not one player
        self.assertEqual(states(0.02, 0.02), ("stop", "lost"))  # a tenth of it: not the player either

    def test_slow_zoom_within_the_limits_is_not_flagged(self):
        flagger = segments.Flagger(25)
        flagger.push((0.5, 0.5, 0.05, 0.1))
        for scale in (1.02, 1.05, 1.1, 1.2, 1.25, 1.3):  # up to 1.7 times the area
            self.assertEqual(flagger.push((0.5, 0.5, 0.05 * scale, 0.1 * scale), colour=0.0)[1][5], segments.TRACKED, scale)

    def test_the_drawing_waits_where_the_player_was_last_trusted(self):
        class Swelling:  # a tracker whose box grows 20% in area every frame, as the real one did over a crowd
            def init(self, frame, box):
                self.box, self.n = list(box), 0

            def update(self, frame):
                self.n += 1
                grow = 1.2 ** (self.n / 2)
                x, y, w, h = self.box
                return True, (x, y, w * grow, h * grow)

        original = tracker.make_tracker
        tracker.make_tracker = lambda model=None: (Swelling(), None)
        try:
            frames = iter([np.full((H, W, 3), 90, np.uint8) for _ in range(40)])
            rows, reason, _ = tracker._follow(frames, SEED, (W, H), FPS, None, None, lambda: None)
        finally:
            tracker.make_tracker = original
        self.assertEqual(reason, "lost")
        self.assertLess(len(rows), 8)  # it stopped when the box passed four times the seed's area
        self.assertEqual(rows[0][5], segments.KEYFRAME)
        self.assertTrue(all(row[5] != segments.REVIEW for row in rows[-3:]), [row[5] for row in rows])  # no doubtful tail
        self.assertTrue(all(row[2] * row[3] < 1.9 * SEED[2] * SEED[3] for row in rows))  # nothing from the swollen frames is kept


class QualityTests(unittest.TestCase):
    """M5: blending passes, bridging holes, smoothing (pure functions)."""

    def rows(self, xs, state=segments.TRACKED):
        return [segments.row((x, 0.5, 0.02, 0.1), 0.9, state) for x in xs]

    def test_blend_leans_on_the_nearer_keyframe(self):
        forward = [segments.row((0.10, 0.5, 0.02, 0.1), 1.0, segments.KEYFRAME)] + self.rows([0.10] * 9)
        backward = self.rows([0.12] * 10)  # the analyst's next keyframe sits 0.02 to the right
        blended = segments.blend(forward, backward)
        self.assertEqual(blended[0], forward[0])  # the keyframe stays exactly where it was placed
        xs = [r[0] for r in blended]
        self.assertEqual(xs, sorted(xs))  # glides towards the next keyframe...
        self.assertAlmostEqual(xs[-1], 0.10 + 0.02 * 10 / 11, places=4)  # ...arriving almost on it

    def test_passes_on_different_players_ask_for_review(self):
        blended = segments.blend(self.rows([0.1] * 4), self.rows([0.5] * 4))
        self.assertEqual([r[5] for r in blended], [segments.REVIEW] * 4)
        self.assertEqual([r[0] for r in blended], [0.1, 0.1, 0.5, 0.5])  # each half trusts its own keyframe

    def test_one_pass_covers_what_the_other_lost(self):
        forward = self.rows([0.1, 0.11]) + [None, None]
        backward = [None] + self.rows([0.12, 0.13, 0.14])
        self.assertEqual([r is not None for r in segments.blend(forward, backward)], [True] * 4)

    def test_short_holes_are_bridged_for_review_and_long_ones_left(self):
        rows = self.rows([0.1]) + [None] * 3 + self.rows([0.5])
        filled = segments.fill_gaps(rows, fps=10)  # 0.5 s = 5 frames
        self.assertEqual([round(r[0], 3) for r in filled], [0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertEqual([r[5] for r in filled[1:4]], [segments.REVIEW] * 3)
        long = self.rows([0.1]) + [None] * 6 + self.rows([0.5])
        self.assertEqual(segments.fill_gaps(long, fps=10)[1:7], [None] * 6)
        self.assertEqual(segments.fill_gaps([None] + self.rows([0.1]), fps=10)[0], None)  # nothing before it

    def test_smoothing_calms_jitter_but_keeps_straight_runs_and_keyframes(self):
        straight = [segments.row((0.1 + 0.01 * i, 0.5, 0.02, 0.1), 1.0, segments.KEYFRAME if i == 0 else 0) for i in range(30)]
        self.assertEqual([round(r[0], 4) for r in segments.smooth(straight, 25)], [round(r[0], 4) for r in straight])
        jitter = [segments.row((0.3 + (0.01 if i % 2 else -0.01), 0.5, 0.02, 0.1), 1.0, 0) for i in range(30)]
        jitter[0] = segments.row((0.3, 0.5, 0.02, 0.1), 1.0, segments.KEYFRAME)
        smoothed = segments.smooth(jitter, 25)
        self.assertEqual(smoothed[0], jitter[0])
        self.assertEqual(smoothed[-1], jitter[-1])  # the end of a run stays put
        middle = [abs(r[0] - 0.3) for r in smoothed[8:22]]
        self.assertLess(max(middle), 0.0025)  # +-0.01 wobble mostly gone

    def test_finish_reports_where_coverage_stops(self):
        forward = self.rows([0.1, 0.11, 0.12])
        rows, stopped = segments.finish(20, 10, 25, forward, {"frame": 23, "reason": "scene-cut"})
        self.assertEqual((len(rows), stopped), (3, {"frame": 23, "reason": "scene-cut"}))
        backward = [None] * 3 + self.rows([0.2] * 7)
        rows, stopped = segments.finish(20, 10, 25, forward, {"frame": 23, "reason": "scene-cut"}, backward)
        self.assertEqual((len(rows), stopped), (10, None))  # the backward pass covered the rest


class TrackerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.clip = player_clip(Path(cls.folder.name) / "player.mp4")
        cls.cut = player_clip(Path(cls.folder.name) / "cut.mp4", cut_at=30)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_follows_the_player_to_within_a_few_pixels(self):
        result = tracker.track_span(_find_ffmpeg(), self.clip, CLIP, 0, 49, SEED)
        self.assertEqual(result["tracker"], "vit")
        self.assertIsNone(result["notice"])
        self.assertEqual(len(result["rows"]), 50)
        for index, row in enumerate(result["rows"]):
            self.assertLess(abs(row[0] * W - (51 + 3 * index)), 5, f"frame {index}")
            self.assertLess(abs(row[1] * H - 150), 5, f"frame {index}")

    def test_starts_on_the_requested_frame(self):
        later = [(40 + 3 * 20 + 11) / W, 150 / H, 22 / W, 50 / H]
        result = tracker.track_span(_find_ffmpeg(), self.clip, CLIP, 20, 29, later)
        self.assertEqual((result["start"], len(result["rows"])), (20, 10))
        self.assertLess(abs(result["rows"][-1][0] * W - (51 + 3 * 29)), 5)

    def test_scene_cut_stops_tracking(self):
        result = tracker.track_span(_find_ffmpeg(), self.cut, CLIP, 0, 49, SEED)
        self.assertEqual(len(result["rows"]), 30)
        self.assertEqual(result["stopped"], {"frame": 30, "reason": "scene-cut"})

    def test_arrives_on_the_next_keyframe_without_a_jump(self):
        result = tracker.track_span(_find_ffmpeg(), self.clip, CLIP, 0, 39, SEED, end_box=at(40))
        rows = result["rows"]
        self.assertEqual((len(rows), result["stopped"]), (40, None))
        self.assertLess(abs(rows[0][0] * W - 51), 1)  # starts on the first keyframe
        xs = [row[0] * W for row in rows] + [at(40)[0] * W]  # ...and runs on into the next one
        steps = [xs[i + 1] - xs[i] for i in range(40)]
        self.assertLess(max(abs(step - 3) for step in steps), 1.5)  # about 3 px a frame throughout, no jump

    def test_smoothing_steadies_the_raw_tracker(self):
        raw = tracker.track_span(_find_ffmpeg(), self.clip, CLIP, 0, 49, SEED)["rows"]
        wobble = [abs((raw[i + 1][0] - raw[i][0]) * W - 3) for i in range(49)]
        self.assertLess(sum(wobble) / len(wobble), 0.8)  # steady steps of 3 px (raw ViT output wobbles 1-2 px)

    def test_tracking_back_covers_the_far_side_of_a_scene_cut(self):
        result = tracker.track_span(_find_ffmpeg(), self.cut, CLIP, 0, 48, SEED, end_box=at(49))
        self.assertEqual((len(result["rows"]), result["stopped"]), (49, None))
        for frame in (10, 29, 30, 45):
            self.assertLess(abs(result["rows"][frame][0] * W - (51 + 3 * frame)), 5, frame)

    def test_missing_model_falls_back_with_a_notice(self):
        result = tracker.track_span(_find_ffmpeg(), self.clip, CLIP, 0, 9, SEED, model=Path("missing.onnx"))
        self.assertEqual((result["tracker"], result["notice"]), ("mil", tracker.REDUCED_NOTICE))
        self.assertEqual(len(result["rows"]), 10)

    def test_bundled_model_is_the_approved_file(self):
        import hashlib
        path = tracker.model_path()
        self.assertIsNotNone(path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         "2990f0b7cd44d92afa48cd97db6de7be113fc1d9594fddb74e2725c10478e91d")

    def test_cancel_stops_the_job(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(tracker.Cancelled):
            tracker.track_span(_find_ffmpeg(), self.clip, CLIP, 0, 49, SEED, cancel)
        jobs = tracker.TrackingJobs()
        job = jobs.start(lambda event, progress: (event.wait(5), (_ for _ in ()).throw(tracker.Cancelled()))[1])
        jobs.cancel(job["id"])
        for _ in range(50):
            if jobs.get(job["id"])["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(jobs.get(job["id"])["status"], "cancelled")


class TrackDocumentTests(unittest.TestCase):
    def track(self, **overrides):
        value = {"id": "t1", "keyframes": {"0": SEED}, "from": 0, "boxes": [SEED + [1, 1], None, SEED + [0.6, 2]]}
        value.update(overrides)
        return value

    def document(self, tracks, points=None):
        ring = {"id": "r1", "kind": "ring", "points": points or [{"track": "t1", "dx": 0, "dy": 0.002}],
                "geometry": {"rx": 0.03, "ry": 0.01}, "show": {"from": 0, "to": 1}}
        return {"version": 1, "items": [ring], "freezes": [], "tracks": tracks}

    def test_linked_points_and_tracks_round_trip(self):
        clean = annotations.clean_document(self.document([self.track(label="Saka")]), duration=2, frames=50)
        self.assertEqual(clean["tracks"][0]["boxes"][1], None)
        self.assertEqual(clean["tracks"][0]["label"], "Saka")
        self.assertEqual(clean["items"][0]["points"][0], {"track": "t1", "dx": 0, "dy": 0.002})

    def test_bad_tracks_are_refused(self):
        cases = {
            "linked to nobody": self.document([], [{"track": "t9", "dx": 0, "dy": 0}]),
            "keyframe off the clip": self.document([self.track(keyframes={"50": SEED})]),
            "no keyframe": self.document([self.track(keyframes={})]),
            "rows past the end": self.document([self.track(**{"from": 49})]),
            "bad state": self.document([self.track(boxes=[SEED + [1, 7]])]),
            "zero-size box": self.document([self.track(keyframes={"0": [0.5, 0.5, 0, 0.1]})]),
            "duplicate ids": self.document([self.track(), self.track()]),
            "unknown setting": self.document([self.track(colour="red")]),
            "far offset": self.document([self.track()], [{"track": "t1", "dx": 3, "dy": 0}]),
        }
        for name, value in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                annotations.clean_document(value, duration=2, frames=50)


class TrackingApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.data)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        project = self.server.match_store.create("Tracking test")
        self.server.media_files["preview"] = player_clip(self.data / "previews" / "player.mp4")
        clip = self.call("/api/editor/clips", {"project_id": project["id"], "media": "preview", "name": "Run"})[1]["clip"]
        self.path = f"/api/editor/{project['id']}/{clip['id']}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def call(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base + path, data=data, method="POST" if data else "GET",
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_tracking_job_reports_progress_and_rows(self):
        status, started = self.call(self.path + "/track", {"from_frame": 0, "to_frame": 49, "box": SEED})
        self.assertEqual(status, 202, started)
        job = started["job"]
        for _ in range(200):
            job = self.call(f"/api/editor-jobs/{job['id']}")[1]["job"]
            if job["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(job["progress"], 1.0)
        self.assertEqual((job["result"]["start"], len(job["result"]["rows"])), (0, 50))
        # The rows can be saved as a track the drawings follow.
        track = {"id": "t1", "keyframes": {"0": SEED}, "from": 0, "boxes": job["result"]["rows"]}
        document = {"version": 1, "freezes": [], "tracks": [track], "items": [
            {"id": "r1", "kind": "ring", "points": [{"track": "t1", "dx": 0, "dy": 0}], "geometry": {"rx": 0.03, "ry": 0.01},
             "show": {"from": 0, "to": 2}}]}
        status, saved = self.call(self.path, {"annotations": document})
        self.assertEqual(status, 200, saved)

    def test_tracking_requests_are_checked(self):
        cases = [
            ({"from_frame": 0, "to_frame": 50, "box": SEED}, 400),  # past the last frame
            ({"from_frame": 10, "to_frame": 5, "box": SEED}, 400),
            ({"from_frame": 0, "to_frame": 9, "box": [0.5, 0.5]}, 400),
            ({"from_frame": "0", "to_frame": 9, "box": SEED}, 400),
            ({"from_frame": 0, "to_frame": 49, "box": SEED, "to_box": SEED}, 400),  # no frame after the last one
            ({"from_frame": 0, "to_frame": 9, "box": SEED, "to_box": [0.5]}, 400),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(self.call(self.path + "/track", body)[0], expected)
        self.assertEqual(self.call(self.path.rsplit("/", 1)[0] + "/" + "0" * 32 + "/track",
                                   {"from_frame": 0, "to_frame": 9, "box": SEED})[0], 404)
        self.assertEqual(self.call("/api/editor-jobs/0123456789abcdef")[0], 404)
        self.assertEqual(self.call("/api/editor-jobs/..%2F..")[0], 404)
