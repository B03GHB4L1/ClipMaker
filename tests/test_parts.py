"""Parts of a clip: cut, reorder, repeat (docs/TELESTRATION_PLAN.md, M9).

The clip is four one-second blocks: the picture's red level steps 0, 60, 120, 180 and the sound is a tone for
the first two seconds, then silence. That makes every output frame and every second of sound identifiable,
so a reordered, cut and repeated export can be checked by decoding it.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.telestration import annotations, export, parts as cuts
from app.telestration.tracker import read_frames
from packaging.clipmaker_api_server import _find_ffmpeg

W, H, FPS = 160, 120, 10
RECORD = {"fps": FPS, "width": W, "height": H, "duration": 4, "frames": 40}
CASES = json.loads((Path(__file__).parent / "fixtures" / "parts_cases.json").read_text(encoding="utf-8"))


def stepped_clip(path: Path) -> Path:
    command = [_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d=4,format=gbrp,geq=r='60*floor(T)':g=128:b=128",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4,volume=enable='gte(t,2)':volume=0",
               "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(command, check=True)
    return path


def audio_of(path: Path) -> np.ndarray:
    raw = subprocess.run([_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-ar", "48000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32)


def loudness(samples, start, end):
    part = samples[int(start * 48000):int(end * 48000)]
    return float(np.sqrt(np.mean(part ** 2))) if part.size else 0.0


class PartsMathTests(unittest.TestCase):
    def test_cut_clip_maps_to_source_like_the_editor(self):
        # The same fixture runs against ui/annotate/parts.js (tests/parts.test.mjs).
        for case in CASES:
            parts = case["parts"]
            self.assertEqual(cuts.cut_frames(parts, case["frames"]), case["cutFrames"], case["name"])
            for cut, source in case["map"]:
                self.assertEqual(cuts.cut_to_source(cut, parts, case["frames"]), source, f"{case['name']}: {cut}")

    def test_cut_clip_record_has_the_cut_length(self):
        self.assertIs(cuts.cut_clip(RECORD, None), RECORD)
        cut = cuts.cut_clip(RECORD, [{"from": 0, "to": 10}, {"from": 30, "to": 40}])
        self.assertEqual((cut["frames"], cut["duration"], cut["fps"]), (20, 2.0, FPS))

    def test_bad_parts_are_refused_and_a_whole_clip_is_not_stored(self):
        for bad in ([], "x", [{"from": 0}], [{"from": 5, "to": 5}], [{"from": 0, "to": 41}], [{"from": -1, "to": 3}],
                    [{"from": 0, "to": 3, "x": 1}], [{"from": 0.5, "to": 3}], [{"from": True, "to": 3}],
                    [{"from": 0, "to": 1}] * 201):
            with self.assertRaises(ValueError, msg=bad):
                cuts.clean(bad, 40)
        self.assertIsNone(cuts.clean(None, 40))
        self.assertIsNone(cuts.clean([{"from": 0, "to": 40}], 40))
        self.assertEqual(cuts.clean([{"from": 0, "to": 20}, {"from": 0, "to": 20}], 40), [{"from": 0, "to": 20}, {"from": 0, "to": 20}])

    def test_audio_plan_joins_parts_with_silence_under_freezes(self):
        plan = cuts.audio_plan([{"from": 20, "to": 30}, {"from": 0, "to": 10}], [{"atFrame": 15, "seconds": 0.5}], 10, 100, 40)
        self.assertEqual(plan, [("copy", 200, 300), ("copy", 0, 50), ("silence", 50, 0), ("copy", 50, 100)])
        whole = cuts.audio_plan(None, [{"atFrame": 5, "seconds": 1.0}], 10, 100, 40)
        self.assertEqual(whole, [("copy", 0, 50), ("silence", 100, 0), ("copy", 50, -1)])  # as before parts existed


class PartsDocumentTests(unittest.TestCase):
    base = {"version": 1, "items": [], "freezes": []}

    def test_a_document_with_parts_is_stored_and_old_ones_are_unchanged(self):
        self.assertNotIn("parts", annotations.clean_document(self.base, 4, 40))
        cut = {**self.base, "parts": [{"from": 20, "to": 30}, {"from": 0, "to": 10}]}
        self.assertEqual(annotations.clean_document(cut, 4, 40)["parts"], cut["parts"])
        self.assertNotIn("parts", annotations.clean_document({**self.base, "parts": [{"from": 0, "to": 40}]}, 4, 40))

    def test_freezes_and_drawings_fit_the_cut_clip_not_the_source(self):
        parts = [{"from": 20, "to": 30}, {"from": 0, "to": 10}]  # a 2 s cut clip
        with self.assertRaises(ValueError):  # frame 25 of a 20-frame cut clip
            annotations.clean_document({**self.base, "parts": parts, "freezes": [{"atFrame": 25, "seconds": 1}]}, 4, 40)
        stored = annotations.clean_document({**self.base, "parts": parts, "freezes": [{"atFrame": 15, "seconds": 1}]}, 4, 40)
        self.assertEqual(stored["freezes"][0]["atFrame"], 15)
        late = {"id": "a", "kind": "line", "points": [[0.1, 0.1], [0.2, 0.2]], "show": {"from": 0, "to": 3.6}}
        with self.assertRaises(ValueError):  # 3.6 s is past the 2 s cut clip plus a 1 s freeze
            annotations.clean_document({**self.base, "parts": parts, "freezes": [{"atFrame": 15, "seconds": 1}], "items": [late]}, 4, 40)
        ok = {**late, "show": {"from": 0, "to": 3}}
        annotations.clean_document({**self.base, "parts": parts, "freezes": [{"atFrame": 15, "seconds": 1}], "items": [ok]}, 4, 40)

    def test_a_board_still_comes_from_a_source_frame(self):
        board = {"kind": "board", "view": "full", "theme": "grass", "fromFrame": 35}
        parts = [{"from": 20, "to": 30}]
        stored = annotations.clean_document({**self.base, "parts": parts, "freezes": [{"atFrame": 3, "seconds": 1, "background": board}]}, 4, 40)
        self.assertEqual(stored["freezes"][0]["background"]["fromFrame"], 35)


class PartsExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.clip = stepped_clip(cls.root / "steps.mp4")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def render(self, parts, freezes=()):
        freezes = list(freezes)
        target = self.root / f"out-{len(list(self.root.iterdir()))}.mp4"
        count = export.output_frames(RECORD, freezes, parts)
        export.render(_find_ffmpeg(), self.clip, RECORD, freezes, count, {}, str(target), "libx264", parts=parts)
        return target, count

    def test_output_frames_follow_the_parts_in_order(self):
        parts = [{"from": 20, "to": 30}, {"from": 0, "to": 10}, {"from": 0, "to": 5}]
        shown = export.source_frames(RECORD, [{"atFrame": 12, "seconds": 0.3}], 28, parts)
        self.assertEqual(shown[:10], list(range(20, 30)))
        self.assertEqual(shown[10:12], [0, 1])
        self.assertEqual(shown[12:15], [2, 2, 2])  # the freeze on cut frame 12 holds source frame 2
        self.assertEqual(shown[15:], list(range(2, 10)) + list(range(0, 5)))  # it plays on from the held frame, then the repeat

    def test_a_cut_reordered_and_repeated_clip_decodes_in_that_order_with_matching_sound(self):
        parts = [{"from": 20, "to": 30}, {"from": 0, "to": 10}, {"from": 0, "to": 10}]  # red 120 silent, then 0 loud twice
        target, count = self.render(parts)
        self.assertEqual(count, 30)
        frames = list(read_frames(_find_ffmpeg(), target, FPS, 0, count + 5, (W, H)))
        self.assertEqual(len(frames), 30)
        red = lambda n: int(frames[n][60, 80][2])
        for n in (1, 5, 9):
            self.assertLess(abs(red(n) - 120), 14, n)
        for n in (11, 15, 19, 21, 25, 29):
            self.assertLess(red(n), 14, n)
        samples = audio_of(target)
        self.assertAlmostEqual(len(samples) / 48000, 3.0, delta=0.1)
        self.assertLess(loudness(samples, 0.1, 0.9), 60)  # the silent second came first
        self.assertGreater(loudness(samples, 1.1, 1.9), 1000)  # then the tone, played twice
        self.assertGreater(loudness(samples, 2.1, 2.9), 1000)

    def test_a_freeze_inside_a_repeated_part_keeps_the_sound_in_step(self):
        parts = [{"from": 20, "to": 30}, {"from": 0, "to": 10}]
        target, count = self.render(parts, [{"atFrame": 15, "seconds": 0.5}])  # half a second into the second part
        self.assertEqual(count, 25)
        samples = audio_of(target)
        self.assertAlmostEqual(len(samples) / 48000, 2.5, delta=0.1)
        self.assertGreater(loudness(samples, 1.1, 1.45), 1000)  # tone before the freeze
        self.assertLess(loudness(samples, 1.6, 1.95), 60)  # silence under it
        self.assertGreater(loudness(samples, 2.1, 2.45), 1000)  # tone after it
        frames = list(read_frames(_find_ffmpeg(), target, FPS, 0, count + 5, (W, H)))
        self.assertLess(int(frames[17][60, 80][2]), 14)  # held on the part's picture

    def test_a_clip_without_parts_renders_as_before(self):
        target, count = self.render(None)
        self.assertEqual(count, 40)
        frames = list(read_frames(_find_ffmpeg(), target, FPS, 0, count + 5, (W, H)))
        self.assertEqual(len(frames), 40)
        self.assertLess(abs(int(frames[35][60, 80][2]) - 180), 14)


if __name__ == "__main__":
    unittest.main()
