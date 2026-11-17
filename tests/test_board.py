"""Board from this frame (docs/TELESTRATION_PLAN.md, M7): boards and tokens in the
document, the player finder's download, team colours and the server routes.

No real model or footage is needed: the download is fed from memory and the
team split runs on drawn shirts.
"""
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

from app.telestration import annotations, players
from packaging.clipmaker_api_server import create_server
from tests.test_tracking import player_clip

BOARD = {"kind": "board", "view": "full", "theme": "grass"}


def document(items, freezes=None):
    return {"version": 1, "freezes": freezes if freezes is not None else [{"atFrame": 10, "seconds": 4, "background": BOARD}],
            "tracks": [], "items": items}


def token(**extra):
    item = {"id": "k1", "kind": "token", "points": [[0.5, 0.5]], "style": {"fill": "#d6262e", "size": 34},
            "show": {"from": 0.4, "to": 4.4}, "team": "home", "label": "10", "on": 10}
    item.update(extra)
    return item


class BoardDocumentTests(unittest.TestCase):
    def clean(self, value):
        return annotations.clean_document(value, duration=2, frames=50)

    def test_board_with_tokens_round_trips(self):
        value = document([token(name="Diallo"), token(id="k2", team="away", label="", on=10)])
        cleaned = self.clean(value)
        self.assertEqual(cleaned["freezes"][0]["background"], BOARD)
        self.assertEqual([(i["team"], i["label"]) for i in cleaned["items"]], [("home", "10"), ("away", "")])
        self.assertEqual(cleaned["items"][0]["name"], "Diallo")

    def test_plain_freeze_still_works(self):
        cleaned = self.clean(document([], [{"atFrame": 3, "seconds": 1}]))
        self.assertNotIn("background", cleaned["freezes"][0])

    def test_bad_boards_and_tokens_are_refused(self):
        cases = {
            "unknown view": document([], [{"atFrame": 10, "seconds": 4, "background": {**BOARD, "view": "half"}}]),
            "unknown theme": document([], [{"atFrame": 10, "seconds": 4, "background": {**BOARD, "theme": "night"}}]),
            "unknown kind": document([], [{"atFrame": 10, "seconds": 4, "background": {**BOARD, "kind": "picture"}}]),
            "path in board": document([], [{"atFrame": 10, "seconds": 4, "background": {**BOARD, "file": "C:/x.png"}}]),
            "unknown team": document([token(team="ref")]),
            "long label": document([token(label="1000")]),
            "long name": document([token(name="x" * 31)]),
            "two points": document([token(points=[[0.1, 0.1], [0.2, 0.2]])]),
            "on no board": document([token(on=11)]),
            "on a plain freeze": document([token()], [{"atFrame": 10, "seconds": 4}]),
            "team on an arrow": document([{"id": "a1", "kind": "arrow", "points": [[0, 0], [1, 1]], "team": "home",
                                           "show": {"from": 0, "to": 1}}]),
            "followed point on a board": document([token(points=[{"track": "t1", "dx": 0, "dy": 0}])]),
        }
        for name, value in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.clean(value)


class FakeDownload(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name) / "models"
        self.payload = bytes(range(256)) * 40

    def tearDown(self):
        self.temporary.cleanup()

    def install(self, payload, cancel=None, **constants):
        values = {"MODEL_BYTES": len(self.payload), "MODEL_SHA256": hashlib.sha256(self.payload).hexdigest(), **constants}
        seen = []
        with mock.patch.multiple(players, **values):
            result = players.install(self.folder, cancel or threading.Event(), lambda d, t: seen.append(d),
                                     opener=lambda url: FakeDownload(payload))
        return result, seen

    def test_good_download_is_kept(self):
        result, seen = self.install(self.payload)
        self.assertTrue(result["installed"])
        self.assertEqual(players.model_path(self.folder).read_bytes(), self.payload)
        self.assertEqual(seen[-1], len(self.payload))
        self.assertEqual(list(self.folder.iterdir()), [players.model_path(self.folder)])

    def test_bad_downloads_leave_nothing(self):
        cases = {
            "checksum": (self.payload[:-1] + b"x", ValueError),
            "too large": (self.payload + b"extra", ValueError),
            "too small": (self.payload[:-10], ValueError),
        }
        for name, (payload, error) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                self.install(payload)
            self.assertEqual(list(self.folder.iterdir()), [])

    def test_cancel_leaves_nothing(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(players.Cancelled):
            self.install(self.payload, cancel)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_a_wrong_file_in_place_is_refused_on_load(self):
        self.folder.mkdir()
        players.model_path(self.folder).write_bytes(b"not a model")
        with self.assertRaises(players.ModelMissing):
            players.Detector(players.model_path(self.folder))


class TeamTests(unittest.TestCase):
    def test_tiles_cover_the_frame_with_overlap(self):
        tiles = list(players.tiles(1024, 576))
        self.assertEqual(len(tiles), 6)
        self.assertEqual((min(t[0] for t in tiles), min(t[1] for t in tiles)), (0, 0))
        self.assertEqual((max(t[2] for t in tiles), max(t[3] for t in tiles)), (1024, 576))
        self.assertLess(tiles[1][0], tiles[0][2])  # neighbours overlap

    def test_shirts_split_into_two_teams_and_an_odd_one_out(self):
        frame = np.zeros((200, 400, 3), np.uint8)
        frame[:] = (40, 120, 40)  # grass
        boxes, shirts = [], []
        bgr = {"red": (40, 40, 210), "blue": (200, 70, 30), "pale blue": (235, 200, 170), "yellow": (20, 220, 235)}
        for index, colour in enumerate(["red"] * 5 + ["blue"] * 3 + ["pale blue"] + ["yellow"]):
            x = 10 + index * 38
            frame[40:120, x:x + 24] = bgr[colour]
            boxes.append([x, 40, 24, 80])
            shirts.append(colour)
        teams, colours = players.split_teams(frame, boxes)
        self.assertEqual(teams[:5], [0] * 5)  # the bigger team first
        self.assertEqual(teams[5:9], [1] * 4)  # washed-out blue stays blue
        self.assertEqual(teams[9], 2)
        self.assertGreater(int(colours[0][1:3], 16), int(colours[0][5:7], 16))  # reddish
        self.assertGreater(int(colours[1][5:7], 16), int(colours[1][1:3], 16))  # bluish

    def test_token_colours_are_vivid(self):
        dull_red = players.token_colour(np.array([50, 50, 120]))
        r, g, b = (int(dull_red[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreaterEqual(r, 200)
        self.assertLess(max(g, b), r // 2)
        self.assertEqual(players.token_colour(np.array([128, 128, 128])), "#808080")  # grey stays grey


class BoardApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.data)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        project = self.server.match_store.create("Board test")
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

    def test_model_status_names_no_local_path(self):
        status, body = self.call("/api/editor-models")
        self.assertEqual(status, 200)
        self.assertFalse(body["players"]["installed"])
        self.assertEqual(body["players"]["bytes"], players.MODEL_BYTES)
        self.assertNotIn(str(self.data), json.dumps(body))

    def test_finding_players_without_the_model_asks_for_it(self):
        status, body = self.call(self.path + "/players", {"frame": 3})
        self.assertEqual(status, 409, body)
        self.assertFalse(body["model"]["installed"])

    def test_player_requests_are_checked(self):
        for frame in (-1, 50, "3", True, None, 2.5):
            with self.subTest(frame=frame):
                self.assertEqual(self.call(self.path + "/players", {"frame": frame})[0], 400)
        self.assertEqual(self.call(self.path.rsplit("/", 1)[0] + "/" + "0" * 32 + "/players", {"frame": 0})[0], 404)

    def test_download_runs_as_one_job(self):
        started = threading.Event()
        release = threading.Event()

        def slow_install(folder, cancel, progress):
            started.set()
            release.wait(5)
            return players.status(folder)

        import telestration.players as served  # the server imports the package from app/
        with mock.patch.object(served, "install", slow_install):
            first = self.call("/api/editor-models/players", {})
            started.wait(5)
            second = self.call("/api/editor-models/players", {})
            release.set()
        self.assertEqual((first[0], second[0]), (202, 202))
        self.assertEqual(first[1]["job"]["id"], second[1]["job"]["id"])
        job = first[1]["job"]
        for _ in range(100):
            job = self.call(f"/api/editor-jobs/{job['id']}")[1]["job"]
            if job["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "done", job)


if __name__ == "__main__":
    unittest.main()
