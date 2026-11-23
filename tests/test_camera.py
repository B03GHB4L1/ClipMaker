"""Following the camera through a clip (docs/CODING_AND_PITCH_PLAN.md, P2).

The clips are generated: a textured "ground" with lines and boards, filmed by a
camera that pans right and zooms in at a known rate, with players running the
other way, so the camera's true path is known exactly and needs no real footage.
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

import cv2
import numpy as np

from app.telestration import annotations, camera, tracker
from packaging.clipmaker_api_server import create_server, _find_ffmpeg

W, H, FPS, FRAMES = 640, 360, 25, 60
CLIP = {"fps": FPS, "width": W, "height": H, "frames": FRAMES, "duration": FRAMES / FPS}
SCALE = np.diag([W, H, 1.0])


def world() -> np.ndarray:
    rng = np.random.default_rng(3)
    ground = rng.integers(0, 40, (900, 2400, 3), dtype=np.uint8) + np.array([30, 120, 40], np.uint8)
    ground = cv2.GaussianBlur(ground, (3, 3), 0)
    for x in range(0, 2400, 300):
        cv2.line(ground, (x, 200), (x + 120, 880), (235, 235, 235), 3)
    cv2.line(ground, (0, 220), (2400, 230), (235, 235, 235), 3)
    cv2.line(ground, (0, 700), (2400, 720), (235, 235, 235), 3)
    for x in range(0, 2400, 160):  # boards along the far side
        cv2.rectangle(ground, (x, 120), (x + 140, 180), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
    return ground


def view(frame: int) -> np.ndarray:
    """Frame pixels -> ground pixels: the camera pans right 9 px a frame and zooms in slowly."""
    zoom = 1 + 0.004 * frame
    return np.array([[1 / zoom, 0, 300 + 9 * frame], [0, 1 / zoom, 150 + frame], [0, 0, 1]], float)


def camera_clip(path: Path, cut_at: int | None = None) -> Path:
    ground = world()
    other = cv2.GaussianBlur(np.random.default_rng(9).integers(0, 255, (H, W, 3), dtype=np.uint8), (5, 5), 0)
    process = subprocess.Popen([_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt",
                                "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                                "-preset", "veryfast", "-crf", "16", str(path)], stdin=subprocess.PIPE)
    for index in range(FRAMES):
        if cut_at is not None and index >= cut_at:  # another camera: a different picture, moving its own way
            frame = np.roll(other, 4 * (index - cut_at), axis=1)
        else:
            frame = cv2.warpPerspective(ground, np.linalg.inv(view(index)), (W, H))
            for k in range(6):  # players running the other way
                x = int(50 + 100 * k - 6 * index) % W
                cv2.rectangle(frame, (x, 200 + 10 * k), (x + 14, 240 + 10 * k), (30, 30, 200), -1)
        process.stdin.write(frame.tobytes())
    process.stdin.close()
    process.wait()
    return path


def true_path(frame: int, start: int = 0) -> np.ndarray:
    """Frame `frame` fractions -> frame `start` fractions."""
    return np.linalg.inv(SCALE) @ np.linalg.inv(view(start)) @ view(frame) @ SCALE


def pixels_off(row: list[float], expected: np.ndarray) -> float:
    found = np.array(row[:8] + [1]).reshape(3, 3)
    worst = 0.0
    for point in ([0.2, 0.3], [0.8, 0.7], [0.5, 0.5]):
        a = found @ [*point, 1]
        b = expected @ [*point, 1]
        worst = max(worst, float(np.hypot(*((a[:2] / a[2] - b[:2] / b[2]) * [W, H]))))
    return worst


class CameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.clip = camera_clip(Path(cls.folder.name) / "pan.mp4")
        cls.cut = camera_clip(Path(cls.folder.name) / "cut.mp4", cut_at=35)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_follows_a_pan_and_zoom_to_within_a_pixel_or_two(self):
        result = camera.follow_camera(_find_ffmpeg(), self.clip, CLIP, 0, FRAMES - 1)
        self.assertEqual((result["from"], len(result["rows"]), result["starts"]), (0, FRAMES, [0]))
        self.assertEqual(result["rows"][0], [1, 0, 0, 0, 1, 0, 0, 0, 1.0])
        for frame, row in enumerate(result["rows"]):
            self.assertLess(pixels_off(row, true_path(frame)), 2.0, f"frame {frame}")
            self.assertTrue(0 <= row[8] <= 1)
        # The camera really moved: by the last frame the picture has panned most of a frame width.
        self.assertGreater(true_path(FRAMES - 1)[0, 2] * W, 400)

    def test_starts_on_the_requested_frame(self):
        result = camera.follow_camera(_find_ffmpeg(), self.clip, CLIP, 20, 39)
        self.assertEqual((result["from"], len(result["rows"]), result["starts"]), (20, 20, [20]))
        self.assertLess(pixels_off(result["rows"][-1], true_path(39, 20)), 2.0)

    def test_a_scene_cut_starts_a_new_stretch(self):
        result = camera.follow_camera(_find_ffmpeg(), self.cut, CLIP, 0, FRAMES - 1)
        self.assertEqual(result["starts"], [0, 35])
        self.assertEqual(result["rows"][35][:8], [1, 0, 0, 0, 1, 0, 0, 0])
        self.assertLess(pixels_off(result["rows"][34], true_path(34)), 2.0)

    def test_the_path_saves_with_the_pitch(self):
        result = camera.follow_camera(_find_ffmpeg(), self.cut, CLIP, 0, FRAMES - 1)
        marks = [{"id": "half-far", "at": [0.3, 0.22]}, {"id": "circle-right", "at": [0.1756, 0.5733]},
                 {"id": "box-r-far", "at": [0.8774, 0.3636]}, {"id": "box-r-near", "at": [0.6291, 0.9506]}]
        document = {"version": 1, "items": [], "freezes": [], "pitch": {"keys": [{"frame": 3, "pairs": marks}], "camera": result}}
        clean = annotations.clean_document(document, duration=CLIP["duration"], frames=FRAMES)
        self.assertEqual(clean["pitch"]["camera"], result)

    def test_a_still_picture_is_followed_as_still(self):
        still = Path(self.folder.name) / "still.mp4"
        frame = cv2.warpPerspective(world(), np.linalg.inv(view(0)), (W, H))
        process = subprocess.Popen([_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt",
                                    "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-pix_fmt", "yuv420p", "-c:v",
                                    "libx264", "-preset", "veryfast", "-crf", "16", str(still)], stdin=subprocess.PIPE)
        for _ in range(10):
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        process.wait()
        result = camera.follow_camera(_find_ffmpeg(), still, {**CLIP, "frames": 10}, 0, 9)
        for row in result["rows"]:
            self.assertLess(pixels_off(row, np.eye(3)), 0.3)

    def test_cancel_stops_it(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(tracker.Cancelled):
            camera.follow_camera(_find_ffmpeg(), self.clip, CLIP, 0, FRAMES - 1, cancel)


class CameraApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.data)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        project = self.server.match_store.create("Camera test")
        (self.data / "previews").mkdir(parents=True, exist_ok=True)
        self.server.media_files["preview"] = camera_clip(self.data / "previews" / "pan.mp4")
        clip = self.call("/api/editor/clips", {"project_id": project["id"], "media": "preview", "name": "Pan"})[1]["clip"]
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

    def test_the_camera_job_reports_progress_and_its_path(self):
        status, started = self.call(self.path + "/camera", {"from_frame": 0, "to_frame": FRAMES - 1})
        self.assertEqual(status, 202, started)
        job = started["job"]
        for _ in range(400):
            job = self.call(f"/api/editor-jobs/{job['id']}")[1]["job"]
            if job["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(len(job["result"]["rows"]), FRAMES)

    def test_camera_requests_are_checked(self):
        for body in ({"from_frame": 0, "to_frame": FRAMES}, {"from_frame": 10, "to_frame": 5},
                     {"from_frame": "0", "to_frame": 9}, {"from_frame": True, "to_frame": 9}, {"to_frame": 9}):
            with self.subTest(body=body):
                self.assertEqual(self.call(self.path + "/camera", body)[0], 400)
        self.assertEqual(self.call(self.path.rsplit("/", 1)[0] + "/" + "0" * 32 + "/camera",
                                   {"from_frame": 0, "to_frame": 9})[0], 404)
