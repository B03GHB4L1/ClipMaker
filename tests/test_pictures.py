"""Picture inserts (docs/CODING_AND_PITCH_PLAN.md, section I): the project's picture library,
the engine's rules for an insert, and the server routes."""
import io
import json
import struct
import tempfile
import threading
import unittest
import zlib
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

from app.telestration import annotations, pictures
from packaging.clipmaker_api_server import create_server

from tests.test_annotations import make_clip


def encoded(size=(64, 48), colour=(200, 30, 30), format="PNG", mode="RGB"):
    output = io.BytesIO()
    Image.new(mode, size, colour if mode == "RGB" else colour + (128,)).save(output, format)
    return output.getvalue()


def picture_freeze(picture_id, **background):
    return {"atFrame": 10, "seconds": 3, "background": {"kind": "picture", "id": picture_id, "fit": "contain",
                                                         "colour": "#1F6F3A", **background}}


class EngineRuleTests(unittest.TestCase):
    def clean(self, freeze):
        return annotations.clean_document({"version": 1, "items": [], "freezes": [freeze]}, duration=2, frames=50)

    def test_a_picture_insert_keeps_its_settings(self):
        clean = self.clean(picture_freeze("a" * 32))
        self.assertEqual(clean["freezes"][0]["background"],
                         {"kind": "picture", "id": "a" * 32, "fit": "contain", "colour": "#1f6f3a"})

    def test_bad_picture_settings_are_refused(self):
        for bad, message in ((picture_freeze("not-an-id"), "project's pictures"),
                             (picture_freeze("../" + "a" * 29), "project's pictures"),
                             (picture_freeze("a" * 32, fit="stretch"), "fitted"),
                             (picture_freeze("a" * 32, colour="green"), "colour"),
                             (picture_freeze("a" * 32, path="C:/x.png"), "Unknown picture setting")):
            with self.subTest(bad=str(bad)[:80]), self.assertRaisesRegex(ValueError, message):
                self.clean(bad)

    def test_drawings_can_be_placed_on_a_picture_insert(self):
        item = {"id": "r1", "kind": "ring", "points": [[0.4, 0.7]], "geometry": {"rx": 0.03, "ry": 0.01},
                "style": {"stroke": "#ffd400", "width": 3}, "show": {"from": 0.4, "to": 0.5}, "on": 10}
        clean = annotations.clean_document({"version": 1, "items": [item], "freezes": [picture_freeze("b" * 32)]},
                                           duration=2, frames=50)
        self.assertEqual(clean["items"][0]["on"], 10)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.folder = self.project / "pictures"

    def tearDown(self):
        self.temporary.cleanup()

    def test_pictures_are_re_encoded_as_clean_pngs(self):
        for format, name in (("PNG", "Line-up.png"), ("JPEG", "Photo.jpg"), ("WEBP", "Graphic.webp")):
            record = pictures.add(self.folder, encoded(format=format), name)
            self.assertEqual((record["width"], record["height"]), (64, 48))
            saved = (self.folder / f"{record['id']}.png").read_bytes()
            self.assertTrue(saved.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(Image.open(io.BytesIO(saved)).size, (64, 48))
        self.assertEqual({row["name"] for row in pictures.listing(self.folder)}, {"Line-up", "Photo", "Graphic"})
        self.assertFalse(list(self.folder.glob("saving-*")))  # atomic writes left nothing behind

    def test_what_a_picture_carries_besides_pixels_is_dropped(self):
        original = io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(original, "PNG", pnginfo=_text_info("Author", "someone"))
        record = pictures.add(self.folder, original.getvalue(), "x.png")
        saved = Image.open(self.folder / f"{record['id']}.png")
        self.assertNotIn("Author", saved.info)

    def test_transparency_is_kept(self):
        record = pictures.add(self.folder, encoded(mode="RGBA"), "Overlay.png")
        self.assertEqual(Image.open(self.folder / f"{record['id']}.png").mode, "RGBA")

    def test_files_that_are_not_pictures_or_are_too_big_are_refused(self):
        wide = encoded(size=(pictures.MAX_SIDE + 1, 2))
        for data, message in ((b"", "under 20 MB"), (b"MZ\x90\x00" + b"0" * 200, "Only PNG, JPEG and WebP"),
                              (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "Only PNG, JPEG and WebP"),
                              (encoded(format="GIF"), "Only PNG, JPEG and WebP"),
                              (wide, "pixels on a side"), (b"0" * (pictures.MAX_BYTES + 1), "under 20 MB")):
            with self.subTest(message=message, size=len(data)), self.assertRaisesRegex(ValueError, message):
                pictures.add(self.folder, data, "bad.png")
        self.assertEqual(pictures.listing(self.folder), [])

    def test_a_picture_that_is_larger_than_it_claims_is_not_decoded(self):
        # A PNG header claiming 60,000 x 60,000 pixels: refused from the header, not by running out of memory.
        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

        header = struct.pack(">IIBBBBB", 60000, 60000, 8, 2, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")
        with self.assertRaisesRegex(ValueError, "pixels on a side"):
            pictures.add(self.folder, png, "huge.png")

    def test_ids_cannot_name_other_files(self):
        for bad in ("../x", "..\\x", "a" * 31, "A" * 32, "", "a" * 32 + ".png"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pictures.file_of(self.folder, bad)

    def test_a_picture_in_use_cannot_be_deleted(self):
        record = pictures.add(self.folder, encoded(), "Line-up.png")
        notes = self.project / "annotations"
        notes.mkdir()
        (notes / ("c" * 32 + ".json")).write_text(json.dumps({"version": 1, "items": [],
                                                                "freezes": [picture_freeze(record["id"])]}))
        with self.assertRaisesRegex(ValueError, "Remove the insert first"):
            pictures.remove(self.project, record["id"])
        self.assertIsNotNone(pictures.file_of(self.folder, record["id"]))
        (notes / ("c" * 32 + ".json")).write_text(json.dumps({"version": 1, "items": [], "freezes": []}))
        pictures.remove(self.project, record["id"])
        self.assertEqual(pictures.listing(self.folder), [])
        with self.assertRaises(LookupError):
            pictures.remove(self.project, record["id"])


def _text_info(key, value):
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text(key, value)
    return info


class PictureApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.data)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.project = self.server.match_store.create("Picture test")
        self.preview = make_clip(self.data / "previews" / "preview-1.mp4")
        self.server.media_files["previewtoken"] = self.preview

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def call(self, path, payload=None, raw=None, name="Line-up.png"):
        data = json.dumps(payload).encode("utf-8") if payload is not None else raw
        headers = {"Content-Type": "application/octet-stream" if raw is not None else "application/json"}
        if raw is not None:
            headers["X-File-Name"] = name
        request = Request(self.base + path, data=data, method="POST" if data is not None else "GET", headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def add(self, data=None, name="Line-up.png"):
        return self.call(f"/api/projects/{self.project['id']}/pictures", raw=encoded() if data is None else data, name=name)

    def test_upload_list_fetch_and_delete(self):
        status, added = self.add(name="Line-up.png")
        self.assertEqual(status, 201, added)
        picture = added["picture"]
        self.assertEqual((picture["name"], picture["width"], picture["height"]), ("Line-up", 64, 48))
        status, listed = self.call(f"/api/projects/{self.project['id']}/pictures")
        self.assertEqual([row["id"] for row in listed["pictures"]], [picture["id"]])
        with urlopen(self.base + picture["url"], timeout=5) as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(Image.open(io.BytesIO(response.read())).size, (64, 48))
        status, left = self.call(f"/api/projects/{self.project['id']}/pictures/delete", {"id": picture["id"]})
        self.assertEqual((status, left["pictures"]), (200, []))
        status, _ = self.call(f"/api/projects/{self.project['id']}/pictures/delete", {"id": picture["id"]})
        self.assertEqual(status, 404)

    def test_bad_uploads_and_unknown_projects_are_refused(self):
        self.assertEqual(self.add(b"not a picture")[0], 400)
        self.assertEqual(self.add(b"")[0], 400)
        for path in ("/api/projects/no-such-project/pictures", "/api/projects/..%2Fx/pictures"):
            self.assertEqual(self.call(path, raw=encoded())[0], 400, path)
            self.assertEqual(self.call(path)[0], 400, path)
        self.assertEqual(self.call(f"/api/projects/{self.project['id']}/pictures/delete", {"id": "../x"})[0], 400)
        self.assertEqual(self.call(f"/api/projects/{self.project['id']}/pictures/delete", {"id": "a" * 32, "path": "x"})[0], 400)

    def test_a_clip_with_a_picture_insert_saves_and_reopens_and_the_picture_stays(self):
        status, clip = self.call("/api/editor/clips", {"project_id": self.project["id"], "media": "previewtoken", "name": "Clip"})
        clip = clip["clip"]
        picture = self.add()[1]["picture"]
        path = f"/api/editor/{self.project['id']}/{clip['id']}"
        value = {"version": 1, "items": [], "freezes": [picture_freeze(picture["id"])]}
        status, saved = self.call(path, {"annotations": value})
        self.assertEqual(status, 200, saved)
        reopened = self.call(path)[1]["annotations"]
        self.assertEqual(reopened["freezes"][0]["background"]["id"], picture["id"])
        # Deleting a picture an insert shows is refused, and it is still there afterwards.
        status, refused = self.call(f"/api/projects/{self.project['id']}/pictures/delete", {"id": picture["id"]})
        self.assertEqual(status, 400)
        self.assertIn("Remove the insert first", refused["error"])
        self.assertEqual(len(self.call(f"/api/projects/{self.project['id']}/pictures")[1]["pictures"]), 1)
        # Saving an insert of a picture the project does not have is refused.
        gone = {"version": 1, "items": [], "freezes": [picture_freeze("d" * 32)]}
        status, refused = self.call(path, {"annotations": gone})
        self.assertEqual(status, 400)
        self.assertIn("not in the project", refused["error"])
        # Once the insert is removed the picture can go.
        self.call(path, {"annotations": {"version": 1, "items": [], "freezes": []}})
        self.assertEqual(self.call(f"/api/projects/{self.project['id']}/pictures/delete", {"id": picture["id"]})[0], 200)


if __name__ == "__main__":
    unittest.main()
