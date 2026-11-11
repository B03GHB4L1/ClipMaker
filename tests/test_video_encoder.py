"""Encoder choice for clips: graphics card when it works, x264 otherwise.

docs/EXPORT_SPEED_PLAN.md. CI runners have no GPU, so the hardware path is
simulated by an encoder that always fails: the fallback must finish the
export in software, say so, and never mix encoders inside one reel.
"""
import queue
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import video_encoder as ve  # noqa: E402
from packaging.clipmaker_api_server import build_clip_config, render_preview_clip  # noqa: E402
import clipmaker_core as core  # noqa: E402

real_video_args = ve.video_args


def broken_hardware(encoder, ffmpeg, crf, preset):
    """NVENC that fails on every source, like a card without H.264 support."""
    if encoder == ve.NVENC:
        return [], ["-c:v", "vizorplay_missing_encoder"]
    return real_video_args(encoder, ffmpeg, crf, preset)


class EncoderChoiceTests(unittest.TestCase):
    def setUp(self):
        ve._cache.clear()
        self.addCleanup(ve._cache.clear)

    def test_software_setting_and_override_never_use_the_card(self):
        with patch.object(ve, "probe", return_value={"encoder": ve.NVENC, "cuda_decode": True}):
            self.assertEqual(ve.resolve("auto", "ffmpeg"), ve.NVENC)
            self.assertEqual(ve.resolve("software", "ffmpeg"), ve.SOFTWARE)
            with patch.dict("os.environ", {"VIZORPLAY_VIDEO_ENCODER": "software"}):
                self.assertEqual(ve.resolve("auto", "ffmpeg"), ve.SOFTWARE)
        with patch.object(ve, "probe", return_value={"encoder": None, "cuda_decode": False}):
            self.assertEqual(ve.resolve("auto", "ffmpeg"), ve.SOFTWARE)

    def test_quality_setting_maps_to_measured_nvenc_level(self):
        with patch.object(ve, "probe", return_value={"encoder": ve.NVENC, "cuda_decode": True}):
            before, video = ve.video_args(ve.NVENC, "ffmpeg", 20, "veryfast")
            self.assertEqual(before, ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
            self.assertEqual(video[video.index("-cq") + 1], "27")
            self.assertEqual(ve.video_args(ve.NVENC, "ffmpeg", 99, "veryfast")[1][video.index("-cq") + 1], "37")
        with patch.object(ve, "probe", return_value={"encoder": ve.NVENC, "cuda_decode": False}):
            self.assertEqual(ve.video_args(ve.NVENC, "ffmpeg", 20, "veryfast")[0], [])
        self.assertEqual(ve.video_args(ve.SOFTWARE, "ffmpeg", 22, "fast"),
                         ([], ["-c:v", "libx264", "-preset", "fast", "-crf", "22", "-threads", "0"]))
        self.assertEqual((ve.workers(ve.NVENC), ve.workers(ve.SOFTWARE)), (2, 1))

    def test_detection_runs_once_per_binary(self):
        with patch.object(ve, "_quiet", return_value=False) as quiet:
            self.assertIsNone(ve.probe("ffmpeg-a")["encoder"])
            ve.probe("ffmpeg-a")
            self.assertEqual(quiet.call_count, 1)  # sample creation failed: no hardware tests
            ve.probe("ffmpeg-b")
            self.assertEqual(quiet.call_count, 2)

    def test_real_ffmpeg_detection_reports_a_supported_answer(self):
        result = ve.probe(ve.find_ffmpeg())
        self.assertIn(result["encoder"], {None, ve.NVENC})
        self.assertIsInstance(result["cuda_decode"], bool)

    def test_setting_is_validated_and_defaults_to_automatic(self):
        with tempfile.TemporaryDirectory() as name:
            csv = Path(name) / "match.csv"
            csv.write_text("minute,second,type,period,team\n0,1,Goal,1,Home\n", encoding="utf-8")
            match = {"id": "m", "csv_path": str(csv), "markers": {"1H": "00:00:00", "2H": "00:00:00"}}
            self.assertEqual(build_clip_config(match, {}, Path(name))["video_encoder"], "auto")
            self.assertEqual(build_clip_config(match, {"video_encoder": "software"}, Path(name))["video_encoder"],
                             "software")
            with self.assertRaisesRegex(ValueError, "automatic or software"):
                build_clip_config(match, {"video_encoder": "h264_nvenc"}, Path(name))


class FallbackMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.ffmpeg = ve.find_ffmpeg()
        cls.video = cls.root / "match.mp4"
        subprocess.run([cls.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(cls.video)], check=True, capture_output=True, timeout=60)
        cls.csv = cls.root / "match.csv"
        cls.csv.write_text("minute,second,type,period,team\n0,2,Goal,1,Home\n0,8,Goal,1,Away\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def duration(self, path):
        probe = subprocess.run([self.ffmpeg, "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=60)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        hours, minutes, seconds = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr).groups()
        self.assertIn("Audio", probe.stderr)
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    def export(self, individual, encoder_setting="auto"):
        out = self.root / f"out-{individual}-{encoder_setting}"
        match = {"id": "m", "csv_path": str(self.csv), "video_path": str(self.video),
                 "markers": {"1H": "00:00:00", "2H": "00:00:00"}}
        config = build_clip_config(match, {
            "dry_run": False, "individual_clips": individual, "video_encoder": encoder_setting,
            "output_dir": str(out), "output_filename": "Reel", "encoder_preset": "ultrafast",
            "clip_windows": [{"start": 1, "end": 3, "period": 1}, {"start": 6, "end": 9, "period": 1}]}, self.root)
        messages, progress = queue.Queue(), queue.Queue()
        core.run_clip_maker(config, messages, progress)
        logs = [str(m.get("msg", "")) for m in messages.queue]
        kinds = [m.get("type") for m in messages.queue if m.get("type") in {"done", "error"}]
        return sorted(out.glob("*.mp4")), logs, kinds

    def test_reel_redoes_every_part_in_software_when_the_card_fails(self):
        with patch.object(ve, "resolve", return_value=ve.NVENC), patch.object(ve, "video_args", side_effect=broken_hardware):
            files, logs, kinds = self.export(individual=False)
        self.assertEqual(kinds, ["done"], logs)
        self.assertTrue(any("Encoding with graphics card" in line for line in logs), logs)
        self.assertTrue(any("continuing with software encoding" in line for line in logs), logs)
        self.assertEqual(len(files), 1)
        self.assertAlmostEqual(self.duration(files[0]), 5.0, delta=0.3)

    def test_individual_clips_finish_in_software_when_the_card_fails(self):
        with patch.object(ve, "resolve", return_value=ve.NVENC), patch.object(ve, "video_args", side_effect=broken_hardware):
            files, logs, kinds = self.export(individual=True)
        self.assertEqual(kinds, ["done"], logs)
        self.assertEqual([round(self.duration(path)) for path in files], [2, 3])

    def test_software_setting_exports_and_says_so(self):
        files, logs, kinds = self.export(individual=False, encoder_setting="software")
        self.assertEqual(kinds, ["done"], logs)
        self.assertTrue(any("Encoding with software (x264)" in line for line in logs), logs)
        self.assertAlmostEqual(self.duration(files[0]), 5.0, delta=0.3)

    def test_preview_falls_back_but_an_exact_encoder_does_not(self):
        with patch.object(ve, "resolve", return_value=ve.NVENC), patch.object(ve, "video_args", side_effect=broken_hardware):
            preview = render_preview_clip(str(self.video), 1, 3, self.root / "previews", 20, "ultrafast", "128k", "auto")
            self.assertAlmostEqual(self.duration(preview), 2.0, delta=0.3)
            with self.assertRaises(ve.HardwareEncodeError):
                render_preview_clip(str(self.video), 1, 3, self.root / "previews", 20, "ultrafast", "128k", ve.NVENC)

    def test_analysis_reel_never_mixes_encoders(self):
        from packaging import clipmaker_api_server as server
        calls = []
        original = server.render_preview_clip

        def record(*args):
            calls.append(args[-1])
            return original(*args)
        events = [{"minute": 0, "second": 2, "period": "FirstHalf"}, {"minute": 0, "second": 8, "period": "FirstHalf"}]
        windows = iter([(1, 1.0, 2.0), (1, 6.0, 2.0)] * 2)
        with patch.object(ve, "resolve", return_value=ve.NVENC), patch.object(ve, "video_args", side_effect=broken_hardware), \
                patch.object(server, "render_preview_clip", side_effect=record), \
                patch("analysis_core.video.clip_window", side_effect=lambda *a: next(windows)):
            folder = self.root / "analysis-clips"
            folder.mkdir(exist_ok=True)
            reel = server.analysis_reel({"video_path": str(self.video)}, SimpleNamespace(df_all=None), events,
                                        {}, [], 1, 1, folder)
        self.assertEqual(calls, [ve.NVENC, ve.SOFTWARE, ve.SOFTWARE])
        self.assertAlmostEqual(self.duration(reel), 4.0, delta=0.3)


if __name__ == "__main__":
    unittest.main()
