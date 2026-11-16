"""Analyst editor export (docs/TELESTRATION_PLAN.md, M4).

A grey two-second clip with a steady tone is generated, so the checks are exact:
drawings appear where and when their overlays say, a freeze holds its frame for
its length with silence under it, and the sound after it stays in step.
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

from app.telestration import export
from app.telestration.tracker import read_frames
from packaging.clipmaker_api_server import create_server, _find_ffmpeg

W, H, FPS, SECONDS = 160, 120, 10, 2
RECORD = {"fps": FPS, "width": W, "height": H, "duration": SECONDS, "frames": FPS * SECONDS}
FREEZES = [{"atFrame": 5, "seconds": 1.0}]  # holds frame 5 (0.5 s) for a second


def grey_clip(path: Path, sound=True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", f"color=c=0x808080:s={W}x{H}:r={FPS}:d={SECONDS}"]
    if sound:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={SECONDS}"]
    command += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10"]
    command += ["-c:a", "aac", "-shortest"] if sound else []
    subprocess.run(command + [str(path)], check=True)
    return path


SQUARE = [40, 30, 40, 40]  # the box square() fills


def square(colour=(255, 0, 0)) -> bytes:
    """An opaque RGBA square, 40 x 40, as the editor sends the box of drawn pixels."""
    return np.full((40, 40, 4), (*colour, 255), np.uint8).tobytes()


def batch(*entries) -> bytes:
    """Overlays as the editor sends them: (frame, box or None, pixels) -> one request body."""
    header = json.dumps([{"frame": frame, "box": box} for frame, box, _ in entries]).encode()
    return len(header).to_bytes(4, "big") + header + b"".join(pixels for _, box, pixels in entries if box)


def output_audio(path: Path) -> np.ndarray:
    raw = subprocess.run([_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-ar", "48000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32)


def loudness(samples: np.ndarray, start: float, end: float) -> float:
    part = samples[int(start * 48000):int(end * 48000)]
    return float(np.sqrt(np.mean(part ** 2))) if part.size else 0.0


class ExportPlanTests(unittest.TestCase):
    def test_output_length_counts_freezes(self):
        self.assertEqual(export.output_frames(RECORD, []), 20)
        self.assertEqual(export.output_frames(RECORD, FREEZES), 30)
        self.assertEqual(export.output_frames(RECORD, [{"atFrame": 0, "seconds": 0.25}]), 22)  # fractional freeze

    def test_freeze_holds_its_frame_then_playback_continues(self):
        shown = export.source_frames(RECORD, FREEZES, 30)
        self.assertEqual(shown[:5], [0, 1, 2, 3, 4])
        self.assertEqual(shown[5:15], [5] * 10)  # the freeze
        self.assertEqual(shown[15:20], [5, 6, 7, 8, 9])  # frame 5 then plays normally
        self.assertEqual(shown, sorted(shown))

    def test_silence_goes_where_the_freezes_are(self):
        plan = export.silence_plan(RECORD, [{"atFrame": 10, "seconds": 0.5}, {"atFrame": 5, "seconds": 1.0}])
        self.assertEqual(plan, [(24000, 48000), (48000, 24000)])


class ExportRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.clip = grey_clip(cls.root / "clip.mp4")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def render(self, schedule, freezes=FREEZES, clip=None):
        target = self.root / f"out-{time.monotonic_ns()}.mp4"
        count = export.output_frames(RECORD, freezes)
        progress = []
        export.render(_find_ffmpeg(), clip or self.clip, RECORD, freezes, count, schedule, str(target), "libx264",
                      progress=lambda done, total: progress.append((done, total)))
        return target, count, progress

    def test_drawings_freezes_and_sound_are_burned_in(self):
        overlay = self.root / "overlay-000003-40-30-40-40.rgba"
        overlay.write_bytes(square())
        target, count, progress = self.render({3: overlay, 12: None})
        frames = list(read_frames(_find_ffmpeg(), target, FPS, 0, count + 5, (W, H)))
        self.assertEqual(len(frames), count)  # 2 s clip + 1 s freeze
        self.assertEqual(progress[-1], (count, count))
        red = lambda frame: frame[50, 60]
        self.assertLess(abs(int(red(frames[2])[2]) - 128), 12)  # before the overlay: grey
        for n in (3, 8, 11):
            self.assertGreater(int(red(frames[n])[2]), 200, n)  # red square (BGR)
            self.assertLess(int(red(frames[n])[0]), 60, n)
        self.assertLess(abs(int(red(frames[12])[2]) - 128), 12)  # cleared
        self.assertLess(abs(int(frames[20][5, 5][1]) - 128), 12)  # outside the square: untouched
        samples = output_audio(target)
        self.assertAlmostEqual(len(samples) / 48000, 3.0, delta=0.08)
        self.assertGreater(loudness(samples, 0.05, 0.45), 1000)  # tone before the freeze
        self.assertLess(loudness(samples, 0.6, 1.4), 50)  # silence under the freeze
        self.assertGreater(loudness(samples, 1.6, 2.9), 1000)  # tone after it

    def test_clip_without_sound_exports(self):
        silent = grey_clip(self.root / "silent.mp4", sound=False)
        target, count, _ = self.render({}, freezes=[], clip=silent)
        self.assertEqual(len(list(read_frames(_find_ffmpeg(), target, FPS, 0, count + 5, (W, H)))), count)

    def test_cancel_part_way_leaves_no_file_or_overlays(self):
        from packaging.clipmaker_api_server import save_to_user_folder
        cancel = threading.Event()
        folder = self.root / "session"
        folder.mkdir()
        session = {"folder": folder, "video": self.clip, "record": RECORD, "freezes": FREEZES, "frames": 30}
        out = self.root / "cancelled-out"
        with self.assertRaises(export.Cancelled):
            export.run_export(_find_ffmpeg(), session, out, "Grey", save_to_user_folder, lambda path: "id", cancel,
                              lambda done, total: done > 5 and cancel.set(), "software")
        self.assertEqual(list(out.iterdir()), [])  # no half-written clip
        self.assertFalse(folder.exists())

    def test_cancel_stops_the_render(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(export.Cancelled):
            export.render(_find_ffmpeg(), self.clip, RECORD, [], 20, {}, str(self.root / "cancelled.mp4"), "libx264", cancel)


class ExportApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.data)
        self.server.default_export_dir = self.data / "Videos"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        project = self.server.match_store.create("Export test")
        self.server.media_files["preview"] = grey_clip(self.data / "previews" / "grey.mp4")
        clip = self.call("/api/editor/clips", {"project_id": project["id"], "media": "preview", "name": "Grey"})[1]["clip"]
        self.path = f"/api/editor/{project['id']}/{clip['id']}"
        document = {"version": 1, "freezes": FREEZES, "items": [
            {"id": "a1", "kind": "arrow", "points": [[0.1, 0.1], [0.5, 0.5]], "show": {"from": 0, "to": 3}}]}
        self.assertEqual(self.call(self.path, {"annotations": document})[0], 200)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def call(self, path, payload=None, raw=None):
        data = raw if raw is not None else None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base + path, data=data, method="POST" if data is not None else "GET",
                          headers={"Content-Type": "application/octet-stream" if raw is not None else "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def wait(self, job):
        for _ in range(400):
            job = self.call(f"/api/editor-jobs/{job['id']}")[1]["job"]
            if job["status"] != "running":
                return job
            time.sleep(0.05)
        self.fail("export did not finish")

    def test_export_round_trip_saves_to_the_users_folder(self):
        status, body = self.call(self.path + "/export", {})
        self.assertEqual(status, 201, body)
        session = body["export"]
        self.assertEqual((session["frames"], session["width"], session["height"]), (30, W, H))
        base = f"/api/editor-exports/{session['id']}"
        # Drawings from frame 0; gone from frame 25.
        self.assertEqual(self.call(f"{base}/overlays", raw=batch((0, SQUARE, square()), (25, None, b""))), (200, {"received": 2}))
        status, body = self.call(f"{base}/render", {"name": "Grey annotated"})
        self.assertEqual(status, 202, body)
        job = self.wait(body["job"])
        self.assertEqual(job["status"], "done", job)
        saved = job["result"]["saved"]
        self.assertEqual(saved["name"], "Grey annotated.mp4")
        self.assertNotIn("path", job["result"])
        output = self.data / "Videos" / saved["name"]
        frames = list(read_frames(_find_ffmpeg(), output, FPS, 0, 40, (W, H)))
        self.assertEqual(len(frames), 30)
        self.assertGreater(int(frames[10][50, 60][2]), 200)
        self.assertLess(abs(int(frames[27][50, 60][2]) - 128), 12)
        self.assertFalse(any((self.data / "editor-exports").iterdir()))  # overlays removed
        self.assertEqual(self.call(f"{base}/render", {})[0], 404)  # a session renders once

    def test_overlays_are_checked(self):
        session = self.call(self.path + "/export", {})[1]["export"]
        base = f"/api/editor-exports/{session['id']}"
        send = lambda body: self.call(f"{base}/overlays", raw=body)[0]
        self.assertEqual(send(batch((30, SQUARE, square()))), 400)  # past the end
        self.assertEqual(send(batch((-1, SQUARE, square()))), 400)
        self.assertEqual(send(batch(("1", SQUARE, square()))), 400)
        self.assertEqual(send(batch((1, [130, 30, 40, 40], square()))), 400)  # box past the frame's edge
        self.assertEqual(send(batch((1, [40, 30, 40, 39], square()))[:-4]), 400)  # pixels short of the box
        self.assertEqual(send(batch((1, SQUARE, square())) + b"xxxx"), 400)  # bytes left over
        self.assertEqual(send((5).to_bytes(4, "big") + b"[]"), 400)  # header cut short
        self.assertEqual(send(batch()), 400)  # nothing in it
        self.assertEqual(send(batch((4, SQUARE, square()))), 200)
        self.assertEqual(send(batch((4, SQUARE, square()))), 400)  # out of order
        self.assertEqual(self.call("/api/editor-exports/0123456789abcdef/overlays", raw=batch((0, SQUARE, square())))[0], 404)
        self.assertEqual(self.call("/api/editor-exports/..%2F..%2F/overlays", raw=batch((0, SQUARE, square())))[0], 404)
        self.assertEqual(self.call(self.path.rsplit("/", 1)[0] + "/" + "0" * 32 + "/export", {})[0], 404)

    def test_cancelled_export_leaves_nothing_behind(self):
        session = self.call(self.path + "/export", {})[1]["export"]
        base = f"/api/editor-exports/{session['id']}"
        self.call(f"{base}/overlays", raw=batch((0, SQUARE, square())))
        self.assertEqual(self.call(f"{base}/cancel", {})[1], {"discarded": True})
        self.assertFalse((self.data / "editor-exports" / session["id"]).exists())
        self.assertEqual(self.call(f"{base}/render", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
