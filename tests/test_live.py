"""Live recording, L1 (docs/CODING_AND_PITCH_PLAN.md): sources are checked against what
FFmpeg can read, segments are recorded per connection with the gaps between them noted,
the page reads only segment files, and stop joins everything into the project's video.
The recording tests push a generated stream with the bundled FFmpeg, as OBS would."""
from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from packaging.clipmaker_api_server import create_server  # first: it puts app/ on the path
from live import recorder  # noqa: E402
import video_encoder  # noqa: E402

ALL = {"rtmp", "rtmps", "srt", "tcp", "tls", "http", "https"}


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def ffmpeg():
    try:
        path = video_encoder.find_ffmpeg()
    except ValueError:
        raise unittest.SkipTest("FFmpeg is not available") from None
    if "rtmp" not in recorder.protocols(path):
        raise unittest.SkipTest("this FFmpeg cannot send or receive RTMP")
    return path


def push(port, seconds):
    """A test pattern with sound, sent over RTMP the way OBS sends it. Like OBS, it tries
    again while the recorder's FFmpeg is still starting to listen (slower on Linux and macOS)."""
    command = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
               "-f", "lavfi", "-i", "sine", "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-f", "flv", f"rtmp://127.0.0.1:{port}/live/any-key"]
    end = time.time() + 20
    while True:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        if "refused" not in result.stderr.lower() or time.time() > end:
            raise AssertionError(f"push failed: {result.stderr[-300:]}")
        time.sleep(0.3)


def wait_for(check, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError("timed out")


class SourceTests(unittest.TestCase):
    def test_stream_addresses(self):
        self.assertEqual(recorder.check_source({"kind": "url", "url": " rtmp://cam.club/live/key "}, ALL),
                         {"kind": "url", "url": "rtmp://cam.club/live/key"})
        for url in ("srt://10.0.0.2:9000", "rtsp://cam/stream", "https://example.org/match.m3u8"):
            self.assertEqual(recorder.check_source({"kind": "url", "url": url}, ALL)["url"], url)

    def test_files_and_odd_addresses_are_refused(self):
        # No arbitrary filesystem access through the browser API (AGENTS.md).
        for url in ("file:///C:/Windows/win.ini", "C:/match.mp4", "concat:a.mp4|b.mp4", "rtmp://", "rtmp://cam/live key",
                    "ftp://cam/stream", "", "rtmp://cam/" + "x" * 2100):
            with self.assertRaises(ValueError, msg=url):
                recorder.check_source({"kind": "url", "url": url}, ALL)
        with self.assertRaises(ValueError):
            recorder.check_source("rtmp://cam/live", ALL)

    def test_a_protocol_ffmpeg_lacks_is_reported(self):
        with self.assertRaisesRegex(ValueError, "cannot read srt"):
            recorder.check_source({"kind": "url", "url": "srt://cam:9000"}, ALL - {"srt"})
        with self.assertRaisesRegex(ValueError, "cannot receive SRT"):
            recorder.check_source({"kind": "listen", "protocol": "srt"}, ALL - {"srt"})

    def test_listening_is_on_this_computer_only(self):
        source = recorder.check_source({"kind": "listen", "protocol": "rtmp"}, ALL)
        self.assertEqual(source, {"kind": "listen", "protocol": "rtmp", "port": 1935})
        self.assertIn("rtmp://127.0.0.1:1935/live/", " ".join(recorder.input_args(source)))
        self.assertEqual(recorder.push_address(source), "rtmp://127.0.0.1:1935/live")
        srt = recorder.check_source({"kind": "listen", "protocol": "srt", "port": "9100"}, ALL)
        self.assertEqual(recorder.input_args(srt), ["-i", "srt://127.0.0.1:9100?mode=listener"])
        for port in (80, 70000, "x"):
            with self.assertRaises(ValueError):
                recorder.check_source({"kind": "listen", "protocol": "rtmp", "port": port}, ALL)
        with self.assertRaises(ValueError):
            recorder.check_source({"kind": "listen", "protocol": "udp"}, ALL)

    def test_the_page_never_sees_a_stream_key(self):
        source = recorder.check_source({"kind": "url", "url": "rtmp://user:secret@cam.club:1936/live/key123"}, ALL)
        self.assertEqual(recorder.describe(source), "rtmp://cam.club:1936")

    def test_h264_is_kept_and_anything_else_is_encoded(self):
        self.assertIn("copy", recorder.output_args(False))
        encoded = recorder.output_args(True)
        self.assertIn("libx264", encoded)
        self.assertIn("fmp4", encoded)


class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def part(self, name, entries):
        part = self.folder / name
        part.mkdir()
        lines = ["#EXTM3U", '#EXT-X-MAP:URI="init.mp4"']
        for file, seconds in entries:
            lines += [f"#EXTINF:{seconds},", file]
            if file.startswith("seg_"):
                (part / file).write_bytes(b"x")
        (part / "live.m3u8").write_text("\n".join(lines), encoding="utf-8")

    def test_segments_run_end_to_end_across_parts(self):
        self.part("part01", [("seg_00000.m4s", 2.0), ("seg_00001.m4s", 1.5)])
        self.part("part02", [("seg_00000.m4s", 2.0)])
        found = recorder.segments(self.folder)
        self.assertEqual([(item["part"], item["start"]) for item in found], [("part01", 0.0), ("part01", 2.0), ("part02", 3.5)])

    def test_only_finished_segment_files_are_listed(self):
        self.part("part01", [("seg_00000.m4s", 2.0), ("../../matches.json", 2.0), ("seg_00009.m4s.tmp", 2.0)])
        (self.folder / "part01" / "seg_00001.m4s").unlink(missing_ok=True)
        self.assertEqual(recorder.read_playlist(self.folder / "part01"), [("seg_00000.m4s", 2.0)])
        (self.folder / "notes").mkdir()
        self.assertEqual([part.name for part in recorder.parts_of(self.folder)], ["part01"])

    def test_a_clip_is_checked_and_stays_inside_one_part(self):
        # L2: clips while recording. Two parts of 2 s + 2 s, then 2 s after a break.
        self.part("part01", [("seg_00000.m4s", 2.0), ("seg_00001.m4s", 2.0)])
        self.part("part02", [("seg_00000.m4s", 2.0)])
        for start, end, message in ((1, 1.1, "too short"), (0, 400, "up to 5 minutes"), (7, 9, "not been recorded"),
                                    (5, 8, "recorded in 2 s"), ("1", 3, "start and an end"), (float("nan"), 3, "start and an end")):
            with self.assertRaisesRegex(ValueError, message):
                recorder.cut("ffmpeg", self.folder, start, end, "out.mp4", run=None)
        commands = []

        def run(command, **options):
            commands.append((command, options))
            return subprocess.CompletedProcess(command, 0, "", "")

        span = recorder.cut("ffmpeg", self.folder, 2.5, 5.5, "out.mp4", run=run)
        self.assertEqual(span, (2.5, 4.0))  # ends where the break starts
        command, options = commands[0]
        self.assertEqual(options["cwd"], self.folder / "part01")
        self.assertEqual(command[command.index("-ss") + 1], "0.500")
        self.assertEqual(command[command.index("-t") + 1], "1.500")
        self.assertEqual(list((self.folder / "part01").glob("clip-*.m3u8")), [])  # its playlist is cleaned up

    def test_codecs_come_from_the_init_segment(self):
        init = self.folder / "init.mp4"
        init.write_bytes(b"....avcC\x01\x64\x00\x1f....mp4a....")
        self.assertEqual(recorder.codecs(init), "avc1.64001f,mp4a.40.2")
        self.assertEqual(recorder.codecs(self.folder / "missing.mp4"), "")


class RecordingTests(unittest.TestCase):
    """Real recordings: a generated stream pushed to the recorder over RTMP on localhost."""

    def setUp(self):
        self.ffmpeg = ffmpeg()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.joined = []
        self.live = recorder.LiveRecordings(self.root / "live", lambda: self.ffmpeg, lambda: self.root / "Recordings",
                                            lambda project, path, gaps: self.joined.append((project, path, gaps)))
        self.port = free_port()

    def tearDown(self):
        self.live.close()
        self.temporary.cleanup()

    def start(self):
        return self.live.start("match1", {"kind": "listen", "protocol": "rtmp", "port": self.port})

    def finish(self):
        self.live.stop("match1", "Home / Away")
        return wait_for(lambda: (lambda status: status if status["state"] != "joining" else None)(self.live.status("match1")), 60)

    def test_a_drop_becomes_a_gap_and_stop_joins_one_video(self):
        self.assertEqual(self.start()["state"], "waiting")
        push(self.port, 4)
        wait_for(lambda: self.live.status("match1")["state"] == "reconnecting")
        push(self.port, 4)
        status = self.live.status("match1", after=1)
        self.assertEqual(status["new_segments"][0]["i"], 1)
        self.assertEqual(set(status["codecs"]), {"part01", "part02"})
        self.assertTrue(all(value.startswith("avc1.") for value in status["codecs"].values()))
        done = self.finish()
        self.assertEqual(done["state"], "done", done)
        project, path, gaps = self.joined[0]
        self.assertEqual(project, "match1")
        self.assertEqual(path.parent, self.root / "Recordings")
        self.assertTrue(path.name.startswith("Home Away live "))
        self.assertAlmostEqual(recorder.media_seconds(self.ffmpeg, path), 8, delta=1)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0]["at"], 4, delta=1)
        self.assertGreater(gaps[0]["length"], 0)
        self.assertFalse((self.root / "live" / "match1").exists())  # the segments went into the video
        self.assertEqual(self.live.status("match1")["state"], "done")

    def test_a_recording_cut_off_by_closing_can_still_be_saved(self):
        self.start()
        push(self.port, 4)
        self.live.close()  # the engine shutting down mid-match
        self.live.recordings.clear()
        status = self.live.status("match1")
        self.assertEqual(status["state"], "interrupted")
        self.assertGreater(status["recorded_seconds"], 2)
        with self.assertRaisesRegex(ValueError, "unfinished recording"):
            self.start()
        self.assertEqual(self.finish()["state"], "done")
        self.assertAlmostEqual(recorder.media_seconds(self.ffmpeg, self.joined[0][1]), 4, delta=1)

    def test_a_clip_can_be_cut_while_it_records(self):
        self.start()
        push(self.port, 6)
        output = self.root / "clip.mp4"
        self.assertEqual(self.live.clip("match1", 1.0, 3.5, str(output)), (1.0, 3.5))
        self.assertAlmostEqual(recorder.media_seconds(self.ffmpeg, output), 2.5, delta=0.15)
        with self.assertRaisesRegex(ValueError, "recorded in"):
            self.live.clip("match1", 2.0, 30.0, str(self.root / "later.mp4"))

    def test_stopping_before_any_stream_records_nothing(self):
        self.start()
        status = self.finish()
        self.assertEqual(status["state"], "failed")
        self.assertIn("Nothing was recorded", status["error"])
        self.assertEqual(self.joined, [])
        self.assertEqual(self.start()["state"], "waiting")  # and a new recording can start

    def test_one_recording_at_a_time(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "already recording"):
            self.start()
        with self.assertRaisesRegex(ValueError, "Another project"):
            self.live.start("match2", {"kind": "listen", "protocol": "rtmp", "port": free_port()})

    def test_an_address_that_does_not_answer_fails_with_a_reason(self):
        self.live.start("match1", {"kind": "url", "url": f"rtmp://127.0.0.1:{self.port}/live/none"})
        status = wait_for(lambda: (lambda status: status if status["state"] == "failed" else None)(self.live.status("match1")), 40)
        self.assertIn("connect", status["error"].lower())


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.root)
        self.server.default_export_dir = str(self.root / "exports")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.project = self.request("/api/projects", {"name": "Live"})["project"]["id"]

    def tearDown(self):
        self.server.live.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def status_of(self, path):
        try:
            self.request(path)
        except HTTPError as error:
            return error.code
        return 200

    def refused(self, path, body):
        with self.assertRaises(HTTPError) as caught:
            self.request(path, body)
        return json.loads(caught.exception.read())["error"]

    def test_capabilities_and_an_idle_project(self):
        capabilities = self.request("/api/live/capabilities")
        self.assertIn("rtmp", capabilities["listen"])
        self.assertEqual(self.request(f"/api/projects/{self.project}/live")["live"]["state"], "idle")
        self.assertEqual(self.status_of("/api/projects/nope/live"), 404)

    def test_only_segment_files_are_served(self):
        folder = self.root / "live" / self.project / "part01"
        folder.mkdir(parents=True)
        (folder / "seg_00000.m4s").write_bytes(b"segment")
        (folder / "live.m3u8").write_text("#EXTM3U", encoding="utf-8")
        with urlopen(f"{self.url}/api/live/{self.project}/part01/seg_00000.m4s") as response:
            self.assertEqual(response.read(), b"segment")
        for path in ("part01/live.m3u8", "part01/..%2F..%2Fmatches.json", "../matches.json", "part01/seg_1.m4s",
                     "recording.json/x/y"):
            self.assertEqual(self.status_of(f"/api/live/{self.project}/{path}"), 404, path)
        self.assertEqual(self.status_of("/api/live/..%2F..%2F/part01/seg_00000.m4s"), 404)

    def test_a_project_with_a_video_does_not_record_over_it(self):
        self.assertIn("rtmp://", self.refused(f"/api/projects/{self.project}/live/start",
                                              {"source": {"kind": "url", "url": "file:///etc/passwd"}}))
        video = self.root / "match.mp4"
        video.write_bytes(b"not really a video")
        self.request(f"/api/projects/{self.project}", {"video_path": str(video)})
        error = self.refused(f"/api/projects/{self.project}/live/start", {"source": {"kind": "listen", "protocol": "rtmp"}})
        self.assertIn("already has a video", error)

    def test_the_page_cannot_set_recording_gaps(self):
        error = self.refused(f"/api/projects/{self.project}", {"live_gaps": [{"at": 1, "length": 2}]})
        self.assertIn("live recorder", error)

    def test_a_recording_becomes_the_projects_video_with_its_gaps(self):
        ffmpeg()
        port = free_port()
        self.request(f"/api/projects/{self.project}/live/start", {"source": {"kind": "listen", "protocol": "rtmp", "port": port}})
        self.assertIn("Stop the live recording", self.refused(f"/api/projects/{self.project}/delete", {}))
        push(port, 3)
        wait_for(lambda: self.request(f"/api/projects/{self.project}/live")["live"]["state"] == "reconnecting")
        # L2: a kick-off and a code while it records, and a clip of it saved straight away.
        self.request(f"/api/projects/{self.project}", {"markers": {"1H": "0:00:01"}})
        self.request(f"/api/projects/{self.project}/codes", {"add": [{"id": "c000001", "code": "goal", "team": "home", "src": "1H", "t": 2}]})
        clip = self.request(f"/api/projects/{self.project}/live/clip", {"start": 0.5, "end": 2.5, "name": "Goal 0.01"})
        self.assertEqual((clip["start"], clip["end"]), (0.5, 2.5))
        self.assertTrue(clip["saved"]["name"].startswith("Live Goal 0.01"))
        self.assertTrue((self.root / "exports" / clip["saved"]["name"]).is_file())
        self.assertIn("5 minutes", self.refused(f"/api/projects/{self.project}/live/clip", {"start": 0, "end": 900}))
        self.assertIn("start, end and name", self.refused(f"/api/projects/{self.project}/live/clip", {"start": 0, "end": 1, "path": "x"}))
        push(port, 3)
        live = self.request(f"/api/projects/{self.project}/live")["live"]
        self.assertGreaterEqual(live["recorded_seconds"], 5)
        first = live["new_segments"][0]
        with urlopen(f"{self.url}/api/live/{self.project}/{first['part']}/init.mp4") as response:
            self.assertIn(b"ftyp", response.read(64))
        self.request(f"/api/projects/{self.project}/live/stop", {})
        done = wait_for(lambda: (lambda live: live if live["state"] != "joining" else None)(
            self.request(f"/api/projects/{self.project}/live")["live"]), 60)
        self.assertEqual(done["state"], "done", done)
        project = self.request(f"/api/projects/{self.project}")["project"]
        self.assertEqual(Path(project["video_path"]).parent, self.root / "exports" / "Recordings")
        self.assertTrue(Path(project["video_path"]).is_file())
        self.assertEqual(len(project["live_gaps"]), 1)
        self.assertEqual(set(project["live_gaps"][0]), {"at", "length"})
        # The code made while it recorded now plays from the joined file at the same moment.
        import pandas as pd
        table = pd.read_csv(project["csv_path"])
        self.assertEqual(project["source"], "coded")
        self.assertEqual((float(table.loc[0, "video_time"]), int(table.loc[0, "minute"]), int(table.loc[0, "second"])), (2.0, 0, 1))
        from packaging.clipmaker_api_server import video_for_period
        self.assertEqual(video_for_period(project, 1), project["video_path"])


if __name__ == "__main__":
    unittest.main()
