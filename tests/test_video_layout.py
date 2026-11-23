"""Slow-loading match videos (2026-11-23): a Chelsea v Hull MP4 saved from a Dailymotion
stream held its picture and sound in ~15,000 top-level mdat pieces, and took the player
18-20 s and ~2,000 requests to open. Intake now offers to rearrange such files losslessly
(app/video_layout.py) and swaps the result in under the same name."""
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import video_layout
from app.video_encoder import find_ffmpeg
from packaging.clipmaker_api_server import create_server

CONTAINERS = {"moov", "trak", "mdia", "minf", "stbl"}


def make_video(path: Path, seconds: int = 3) -> None:
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=25:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(path)], check=True, timeout=60)


def offset_tables(data: bytes, start: int, end: int, found: list):
    """(position, width) of every stco/co64 table inside the moov at data[start:end]."""
    position = start
    while position + 8 <= end:
        size, kind = struct.unpack(">I4s", data[position:position + 8])
        kind = kind.decode("latin-1")
        if kind in CONTAINERS:
            offset_tables(data, position + 8, position + size, found)
        elif kind in ("stco", "co64"):
            found.append((position, 4 if kind == "stco" else 8))
        position += size
    return found


def split_into_pieces(source: Path, target: Path) -> int:
    """Rewrite a faststart MP4 so every chunk sits in its own top-level mdat, like a web-stream download."""
    data = bytearray(source.read_bytes())
    boxes = []
    position = 0
    while position < len(data):
        size, kind = struct.unpack(">I4s", data[position:position + 8])
        boxes.append((kind.decode("latin-1"), position, size))
        position += size
    moov = next(box for box in boxes if box[0] == "moov")
    mdat = next(box for box in boxes if box[0] == "mdat")
    assert moov[1] < mdat[1], "the fixture needs the index first"
    tables = offset_tables(data, moov[1] + 8, moov[1] + moov[2], [])
    chunks = []
    for table, width in tables:
        count = struct.unpack(">I", data[table + 12:table + 16])[0]
        for index in range(count):
            at = table + 16 + index * width
            chunks.append(struct.unpack(">I" if width == 4 else ">Q", data[at:at + width])[0])
    chunks = sorted(set(chunks))
    shift = {chunk: 8 * index for index, chunk in enumerate(chunks)}  # one more mdat header before each later chunk
    for table, width in tables:
        count = struct.unpack(">I", data[table + 12:table + 16])[0]
        for index in range(count):
            at = table + 16 + index * width
            old = struct.unpack(">I" if width == 4 else ">Q", data[at:at + width])[0]
            data[at:at + width] = struct.pack(">I" if width == 4 else ">Q", old + shift[old])
    payload_start, payload_end = mdat[1] + 8, mdat[1] + mdat[2]
    edges = [payload_start, *chunks[1:], payload_end]
    out = bytearray(data[:mdat[1]])
    for first, last in zip(edges, edges[1:]):
        out += struct.pack(">I4s", last - first + 8, b"mdat") + data[first:last]
    out += data[payload_end:]
    target.write_bytes(bytes(out))
    return len(chunks)


class VideoLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.normal = cls.root / "normal.mp4"
        make_video(cls.normal)
        cls.pieces_source = cls.root / "pieces-source.mp4"
        cls.pieces_count = split_into_pieces(cls.normal, cls.pieces_source)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def pieces_copy(self, name="match.mp4") -> Path:
        path = self.root / name
        path.write_bytes(self.pieces_source.read_bytes())
        return path

    def test_fixture_is_a_valid_video_in_many_pieces(self):
        self.assertGreater(self.pieces_count, 3)
        layout = video_layout.layout(self.pieces_source)
        # The scan stops counting once the file is known to be in many pieces.
        self.assertEqual(layout["pieces"], min(self.pieces_count, video_layout.MANY_PIECES + 1))
        self.assertTrue(layout["index_first"])
        decoded = subprocess.run([find_ffmpeg(), "-v", "error", "-i", str(self.pieces_source), "-f", "null", "-"],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(decoded.returncode, 0, decoded.stderr)
        self.assertEqual(decoded.stderr.strip(), "")

    def test_only_files_in_many_pieces_need_preparing(self):
        self.assertFalse(video_layout.needs_preparing(self.normal))
        self.assertTrue(video_layout.needs_preparing(self.pieces_source))
        with patch.object(video_layout, "MANY_PIECES", 1000):
            self.assertFalse(video_layout.needs_preparing(self.pieces_source))
        other = self.root / "clip.mkv"
        other.write_bytes(b"\x1a\x45\xdf\xa3")
        self.assertFalse(video_layout.needs_preparing(other))
        self.assertFalse(video_layout.needs_preparing(self.root / "missing.mp4"))

    def test_summary_reads_length_and_tracks_from_the_index(self):
        for path in (self.normal, self.pieces_source):
            summary = video_layout.summary(path)
            self.assertEqual(summary["tracks"], 2)
            self.assertAlmostEqual(summary["duration"], 3.0, delta=0.2)

    def test_prepare_swaps_in_one_piece_under_the_same_name(self):
        path = self.pieces_copy()
        seen = []
        with patch.object(video_layout, "MANY_PIECES", 3):
            result = video_layout.prepare(path, find_ffmpeg(), seen.append)
            self.assertFalse(video_layout.needs_preparing(path))
        layout = video_layout.layout(path)
        self.assertEqual(layout["pieces"], 1)
        self.assertTrue(layout["index_first"])
        self.assertEqual(result["tracks"], 2)
        self.assertEqual(seen[-1], 1.0)
        self.assertFalse(video_layout.part_path(path).exists())
        self.assertEqual([item.name for item in self.root.glob(".*")], [])

    def test_stopped_preparation_leaves_the_original_untouched(self):
        path = self.pieces_copy("stopped.mp4")
        before = path.read_bytes()
        stop = threading.Event()
        stop.set()
        with patch.object(video_layout, "MANY_PIECES", 3), self.assertRaises(video_layout.PrepareCancelled):
            video_layout.prepare(path, find_ffmpeg(), cancel=stop)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(video_layout.part_path(path).exists())

    def test_a_copy_that_does_not_match_keeps_the_original(self):
        path = self.pieces_copy("mismatch.mp4")
        before = path.read_bytes()
        real = video_layout.summary
        calls = []

        def summary(target):
            calls.append(target)
            found = real(target)
            return found if len(calls) == 1 else {**found, "tracks": found["tracks"] - 1}

        with patch.object(video_layout, "MANY_PIECES", 3), patch.object(video_layout, "summary", summary), \
                self.assertRaisesRegex(ValueError, "did not match the original"):
            video_layout.prepare(path, find_ffmpeg())
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(video_layout.part_path(path).exists())

    def test_not_enough_space_is_reported_before_writing(self):
        path = self.pieces_copy("space.mp4")
        with patch.object(video_layout, "_free_space", return_value=10), \
                self.assertRaisesRegex(ValueError, "Not enough free space"):
            video_layout.prepare(path, find_ffmpeg())
        self.assertFalse(video_layout.part_path(path).exists())


class PrepareApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.root / "data")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        normal = self.root / "normal.mp4"
        make_video(normal)
        self.video = self.root / "Chelsea vs Hull City.mp4"
        split_into_pieces(normal, self.video)
        # The engine imports app/ modules by their own names.
        import video_layout as engine_layout
        self.threshold = patch.object(engine_layout, "MANY_PIECES", 3)
        self.threshold.start()

    def tearDown(self):
        self.threshold.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def error(self, path, body=None):
        with self.assertRaises(HTTPError) as raised:
            self.request(path, body)
        message = json.loads(raised.exception.read())["error"]
        raised.exception.close()
        return raised.exception.code, message

    def test_reopen_flags_a_slow_video_and_prepare_fixes_it_in_place(self):
        project = self.request("/api/projects", {})["project"]
        self.request(f"/api/projects/{project['id']}", {"video_path": str(self.video)})
        opened = self.request("/api/files/reopen", {"match_id": project["id"]})["file"]
        self.assertTrue(opened["needs_preparing"])

        job = self.request("/api/files/prepare", {"match_id": project["id"]})["job"]
        self.assertEqual(job["name"], self.video.name)
        self.assertNotIn(str(self.video.parent), json.dumps({k: v for k, v in job.items() if k != "path"}))
        deadline = time.monotonic() + 60
        while job["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
            job = self.request(f"/api/files/prepare/{job['id']}")["job"]
        self.assertEqual(job["status"], "done", job["error"])

        reopened = self.request("/api/files/reopen", {"match_id": project["id"]})["file"]
        self.assertFalse(reopened["needs_preparing"])
        self.assertEqual(reopened["path"], str(self.video.resolve()))
        self.assertEqual(self.request(f"/api/projects/{project['id']}")["project"]["video_path"], str(self.video))
        self.assertEqual(self.error("/api/files/prepare", {"match_id": project["id"]}),
                         (400, "This video already loads quickly."))

    def test_prepare_only_takes_a_saved_match_and_never_a_path(self):
        self.assertEqual(self.error("/api/files/prepare", {"match_id": "nope", "path": str(self.video)})[0], 400)
        project = self.request("/api/projects", {})["project"]
        code, message = self.error("/api/files/prepare", {"match_id": project["id"], "path": str(self.video)})
        self.assertEqual((code, message), (400, "No video is chosen for this match yet. Choose it on Intake."))
        self.assertEqual(self.error("/api/files/prepare/unknown")[0], 404)
        self.assertEqual(self.error("/api/files/prepare/unknown/cancel", {})[0], 404)

    def test_the_player_is_refused_while_the_file_is_being_swapped(self):
        project = self.request("/api/projects", {})["project"]
        self.request(f"/api/projects/{project['id']}", {"video_path": str(self.video)})
        url = self.request("/api/files/reopen", {"match_id": project["id"]})["file"]["url"]
        with patch.object(self.server.preparations, "busy", return_value=True):
            self.assertEqual(self.error(url)[0], 409)
        with urlopen(Request(self.url + url, headers={"Range": "bytes=0-15"}), timeout=5) as response:
            self.assertEqual(response.status, 206)


if __name__ == "__main__":
    unittest.main()
