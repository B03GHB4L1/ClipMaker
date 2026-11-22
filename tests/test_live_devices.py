"""Live recording from cameras, capture cards and the screen (L3).

CI cannot plug in a camera, so the device listings are read from FFmpeg's own output
captured on real machines, and each system's command line is checked as built. The
screen is recorded for real where the runner has one to record (Windows and Linux).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from packaging.clipmaker_api_server import create_server  # first: it puts app/ on the path
from live import devices, recorder  # noqa: E402
import video_encoder  # noqa: E402

# FFmpeg 7.1 on Windows 11, with names as DirectShow gives them.
DSHOW = r'''[dshow @ 000001e592935d00] "HP Wide Vision HD Camera" (video)
[dshow @ 000001e592935d00]   Alternative name "@device_pnp_\\?\usb#vid_0408&pid_5300&mi_00#6&1260c3a&0&0000#{65e8773d}\global"
[dshow @ 000001e592935d00] "OBS Virtual Camera" (none)
[dshow @ 000001e592935d00]   Alternative name "@device_sw_{860BB310}\{A3FCE0F5}"
[dshow @ 000001e592935d00] "Game Capture HD60: Video" (video)
[dshow @ 000001e592935d00]   Alternative name "@device_pnp_\\?\usb#vid_0fd9&pid_0066#capture"
[dshow @ 000001e592935d00] "Cam Link 4K" (audio, video)
[dshow @ 000001e592935d00]   Alternative name "@device_pnp_\\?\usb#vid_0fd9&pid_007b#camlink"
[dshow @ 000001e592935d00] "Microphone Array (Intel® Smart Sound Technology (Intel® SST))" (audio)
[dshow @ 000001e592935d00]   Alternative name "@device_cm_{33D9A762}\wave_{AA36FD1C}"
[dshow @ 000001e592935d00] "USB Microphone" (audio)
[dshow @ 000001e592935d00]   Alternative name "@device_cm_{33D9A762}\wave_{1}"
[dshow @ 000001e592935d00] "USB Microphone" (audio)
[dshow @ 000001e592935d00]   Alternative name "@device_cm_{33D9A762}\wave_{2}"
[in#0 @ 000001e592935900] Error opening input: Immediate exit requested
'''

AVFOUNDATION = """[AVFoundation indev @ 0x7f8b1c004a00] AVFoundation video devices:
[AVFoundation indev @ 0x7f8b1c004a00] [0] FaceTime HD Camera
[AVFoundation indev @ 0x7f8b1c004a00] [1] Elgato: HD60 S+
[AVFoundation indev @ 0x7f8b1c004a00] [2] Capture screen 0
[AVFoundation indev @ 0x7f8b1c004a00] [3] Capture screen 1
[AVFoundation indev @ 0x7f8b1c004a00] AVFoundation audio devices:
[AVFoundation indev @ 0x7f8b1c004a00] [0] MacBook Pro Microphone
[AVFoundation indev @ 0x7f8b1c004a00] [1] Elgato: HD60 S+
[in#0 @ 0x600001f04000] Error opening input: Input/output error
"""

# The HP camera above, from "-list_options true": raw HD only reaches 8 frames a second.
DSHOW_MODES = """[dshow @ 0000020c60bb5d40] DirectShow video device options (from video devices)
[dshow @ 0000020c60bb5d40]  Pin "Capture" (alternative pin name "0")
[dshow @ 0000020c60bb5d40]   vcodec=mjpeg  min s=640x360 fps=15 max s=640x360 fps=30
[dshow @ 0000020c60bb5d40]   vcodec=mjpeg  min s=640x480 fps=15 max s=640x480 fps=30
[dshow @ 0000020c60bb5d40]   vcodec=mjpeg  min s=1280x720 fps=30 max s=1280x720 fps=30
[dshow @ 0000020c60bb5d40]   vcodec=mjpeg  min s=1280x720 fps=30 max s=1280x720 fps=30 (pc, bt470bg/bt709/unknown, center)
[dshow @ 0000020c60bb5d40]   pixel_format=yuyv422  min s=640x480 fps=15 max s=640x480 fps=30
[dshow @ 0000020c60bb5d40]   pixel_format=yuyv422  min s=1280x720 fps=8 max s=1280x720 fps=8
"""


def windows_listing():
    found = devices.parse_dshow(DSHOW)
    return {"system": "windows", "video": found["video"], "audio": found["audio"],
            "screens": {"Whole desktop": "desktop"}, "device_problem": "", "screen_problem": ""}


class ListingTests(unittest.TestCase):
    def test_directshow_names_kinds_and_awkward_names(self):
        found = devices.parse_dshow(DSHOW)
        self.assertEqual(list(found["video"]), ["HP Wide Vision HD Camera", "Game Capture HD60: Video", "Cam Link 4K"])
        self.assertNotIn("OBS Virtual Camera", found["video"])  # "(none)": the virtual camera is not running
        self.assertEqual(found["video"]["HP Wide Vision HD Camera"], "HP Wide Vision HD Camera")
        # ":" would split "video=...:audio=...", so that device is opened by its alternative name.
        self.assertEqual(found["video"]["Game Capture HD60: Video"], r"@device_pnp_\\?\usb#vid_0fd9&pid_0066#capture")
        self.assertEqual(list(found["audio"]), ["Cam Link 4K", "Microphone Array (Intel® Smart Sound Technology (Intel® SST))",
                                               "USB Microphone", "USB Microphone (2)"])
        self.assertEqual(found["audio"]["USB Microphone (2)"], "USB Microphone")

    def test_avfoundation_splits_cameras_from_screens(self):
        found = devices.parse_avfoundation(AVFOUNDATION)
        self.assertEqual(found["video"], {"FaceTime HD Camera": "0", "Elgato: HD60 S+": "1"})
        self.assertEqual(found["screens"], {"Capture screen 0": "2", "Capture screen 1": "3"})
        self.assertEqual(found["audio"], {"MacBook Pro Microphone": "0", "Elgato: HD60 S+": "1"})

    def test_v4l2_keeps_each_cameras_capture_node(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for node, name, index in (("video0", "HD Webcam", "0"), ("video1", "HD Webcam", "1"),
                                      ("video10", "Capture card", "0"), ("video2", "HD Webcam", "0")):
                (root / node).mkdir()
                (root / node / "name").write_text(name + "\n")
                (root / node / "index").write_text(index + "\n")
            (root / "v4l-subdev0").mkdir()
            self.assertEqual(devices.v4l2_cameras(root), {"HD Webcam": "/dev/video0", "HD Webcam (2)": "/dev/video2",
                                                          "Capture card": "/dev/video10"})
            self.assertEqual(devices.v4l2_cameras(root / "missing"), {})

    def test_the_largest_mode_that_keeps_up(self):
        mode = devices.best_mode(devices.parse_dshow_modes(DSHOW_MODES))
        self.assertEqual((mode["option"], mode["value"], mode["width"], mode["height"], mode["fps"]),
                         ("vcodec", "mjpeg", 1280, 720, 30))
        uhd = [{"option": "vcodec", "value": "mjpeg", "width": 3840, "height": 2160, "min_fps": 30, "max_fps": 30},
               {"option": "pixel_format", "value": "nv12", "width": 1920, "height": 1080, "min_fps": 25, "max_fps": 60}]
        mode = devices.best_mode(uhd)
        self.assertEqual((mode["width"], mode["fps"]), (1920, 30))  # 4K is recorded at 1080p, at 30 frames
        self.assertIsNone(devices.best_mode([{**uhd[1], "max_fps": 15, "min_fps": 5}]))

    def test_this_systems_ffmpeg_has_its_capture_inputs(self):
        """Whatever this FFmpeg lacks must show as a stated problem, never a silent gap."""
        try:
            ffmpeg = video_encoder.find_ffmpeg()
        except ValueError:
            self.skipTest("FFmpeg is not available")
        formats = devices.input_formats(ffmpeg)
        listing = devices.list_devices(ffmpeg)
        print(f"\n{devices.system()} FFmpeg capture inputs: {sorted(formats)}; "
              f"device problem: {listing['device_problem']!r}; screen problem: {listing['screen_problem']!r}")
        wanted = {"windows": {"dshow", "gdigrab"}, "macos": {"avfoundation"}, "linux": {"v4l2"}}[devices.system()]
        self.assertLessEqual(wanted, formats | ({"v4l2"} if "video4linux2" in formats else set()))
        self.assertTrue(listing["screens"] or listing["screen_problem"])
        self.assertTrue(listing["video"] or listing["device_problem"])
        self.assertEqual(set(devices.public(listing)),
                         {"system", "video", "audio", "screens", "device_problem", "screen_problem"})


class SourceTests(unittest.TestCase):
    def test_only_listed_devices_are_accepted(self):
        listing = windows_listing()
        for source, message in (
                ({"kind": "device", "video": "C:/Windows/System32"}, "no longer connected"),
                ({"kind": "device", "video": ""}, "Choose a camera"),
                ({"kind": "device", "video": "Cam Link 4K", "audio": "/dev/snd"}, "no longer connected"),
                ({"kind": "screen", "screen": "desktop"}, "Choose a screen"),
                ({"kind": "screen", "screen": "Whole desktop"}, None)):
            if message:
                with self.assertRaisesRegex(ValueError, message):
                    recorder.check_source(source, set(), listing)
            else:
                self.assertEqual(recorder.check_source(source, set(), listing)["video_id"], "desktop")
        with self.assertRaisesRegex(ValueError, "Look for devices"):
            recorder.check_source({"kind": "device", "video": "Cam Link 4K"}, set())

    def test_a_stated_problem_is_the_refusal(self):
        listing = {**windows_listing(), "screens": {}, "screen_problem": "This copy of FFmpeg cannot record the screen."}
        with self.assertRaisesRegex(ValueError, "cannot record the screen"):
            recorder.check_source({"kind": "screen", "screen": "Whole desktop"}, set(), listing)

    def test_windows_camera_and_microphone_are_one_input_in_their_best_mode(self):
        listing = windows_listing()
        with mock.patch.object(devices, "_run", return_value=DSHOW_MODES):
            source = recorder.check_source({"kind": "device", "video": "Game Capture HD60: Video", "audio": "USB Microphone (2)"},
                                           set(), listing, "ffmpeg")
        self.assertEqual(recorder.describe(source), "Camera: Game Capture HD60: Video, sound from USB Microphone (2)")
        args = recorder.input_args(source)
        self.assertEqual(args[args.index("-i") + 1],
                         r"video=@device_pnp_\\?\usb#vid_0fd9&pid_0066#capture:audio=USB Microphone")
        self.assertEqual(args[args.index("-video_size") + 1], "1280x720")
        self.assertEqual(args[args.index("-vcodec") + 1], "mjpeg")
        output = recorder.output_args(True, source)
        self.assertEqual(output[:4], ["-map", "0:v:0", "-map", "0:a:0?"])
        self.assertIn("zerolatency", output)
        self.assertEqual(output[output.index("-vf") + 1], "scale=trunc(iw/2)*2:-2,format=yuv420p")

    def test_windows_screen_takes_its_sound_from_a_second_input(self):
        source = recorder.check_source({"kind": "screen", "screen": "Whole desktop", "audio": "USB Microphone"},
                                       set(), windows_listing())
        args = recorder.input_args(source)
        self.assertEqual(args[args.index("-f") + 1], "gdigrab")
        self.assertEqual(args[-2:], ["-i", "audio=USB Microphone"])
        output = recorder.output_args(True, source)
        self.assertEqual(output[:4], ["-map", "0:v:0", "-map", "1:a:0"])
        self.assertIn("min(1920", output[output.index("-vf") + 1])
        silent = recorder.check_source({"kind": "screen", "screen": "Whole desktop"}, set(), windows_listing())
        self.assertEqual(recorder.input_args(silent).count("-i"), 1)
        self.assertEqual(recorder.describe(silent), "Screen: Whole desktop, no sound")

    def test_macos_and_linux_commands(self):
        found = devices.parse_avfoundation(AVFOUNDATION)
        mac = {"system": "macos", **found, "device_problem": "", "screen_problem": ""}
        source = recorder.check_source({"kind": "device", "video": "Elgato: HD60 S+", "audio": "Elgato: HD60 S+"}, set(), mac)
        args = recorder.input_args(source)
        self.assertEqual(args[args.index("-i") + 1], "1:1")  # by index, so ":" in a name cannot split it
        screen = recorder.check_source({"kind": "screen", "screen": "Capture screen 1"}, set(), mac)
        args = recorder.input_args(screen)
        self.assertEqual(args[args.index("-i") + 1], "3:none")
        self.assertIn("-capture_cursor", args)
        linux = {"system": "linux", "video": {"HD Webcam": "/dev/video0"}, "audio": {"Default microphone": "pulse:default"},
                 "screens": {"Whole screen": ":0"}, "device_problem": "", "screen_problem": ""}
        source = recorder.check_source({"kind": "device", "video": "HD Webcam", "audio": "Default microphone"}, set(), linux)
        self.assertEqual(recorder.input_args(source)[-6:], ["-thread_queue_size", "1024", "-f", "pulse", "-i", "default"])
        self.assertEqual(recorder.output_args(True, source)[:4], ["-map", "0:v:0", "-map", "1:a:0"])
        screen = recorder.check_source({"kind": "screen", "screen": "Whole screen"}, set(), linux)
        args = recorder.input_args(screen)
        self.assertEqual((args[args.index("-f") + 1], args[args.index("-i") + 1]), ("x11grab", ":0"))

    def test_linux_on_wayland_says_why_there_is_no_screen(self):
        with mock.patch.object(devices, "system", return_value="linux"), \
             mock.patch.object(devices, "input_formats", return_value={"v4l2", "x11grab", "alsa"}), \
             mock.patch.object(devices, "v4l2_cameras", return_value={}), \
             mock.patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}):
            listing = devices.list_devices("ffmpeg")
        self.assertEqual(listing["screens"], {})
        self.assertIn("Wayland", listing["screen_problem"])
        self.assertIn("No camera", listing["device_problem"])
        self.assertEqual(listing["audio"], {"Default microphone": "alsa:default"})

    def test_a_camera_or_screen_is_encoded_from_the_start(self):
        source = recorder.check_source({"kind": "screen", "screen": "Whole desktop"}, set(), windows_listing())
        with tempfile.TemporaryDirectory() as folder:
            recording = recorder.Recording("ffmpeg", Path(folder) / "r", source)
            self.assertTrue(recording.transcode)
            self.assertEqual(recording.state, "connecting")
            self.assertEqual(recording.status()["kind"], "screen")

    def test_why_a_device_would_not_open(self):
        camera = {"kind": "device"}
        self.assertIn("Close any other app", recorder._explain_device(["[dshow] Could not run graph of device"], camera))
        self.assertIn("not allowed to use the screen",
                      recorder._explain_device(["[AVFoundation indev] Not authorized to capture screen"], {"kind": "screen"}))
        self.assertIn("30 frames", recorder._explain_device(["Selected framerate (30.000000) is not supported"], camera))
        self.assertIn("FFmpeg said: odd", recorder._explain_device(["odd"], camera))


@unittest.skipIf(sys.platform == "darwin", "macOS asks for Screen Recording permission, which a CI runner cannot give")
class ScreenRecordingTests(unittest.TestCase):
    """A real screen recording, where the machine has a screen FFmpeg can read."""

    def test_record_and_join_the_screen(self):
        try:
            ffmpeg = video_encoder.find_ffmpeg()
        except ValueError:
            self.skipTest("FFmpeg is not available")
        listing = devices.list_devices(ffmpeg)
        if not listing["screens"]:
            self.skipTest(f"no screen to record here: {listing['screen_problem']}")
        source = recorder.check_source({"kind": "screen", "screen": next(iter(listing["screens"]))}, set(), listing, ffmpeg)
        folder = Path(tempfile.mkdtemp())
        try:
            recording = recorder.Recording(ffmpeg, folder / "rec", source)
            recording.start()
            deadline = time.time() + 40
            while time.time() < deadline and recording.status()["recorded_seconds"] < 4 and recording.state != "failed":
                time.sleep(0.5)
            self.assertNotEqual(recording.state, "failed", recording.error)
            recording.stop()
            length = recorder.join(ffmpeg, folder / "rec", folder / "screen.mp4")
            self.assertGreaterEqual(length, 3.5)
            self.assertIn("avc1", recorder.codecs(folder / "rec" / "part01" / "init.mp4"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


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

    def test_devices_are_listed_by_name_and_only_listed_ones_start(self):
        listing = self.request("/api/live/devices")
        self.assertEqual(set(listing), {"system", "video", "audio", "screens", "device_problem", "screen_problem"})
        self.assertEqual(self.request("/api/live/capabilities")["system"], devices.system())
        with self.assertRaises(HTTPError) as caught:
            self.request(f"/api/projects/{self.project}/live/start",
                         {"source": {"kind": "device", "video": "../../etc/passwd", "audio": ""}})
        self.assertEqual(caught.exception.code, 400)
        error = json.loads(caught.exception.read())["error"]
        self.assertTrue("no longer connected" in error or error == listing["device_problem"], error)
        self.assertEqual(self.request(f"/api/projects/{self.project}/live")["live"]["state"], "idle")


if __name__ == "__main__":
    unittest.main()
