"""Moving boards (docs/TELESTRATION_PLAN.md, M8): token moves in the document, and
export patches (the changed tiles laid over the overlay before)."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

from app.telestration import annotations, export
from app.telestration.tracker import read_frames
from packaging.clipmaker_api_server import create_server, _find_ffmpeg
from tests.test_board import document, token
from tests.test_export import FPS, H, RECORD, SQUARE, W, grey_clip, square


class TokenMoveTests(unittest.TestCase):
    def clean(self, value):
        return annotations.clean_document(value, duration=2, frames=50)

    def test_moves_round_trip(self):
        cleaned = self.clean(document([token(moves=[[1, 0.5, 0.5], [3.25, 0.61234567, 0.4]])]))
        self.assertEqual(cleaned["items"][0]["moves"], [[1.0, 0.5, 0.5], [3.25, 0.61235, 0.4]])

    def test_bad_moves_are_refused(self):
        arrow = {"id": "a1", "kind": "arrow", "points": [[0, 0], [1, 1]], "show": {"from": 0, "to": 1},
                 "on": 10, "moves": [[1, 0.5, 0.5]]}
        plain = token(moves=[[1, 0.5, 0.5]])
        del plain["on"]
        cases = {
            "not a token": document([arrow]),
            "not on a board": document([plain]),
            "out of order": document([token(moves=[[2, 0.5, 0.5], [1, 0.5, 0.5]])]),
            "at the start": document([token(moves=[[0, 0.5, 0.5]])]),
            "too late": document([token(moves=[[61, 0.5, 0.5]])]),
            "off the picture": document([token(moves=[[1, 2.0, 0.5]])]),
            "not a key": document([token(moves=[[1, 0.5]])]),
            "text": document([token(moves=[["1", 0.5, 0.5]])]),
            "too many": document([token(moves=[[i + 1, 0.5, 0.5] for i in range(101)])]),
        }
        for name, value in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.clean(value)


def patch_batch(frame, tiles):
    """A patch as the editor sends it: (frame, [(box, pixels)])."""
    header = json.dumps([{"frame": frame, "tiles": [box for box, _ in tiles]}]).encode()
    return len(header).to_bytes(4, "big") + header + b"".join(pixels for _, pixels in tiles)


def tile(colour, w=20, h=20):
    return np.full((h, w, 4), (*colour, 255), np.uint8).tobytes()


class ExportPatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clip = grey_clip(self.root / "clip.mp4", sound=False)
        self.sessions = export.ExportSessions(self.root / "sessions")

    def tearDown(self):
        self.temporary.cleanup()

    def test_patches_change_only_their_tiles(self):
        session = self.sessions.create("p", "c", RECORD, self.clip, {"freezes": []})
        sid = session["id"]
        self.sessions.add_overlay(sid, 0, square((255, 0, 0)), SQUARE)  # red square at 40,30 40x40
        # Frame 5: a blue tile inside the square, a green one outside it.
        self.sessions.add_batch(sid, patch_batch(5, [([40, 30, 20, 20], tile((0, 0, 255))), ([100, 80, 20, 20], tile((0, 255, 0)))]))
        self.sessions.add_batch(sid, patch_batch(8, [([100, 80, 20, 20], tile((255, 255, 0)))]))
        schedule = export.overlay_schedule(self.sessions.get(sid)["folder"])
        target = self.root / "out.mp4"
        export.render(_find_ffmpeg(), self.clip, RECORD, [], 20, schedule, str(target), "libx264")
        frames = list(read_frames(_find_ffmpeg(), target, FPS, 0, 25, (W, H)))
        bgr = lambda n, x, y: [int(v) for v in frames[n][y, x]]
        near = lambda value, expected: all(abs(a - b) < 40 for a, b in zip(value, expected))
        self.assertTrue(near(bgr(3, 70, 60), (0, 0, 255)))  # red square
        self.assertTrue(near(bgr(3, 110, 90), (128, 128, 128)))  # nothing outside yet
        self.assertTrue(near(bgr(6, 45, 35), (255, 0, 0)))  # blue tile over the square
        self.assertTrue(near(bgr(6, 70, 60), (0, 0, 255)))  # the rest of the square stays red
        self.assertTrue(near(bgr(6, 110, 90), (0, 255, 0)))  # green tile outside it
        self.assertTrue(near(bgr(9, 110, 90), (0, 255, 255)))  # replaced by yellow
        self.assertTrue(near(bgr(9, 45, 35), (255, 0, 0)))  # earlier patches stay

    def test_bad_patches_are_refused(self):
        session = self.sessions.create("p", "c", RECORD, self.clip, {"freezes": []})
        sid = session["id"]
        with self.assertRaises(ValueError):  # nothing to patch yet
            self.sessions.add_batch(sid, patch_batch(0, [([0, 0, 20, 20], tile((0, 0, 0)))]))
        self.sessions.add_overlay(sid, 0, square(), SQUARE)
        cases = {
            "off the frame": patch_batch(1, [([150, 0, 20, 20], tile((0, 0, 0)))]),
            "short": patch_batch(1, [([0, 0, 20, 20], tile((0, 0, 0))[:-4])]),
            "no tiles": len(b'[{"frame": 1, "tiles": []}]').to_bytes(4, "big") + b'[{"frame": 1, "tiles": []}]',
            "tile and box": (lambda h: len(h).to_bytes(4, "big") + h + tile((0, 0, 0)))(
                json.dumps([{"frame": 1, "box": [0, 0, 20, 20], "tiles": [[0, 0, 20, 20]]}]).encode()),
        }
        for name, body in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.sessions.add_batch(sid, body)
        self.sessions.add_batch(sid, patch_batch(1, [([0, 0, 20, 20], tile((0, 0, 0)))]))
        names = sorted(path.name for path in self.sessions.get(sid)["folder"].iterdir())
        self.assertEqual(names, ["overlay-000000-40-30-40-40.rgba", "overlay-000001.patch"])


if __name__ == "__main__":
    unittest.main()
