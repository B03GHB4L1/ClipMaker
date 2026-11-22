"""Analyst editor (docs/TELESTRATION_PLAN.md, M1): drawing documents, copying a
watched clip into a project, opening it, saving and reopening its drawings."""
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.telestration import annotations, timeline
from app.telestration.clips import probe_video
from packaging.clipmaker_api_server import create_server, _find_ffmpeg


def ring(item_id="r1", **overrides):
    item = {"id": item_id, "kind": "ring", "points": [[0.4, 0.7]], "geometry": {"rx": 0.03, "ry": 0.01},
            "style": {"stroke": "#FFD400", "width": 3}, "show": {"from": 0, "to": 1.5}}
    item.update(overrides)
    return item


def document(*items):
    return {"version": 1, "items": list(items), "freezes": []}


class DocumentTests(unittest.TestCase):
    def test_every_drawing_kind_round_trips(self):
        items = [
            ring(),
            {"id": "s1", "kind": "spotlight", "points": [[0.5, 0.8]], "geometry": {"rx": 0.04, "ry": 0.012, "h": 0.4},
             "style": {"fill": "#ffffff", "fillOpacity": 0.3}, "show": {"from": 0, "to": 2}},
            {"id": "a1", "kind": "arrow", "points": [[0.1, 0.1], [0.5, 0.5]], "style": {"dashed": True},
             "show": {"from": 0.2, "to": 0.4}},
            {"id": "l1", "kind": "line", "points": [[0, 0], [1, 1]], "show": {"from": 0, "to": 2}},
            {"id": "f1", "kind": "freehand", "points": [[0.1, 0.1], [0.2, 0.15], [0.3, 0.1]], "show": {"from": 0, "to": 2}},
            {"id": "t1", "kind": "text", "points": [[0.05, 0.05]], "text": "Line breaks here",
             "style": {"color": "#111111", "background": None, "size": 36}, "show": {"from": 0, "to": 2}},
            {"id": "z1", "kind": "zone", "points": [[0.1, 0.5], [0.4, 0.5], [0.4, 0.8]],
             "style": {"fill": "#2f80ed", "fillOpacity": 0.25}, "show": {"from": 0, "to": 2}},
        ]
        clean = annotations.clean_document(document(*items), duration=2, frames=50)
        self.assertEqual([item["kind"] for item in clean["items"]],
                         ["ring", "spotlight", "arrow", "line", "freehand", "text", "zone"])
        self.assertEqual(clean["items"][0]["style"]["stroke"], "#ffd400")  # colours are lower-cased
        self.assertIsNone(clean["items"][5]["style"]["background"])  # transparent text background kept
        self.assertEqual(clean["items"][0]["show"]["animate"], "none")

    def test_zones_can_be_shaded_with_lines(self):
        for pattern in ("solid", "lines", "cross"):
            zone = {"id": "z", "kind": "zone", "points": [[0.1, 0.1], [0.5, 0.1], [0.4, 0.6]],
                    "style": {"fill": "#2F80ED", "pattern": pattern}, "show": {"from": 0, "to": 1}}
            clean = annotations.clean_document(document(zone), duration=2, frames=50)
            self.assertEqual(clean["items"][0]["style"], {"fill": "#2f80ed", "pattern": pattern})

    def test_bad_documents_are_refused_not_repaired(self):
        cases = {
            "wrong version": {"version": 2, "items": []},
            "unknown kind": document(ring(kind="laser")),
            "point far off frame": document(ring(points=[[3, 0.5]])),
            "bad colour": document(ring(style={"stroke": "red"})),
            "unknown style": document(ring(style={"glow": 3})),
            "ends before it starts": document(ring(show={"from": 1, "to": 0.5})),
            "past the clip": document(ring(show={"from": 0, "to": 9})),
            "zone with two corners": document({"id": "z", "kind": "zone", "points": [[0, 0], [1, 1]],
                                               "show": {"from": 0, "to": 1}}),
            "empty text": document({"id": "t", "kind": "text", "points": [[0, 0]], "text": " ",
                                    "show": {"from": 0, "to": 1}}),
            "duplicate ids": document(ring("same"), ring("same")),
            "not a number": document(ring(geometry={"rx": "wide", "ry": 0.01})),
            "infinite": document(ring(points=[[float("inf"), 0.5]])),
            "unknown animation": document(ring(show={"from": 0, "to": 1, "animate": "spin"})),
            "unknown zone fill": document({"id": "z", "kind": "zone", "points": [[0, 0], [1, 0], [1, 1]],
                                           "style": {"pattern": "dots"}, "show": {"from": 0, "to": 1}}),
            "freeze off the clip": {"version": 1, "items": [], "freezes": [{"atFrame": 50, "seconds": 2}]},
            "freeze too long": {"version": 1, "items": [], "freezes": [{"atFrame": 3, "seconds": 61}]},
            "freeze too short": {"version": 1, "items": [], "freezes": [{"atFrame": 3, "seconds": 0}]},
            "two freezes on a frame": {"version": 1, "items": [], "freezes": [{"atFrame": 3, "seconds": 1},
                                                                              {"atFrame": 3, "seconds": 2}]},
            "freeze with extras": {"version": 1, "items": [], "freezes": [{"atFrame": 3, "seconds": 1, "audio": True}]},
            "fractional freeze frame": {"version": 1, "items": [], "freezes": [{"atFrame": 3.5, "seconds": 1}]},
            "arrow cannot pulse": document({"id": "a", "kind": "arrow", "points": [[0, 0], [1, 1]],
                                            "show": {"from": 0, "to": 1, "pulse": True}}),
            "unknown easing": document(ring(show={"from": 0, "to": 1, "animate": "fade", "ease": "bounce"})),
            "unknown exit": document(ring(show={"from": 0, "to": 1, "animateOut": "spin"})),
            "animation too long": document(ring(show={"from": 0, "to": 1, "animate": "fade", "animSeconds": 9})),
            "unknown timing setting": document(ring(show={"from": 0, "to": 1, "loop": True})),
            "path-like id": document(ring("../x")),
        }
        for name, value in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                annotations.clean_document(value, duration=2, frames=50)

    def test_freezes_lengthen_the_time_drawings_may_use(self):
        late = ring(show={"from": 2.5, "to": 5.4, "animate": "draw", "animateOut": "fade", "animSeconds": 0.4,
                          "ease": "linear", "pulse": True})
        value = {"version": 1, "items": [late], "freezes": [{"atFrame": 30, "seconds": 1.5}, {"atFrame": 0, "seconds": 1.5}]}
        clean = annotations.clean_document(value, duration=2, frames=50)
        self.assertEqual([f["atFrame"] for f in clean["freezes"]], [0, 30])  # stored in order
        self.assertEqual(clean["items"][0]["show"], late["show"])
        with self.assertRaises(ValueError):  # without the freezes it would run past the clip
            annotations.clean_document({**value, "freezes": []}, duration=2, frames=50)

    def test_the_pitch_is_kept_on_one_frame_and_rings_and_arrows_can_lie_flat(self):
        # P1 (docs/CODING_AND_PITCH_PLAN.md section P): the clip's pitch marks and flat drawings.
        marks = [{"id": "half-far", "at": [0.3, 0.22]}, {"id": "circle-right", "at": [0.1756, 0.5733]},
                 {"id": "box-r-far", "at": [0.8774, 0.3636]}, {"id": "box-r-near", "at": [0.6291, 0.9506]}]
        pitch = {"keys": [{"frame": 40, "pairs": marks}]}
        flat = [ring(style={"stroke": "#ffd400", "width": 4, "flat": True}),
                {"id": "a1", "kind": "arrow", "points": [[0.1, 0.1], [0.5, 0.5]], "style": {"flat": True},
                 "show": {"from": 0, "to": 1}}]
        clean = annotations.clean_document({**document(*flat), "pitch": pitch}, duration=2, frames=50)
        self.assertEqual(clean["pitch"], pitch)
        self.assertTrue(all(item["style"]["flat"] for item in clean["items"]))
        self.assertNotIn("pitch", annotations.clean_document(document(ring()), duration=2, frames=50))
        zone = {"id": "z1", "kind": "zone", "points": [[0.1, 0.5], [0.4, 0.5], [0.4, 0.8]], "style": {"flat": True},
                "show": {"from": 0, "to": 2}}
        for bad, message in (
                ({"keys": []}, "1 calibrated frame"),
                ({"keys": [{"frame": 40, "pairs": marks}, {"frame": 41, "pairs": marks}]}, "1 calibrated frame"),
                ({"keys": [{"frame": 50, "pairs": marks}]}, "not in the clip"),  # frame 51 of 50
                ({"keys": [{"frame": True, "pairs": marks}]}, "not in the clip"),
                ({"keys": [{"frame": 1, "pairs": marks[:3]}]}, "4 to 40"),
                ({"keys": [{"frame": 1, "pairs": marks + [marks[0]]}]}, "placed twice"),
                ({"keys": [{"frame": 1, "pairs": [{"id": "../x", "at": [0, 0]}] + marks[1:]}]}, "its name"),
                ({"keys": [{"frame": 1, "pairs": [{"id": "centre", "at": [9, 0]}] + marks[1:]}]}, "between"),
                ({"keys": [{"frame": 1, "pairs": marks, "note": "x"}]}, "frame and its pitch marks"),
                ({"keys": [], "extra": 1}, "list its calibrated frames")):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                annotations.clean_document({**document(ring()), "pitch": bad}, duration=2, frames=50)
        with self.assertRaisesRegex(ValueError, "cannot lie flat"):
            annotations.clean_document(document(zone), duration=2, frames=50)
        with self.assertRaisesRegex(ValueError, "true or false"):
            annotations.clean_document(document(ring(style={"flat": "yes"})), duration=2, frames=50)

    def test_no_animation_stores_no_animation_settings(self):
        clean = annotations.clean_document(document(ring(show={"from": 0, "to": 1, "animSeconds": 2, "ease": "linear"})),
                                           duration=2, frames=50)
        self.assertEqual(clean["items"][0]["show"], {"from": 0, "to": 1, "animate": "none"})

    def test_too_many_drawings_are_refused(self):
        many = [ring(f"r{i}") for i in range(annotations.MAX_ITEMS + 1)]
        with self.assertRaises(ValueError):
            annotations.clean_document(document(*many), duration=2, frames=50)


def make_clip(path: Path, seconds=2, fps=25, size="320x240"):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:rate={fps}:duration={seconds}", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True)
    return path


class EditorApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.data)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.project = self.server.match_store.create("Editor test")
        self.preview = make_clip(self.data / "previews" / "preview-1.mp4")
        self.server.media_files["previewtoken"] = self.preview

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

    def annotate(self):
        status, result = self.call("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken",
                                                          "name": "Saka 34'.mp4"})
        self.assertEqual(status, 201, result)
        return result["clip"]

    def test_annotate_copies_the_clip_into_the_project_and_describes_it(self):
        clip = self.annotate()
        self.assertEqual(clip["name"], "Saka 34'")
        self.assertEqual((clip["fps"], clip["width"], clip["height"], clip["frames"]), (25, 320, 240, 50))
        copied = self.data / "projects" / self.project["id"] / "clips" / f"{clip['id']}.mp4"
        self.assertEqual(copied.read_bytes(), self.preview.read_bytes())
        self.preview.unlink()  # the scratch clip may be pruned; the copy stays
        status, opened = self.call(f"/api/editor/{self.project['id']}/{clip['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(opened["annotations"], annotations.empty_document())
        self.assertFalse(opened["changed"])
        with urlopen(self.base + opened["url"], timeout=5) as response:
            self.assertEqual(response.read(), copied.read_bytes())

    def test_drawings_save_and_reopen(self):
        clip = self.annotate()
        path = f"/api/editor/{self.project['id']}/{clip['id']}"
        status, saved = self.call(path, {"annotations": document(ring())})
        self.assertEqual(status, 200, saved)
        status, opened = self.call(path)
        self.assertEqual(opened["annotations"]["items"][0]["id"], "r1")
        on_disk = self.data / "projects" / self.project["id"] / "annotations" / f"{clip['id']}.json"
        self.assertEqual(json.loads(on_disk.read_text())["items"][0]["kind"], "ring")
        self.assertFalse(list(on_disk.parent.glob("saving-*")))  # atomic write left nothing behind

    def test_freezes_save_and_reopen(self):
        clip = self.annotate()
        path = f"/api/editor/{self.project['id']}/{clip['id']}"
        value = {"version": 1, "items": [ring(show={"from": 0.5, "to": 4.5, "animate": "grow", "animSeconds": 0.3,
                                                     "ease": "ease-out"})],
                 "freezes": [{"atFrame": 12, "seconds": 2.75}]}
        status, saved = self.call(path, {"annotations": value})
        self.assertEqual(status, 200, saved)
        opened = self.call(path)[1]["annotations"]
        self.assertEqual(opened["freezes"], [{"atFrame": 12, "seconds": 2.75}])
        self.assertEqual(opened["items"][0]["show"]["animate"], "grow")
        status, _ = self.call(path, {"annotations": {**value, "freezes": [{"atFrame": 50, "seconds": 1}]}})  # frame 51 of 50
        self.assertEqual(status, 400)

    def test_the_pitch_saves_and_reopens(self):
        clip = self.annotate()
        path = f"/api/editor/{self.project['id']}/{clip['id']}"
        marks = [{"id": mark, "at": at} for mark, at in
                 (("half-far", [0.1, 0.3]), ("box-r-far", [0.3, 0.4]), ("box-r-near", [0.5, 0.3]), ("spot-r", [0.7, 0.4]))]
        value = {**document(ring(style={"flat": True})), "pitch": {"keys": [{"frame": 3, "pairs": marks}]}}
        status, saved = self.call(path, {"annotations": value})
        self.assertEqual(status, 200, saved)
        opened = self.call(path)[1]["annotations"]
        self.assertEqual(opened["pitch"], value["pitch"])
        self.assertTrue(opened["items"][0]["style"]["flat"])

    def test_bad_drawings_leave_the_saved_ones_untouched(self):
        clip = self.annotate()
        path = f"/api/editor/{self.project['id']}/{clip['id']}"
        self.call(path, {"annotations": document(ring())})
        status, result = self.call(path, {"annotations": document(ring(kind="laser"))})
        self.assertEqual(status, 400)
        self.assertIn("Unknown drawing type", result["error"])
        self.assertEqual(self.call(path)[1]["annotations"]["items"][0]["kind"], "ring")

    def test_a_changed_video_is_reported(self):
        clip = self.annotate()
        copied = self.data / "projects" / self.project["id"] / "clips" / f"{clip['id']}.mp4"
        with copied.open("ab") as handle:
            handle.write(b"\0")
        self.assertTrue(self.call(f"/api/editor/{self.project['id']}/{clip['id']}")[1]["changed"])

    def test_only_watched_clips_can_be_annotated(self):
        outside = make_clip(self.data / "elsewhere" / "private.mp4")
        self.server.media_files["outside"] = outside
        for media in ("outside", "missing", ""):
            status, result = self.call("/api/editor/clips", {"project_id": self.project["id"], "media": media})
            self.assertEqual(status, 404, media)
        self.assertFalse((self.data / "projects" / self.project["id"] / "clips").exists())

    def sessions(self):
        status, result = self.call(f"/api/editor-sessions/{self.project['id']}")
        self.assertEqual(status, 200, result)
        return result["sessions"]

    def test_one_clip_gets_its_own_session_and_several_can_share_one(self):
        first = self.annotate()
        status, result = self.call("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken",
                                                          "name": "Odegaard 51'.mp4", "session_name": "Pressing"})
        self.assertEqual(status, 201, result)
        shared = result["session"]["id"]
        status, again = self.call("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken",
                                                         "name": "Rice 70'.mp4", "session_id": shared})
        self.assertEqual(status, 201, again)
        self.assertEqual(again["session"]["id"], shared)
        listed = {session["name"]: session for session in self.sessions()}
        self.assertEqual(set(listed), {"Saka 34'", "Pressing"})
        self.assertEqual([clip["name"] for clip in listed["Pressing"]["clips"]], ["Odegaard 51'", "Rice 70'"])
        self.assertEqual(listed["Saka 34'"]["clips"][0]["id"], first["id"])

    def test_clips_saved_before_sessions_appear_as_their_own_session(self):
        clip = self.annotate()
        (self.data / "projects" / self.project["id"] / "sessions.json").unlink()
        self.call(f"/api/editor/{self.project['id']}/{clip['id']}", {"annotations": document(ring())})
        [session] = self.sessions()
        self.assertEqual(session["clips"][0]["id"], clip["id"])
        self.assertEqual(session["clips"][0]["drawings"], 1)

    def test_sessions_rename_and_remove_clips_to_the_trash(self):
        clip = self.annotate()
        [session] = self.sessions()
        base = f"/api/editor-sessions/{self.project['id']}"
        status, result = self.call(base + "/rename", {"session_id": session["id"], "name": "  Build-up   play "})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["sessions"][0]["name"], "Build-up play")
        self.assertEqual(self.call(base + "/rename", {"session_id": session["id"], "name": " "})[0], 400)
        status, result = self.call(base + "/delete", {"session_id": session["id"]})
        self.assertEqual((status, result["sessions"]), (200, []))
        project = self.data / "projects" / self.project["id"]
        self.assertFalse((project / "clips" / f"{clip['id']}.mp4").exists())
        self.assertEqual(len(list((project / "editor-trash").glob(f"*-{clip['id']}/clip.mp4"))), 1)
        self.assertEqual(self.call(f"/api/editor/{self.project['id']}/{clip['id']}")[0], 404)

    def test_removing_one_clip_keeps_the_rest_of_its_session(self):
        self.annotate()
        status, result = self.call("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken",
                                                          "name": "Second.mp4", "session_name": "Pair"})
        second = result["clip"]
        self.call("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken",
                                        "name": "Third.mp4", "session_id": result["session"]["id"]})
        status, result = self.call(f"/api/editor-sessions/{self.project['id']}/remove-clip", {"clip_id": second["id"]})
        self.assertEqual(status, 200, result)
        pair = next(session for session in result["sessions"] if session["name"] == "Pair")
        self.assertEqual([clip["name"] for clip in pair["clips"]], ["Third"])

    def test_bad_session_requests_are_refused(self):
        self.annotate()
        base = f"/api/editor-sessions/{self.project['id']}"
        cases = [(base + "/rename", {"session_id": "../x", "name": "A"}, 400),
                 (base + "/delete", {"session_id": "s" + "0" * 16}, 404),
                 (base + "/remove-clip", {"clip_id": "../../x"}, 400),
                 (base + "/remove-clip", {"clip_id": "0" * 32}, 404),
                 (base + "/explode", {"session_id": "s" + "0" * 16}, 400),
                 ("/api/editor-sessions/no-such-project/delete", {"session_id": "s" + "0" * 16}, 404),
                 ("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken", "session_id": "nope"}, 400),
                 ("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken",
                                        "session_id": "s" + "0" * 16}, 404)]
        for path, payload, expected in cases:
            self.assertEqual(self.call(path, payload)[0], expected, (path, payload))
        self.assertEqual(self.call("/api/editor-sessions/..%2F..%2Fx")[0], 404)
        self.assertEqual(len(self.sessions()), 1)

    def test_requests_cannot_reach_outside_the_project(self):
        clip = self.annotate()
        status, _ = self.call("/api/editor/clips", {"project_id": "no-such-project", "media": "previewtoken"})
        self.assertEqual(status, 400)
        for path in (f"/api/editor/..%2F..%2Fx/{clip['id']}", f"/api/editor/{self.project['id']}/..",
                     f"/api/editor/{self.project['id']}/{'0' * 32}", f"/api/editor/{self.project['id']}"):
            status, _ = self.call(path)
            self.assertIn(status, (400, 404), path)

    def test_editor_screenshots_save_as_jpeg(self):
        folder = self.data / "exports"
        self.server.default_export_dir = folder
        request = Request(self.base + "/api/images/save", data=b"\xff\xd8\xff\xe0fakejpeg", method="POST",
                          headers={"Content-Type": "application/octet-stream", "X-File-Name": "Frame.jpg"})
        with urlopen(request, timeout=5) as response:
            saved = json.loads(response.read())["saved"]
        self.assertEqual(saved["name"], "Frame.jpg")
        self.assertTrue((folder / "Frame.jpg").is_file())


class TimelineTests(unittest.TestCase):
    """The engine's rules match the browser's: both are checked against one fixture."""

    def setUp(self):
        self.cases = json.loads((Path(__file__).parent / "fixtures" / "timeline_cases.json").read_text(encoding="utf-8"))

    def test_output_time_maps_to_source_frames_through_freezes(self):
        clip, freezes = self.cases["clip"], self.cases["freezes"]
        self.assertAlmostEqual(timeline.total_seconds(clip["duration"], freezes), self.cases["total"])
        for case in self.cases["mapping"]:
            with self.subTest(t=case["t"]):
                at = timeline.output_to_source(case["t"], clip["fps"], clip["duration"], clip["frames"], freezes)
                self.assertEqual((at["frame"], at["freeze"]), (case["frame"], case["freeze"]))

    def test_animation_progress(self):
        for case in self.cases["animation"]:
            with self.subTest(item=case["item"], t=case["t"]):
                state = timeline.animation(case["item"], case["t"])
                if case["state"] is None:
                    self.assertIsNone(state)
                    continue
                for key, expected in case["state"].items():
                    if expected is None:
                        self.assertIsNone(state[key])
                    else:
                        self.assertAlmostEqual(state[key], expected, places=6, msg=key)


class ProbeTests(unittest.TestCase):
    def test_reads_fractional_frame_rates(self):
        with tempfile.TemporaryDirectory() as name:
            clip = make_clip(Path(name) / "ntsc.mp4", seconds=1, fps="30000/1001", size="64x48")
            info = probe_video(clip, _find_ffmpeg())
        self.assertAlmostEqual(info["fps"], 29.97, places=2)
        self.assertEqual((info["width"], info["height"]), (64, 48))


if __name__ == "__main__":
    unittest.main()
