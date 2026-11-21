"""Coding milestone C3 (docs/CODING_AND_PITCH_PLAN.md): tags, linked codes,
code panels (templates) and squad lists, from validation to the event table
Filter reads and the HTTP API."""
from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.clipmaker_core import INTENT_FLAG_TO_BOOL_COL, read_csv_safe
from app.coding import store, templates, to_events
from packaging.clipmaker_api_server import FILTER_QUALIFIERS, create_server

MARKERS = {"1H": "0:00:05", "2H": "0:00:40"}


def event(event_id, t, code="goal", team="home", **extra):
    return {"id": event_id, "code": code, "team": team, "src": "1H", "t": t, **extra}


def single_video(_period):
    return "match.mp4"


class TemplateValidationTests(unittest.TestCase):
    def test_built_ins_are_valid_and_the_match_panel_keeps_c1_codes(self):
        self.assertEqual({item["id"] for item in templates.BUILT_INS}, {"match", "set-pieces", "training", "keeper"})
        for template in templates.BUILT_INS:
            self.assertEqual(templates.clean(copy.deepcopy(template)), template, template["id"])
        match = {code["id"] for code in templates.built_in("match")["codes"]}
        self.assertTrue({"goal", "shot-on", "shot-off", "corner", "possession", "build-up", "press", "transition"} <= match)
        self.assertEqual(store.CODE_IDS, match)

    def test_tag_flags_are_filter_qualifier_columns(self):
        self.assertTrue(set(templates.FLAGS) <= set(INTENT_FLAG_TO_BOOL_COL.values()))
        self.assertTrue(set(templates.FLAGS) <= {definition[1] for definition in FILTER_QUALIFIERS})

    def test_unknown_fields_are_refused_at_every_level(self):
        base = templates.built_in("training")
        for where in ("template", "code", "tag"):
            value = copy.deepcopy(base)
            target = {"template": value, "code": value["codes"][0], "tag": value["tags"][0]}[where]
            target["path"] = "C:/Windows"
            with self.assertRaisesRegex(ValueError, "unknown field"):
                templates.clean(value)

    def test_keys_colours_links_and_text_are_checked(self):
        def broken(change):
            value = templates.built_in("match")
            change(value)
            with self.assertRaises(ValueError):
                templates.clean(value)

        broken(lambda v: v["codes"][0].update(key="h"))              # H chooses the team
        broken(lambda v: v["codes"][0].update(key="1"))              # numbers name players
        broken(lambda v: v["codes"][1].update(key=v["codes"][0]["key"]))  # used twice
        broken(lambda v: v["tags"][0].update(key="l"))               # tags are Shift+letter
        broken(lambda v: v["codes"][0].update(colour="red"))
        broken(lambda v: v["codes"][0].update(label="<script>"))
        broken(lambda v: v["codes"][0].update(before=61))
        broken(lambda v: v["codes"][0].update(stops=["goal"]))       # only intervals can be stopped
        broken(lambda v: v["codes"][0].update(starts=[{"code": "possession", "team": "both"}]))
        broken(lambda v: v["codes"][0].update(tags=["no-such-tag"]))
        broken(lambda v: v["tags"][0].update(flag="is_anything"))
        broken(lambda v: v.update(version=2))
        broken(lambda v: v.update(codes=[]))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.library = templates.TemplateLibrary(Path(self.temporary.name) / "code-templates")

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_never_replaces_a_built_in_or_another_panel(self):
        mine = {**templates.built_in("match"), "name": "Match: two teams"}
        first = self.library.save(mine)
        second = self.library.save(mine)
        self.assertNotIn(first["id"], templates.BUILT_IN_IDS)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len([item for item in self.library.list() if not item["builtin"]]), 2)
        replaced = self.library.save({**first, "name": "Renamed"}, replace=True)
        self.assertEqual(replaced["id"], first["id"])
        self.assertEqual(self.library.get(first["id"])["name"], "Renamed")

    def test_delete_moves_to_trash_and_built_ins_stay(self):
        saved = self.library.save({**templates.built_in("keeper"), "name": "Our keeper"})
        with self.assertRaises(ValueError):
            self.library.delete("keeper")
        self.library.delete(saved["id"])
        self.assertNotIn(saved["id"], {item["id"] for item in self.library.list()})
        self.assertEqual(len(list((self.library.folder / "trash").glob("*.json"))), 1)
        with self.assertRaises(ValueError):
            self.library.delete("../projects")

    def test_a_damaged_file_is_skipped_not_overwritten(self):
        self.library.folder.mkdir(parents=True)
        (self.library.folder / "broken.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(len(self.library.list()), len(templates.BUILT_INS))
        self.assertEqual((self.library.folder / "broken.json").read_text(encoding="utf-8"), "{not json")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_tags_and_players_are_saved_and_checked(self):
        document = store.apply(self.folder, {"add": [event("c000001", 10, code="shot-on", tags=["left", "header"], player=9)]})
        self.assertEqual(document["events"][0]["tags"], ["left", "header"])
        self.assertEqual(document["events"][0]["player"], 9)
        for bad in ({"tags": ["left", "right"]}, {"tags": ["nope"]}, {"player": 100}, {"player": True}):
            with self.assertRaises(ValueError):
                store.apply(self.folder, {"update": [{"id": "c000001", **bad}]})
        cleared = store.apply(self.folder, {"update": [{"id": "c000001", "tags": [], "player": None}]})
        self.assertNotIn("tags", cleared["events"][0])
        self.assertNotIn("player", cleared["events"][0])

    def test_a_panel_lacking_used_codes_is_refused_and_nothing_changes(self):
        store.apply(self.folder, {"add": [event("c000001", 10, code="possession", end=20)]})
        with self.assertRaisesRegex(ValueError, "this panel does not have"):
            store.apply(self.folder, {"panel": templates.built_in("keeper")})
        self.assertEqual(store.read(self.folder)["panel"]["id"], "match")
        store.apply(self.folder, {"delete": ["c000001"]})
        document = store.apply(self.folder, {"panel": templates.built_in("keeper"), "add": [event("c000002", 5, code="claim")]})
        self.assertEqual(document["panel"]["id"], "keeper")
        self.assertEqual(store.lead(document, "claim"), (6, 3))
        with self.assertRaises(ValueError):
            store.apply(self.folder, {"add": [event("c000003", 5, code="goal")]})  # not on this panel

    def test_squads_are_checked(self):
        document = store.apply(self.folder, {"squads": {"home": [{"number": 9, "name": "Saka"}, {"number": 1, "name": ""}], "away": []}})
        self.assertEqual([player["number"] for player in document["squads"]["home"]], [1, 9])
        for bad in ({"home": [{"number": 9, "name": "A"}, {"number": 9, "name": "B"}]}, {"home": [{"number": 120, "name": "A"}]},
                    {"home": [{"number": 9, "name": "<b>"}]}, {"third": []}, {"home": [{"number": 9, "age": 20}]}):
            with self.assertRaises(ValueError):
                store.apply(self.folder, {"squads": bad})

    def test_documents_from_c2_still_open_with_the_match_panel(self):
        (self.folder / store.FILE_NAME).write_text(json.dumps({"version": 1, "events": [event("c000001", 3)], "leads": {}}), encoding="utf-8")
        document = store.read(self.folder)
        self.assertEqual(document["panel"]["id"], "match")
        self.assertEqual(document["squads"], {"home": [], "away": []})


class TableTests(unittest.TestCase):
    def test_tags_players_outcomes_and_flags_reach_the_event_table(self):
        document = store.empty()
        document["squads"] = {"home": [{"number": 9, "name": "Saka"}], "away": []}
        document["events"] = [
            event("c000001", 10, code="shot-on", tags=["header", "unsuccessful"], player=9),
            event("c000002", 12, code="corner", team="away", tags=["set-piece"], player=4),
        ]
        table, _ = to_events.rows(document, MARKERS, single_video, "Reims", "Lens")
        shot, corner = table
        self.assertEqual((shot["playerName"], shot["shirt"], shot["outcomeType"]), ("Saka", 9, "Unsuccessful"))
        self.assertEqual(shot["tags"], "Header; Unsuccessful")
        self.assertIs(shot["is_header"], True)
        self.assertIs(corner["is_header"], False)
        self.assertEqual(corner["playerName"], "#4")

        with tempfile.TemporaryDirectory() as folder:
            path = to_events.write_csv(Path(folder) / "coded.csv", table)
            frame = read_csv_safe(str(path))
            self.assertEqual(frame.loc[frame["is_header"] == True, "type"].tolist(), ["SavedShot"])  # noqa: E712


class TemplatesApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.root)
        self.server.default_export_dir = str(self.root / "exports")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def refused(self, path, body):
        with self.assertRaises(HTTPError) as caught:
            self.request(path, body)
        self.assertEqual(caught.exception.code, 400)
        return json.loads(caught.exception.read())["error"]

    def test_save_import_list_export_and_delete(self):
        listed = self.request("/api/code-templates")["templates"]
        self.assertEqual([item["id"] for item in listed if item["builtin"]], ["match", "set-pieces", "training", "keeper"])
        saved = self.request("/api/code-templates", {"template": {**templates.built_in("set-pieces"), "name": "Our set pieces"}})
        self.assertEqual(saved["template"]["id"], "our-set-pieces")
        self.assertTrue((self.root / "code-templates" / "our-set-pieces.json").is_file())

        self.assertIn("unknown field", self.refused("/api/code-templates", {"template": {**templates.built_in(), "file": "x"}}))
        self.refused("/api/code-templates", {"template": templates.built_in(), "path": "C:/"})
        self.refused("/api/code-templates/delete", {"id": "match"})

        exported = self.request("/api/code-templates/export", {"template": saved["template"]})["saved"]
        file = self.root / "exports" / exported["name"]
        self.assertEqual(json.loads(file.read_text(encoding="utf-8"))["name"], "Our set pieces")
        self.assertEqual(Path(exported["folder"]), file.parent)

        after = self.request("/api/code-templates/delete", {"id": "our-set-pieces"})["templates"]
        self.assertNotIn("our-set-pieces", {item["id"] for item in after})

    def test_project_panel_squads_and_linked_codes_through_filter(self):
        video = self.root / "match.mp4"
        video.write_bytes(b"not decoded by these requests")
        project = self.request("/api/projects", {})["project"]
        project_id = project["id"]
        self.request(f"/api/projects/{project_id}", {"video_path": str(video), "markers": MARKERS,
                                                     "home_team": "Reims", "away_team": "Lens"})
        codes = f"/api/projects/{project_id}/codes"
        first = self.request(codes)
        self.assertEqual(first["panel"]["id"], "match")
        self.assertEqual(first["codes"], first["panel"]["codes"])
        result = self.request(codes, {"squads": {"home": [{"number": 9, "name": "Saka"}], "away": []}, "add": [
            event("c000001", 20, code="shot-on", tags=["big-chance"], player=9),
            event("c000002", 34, code="shot-off", team="away", tags=["successful"])]})
        self.assertEqual(result["squads"]["home"][0]["name"], "Saka")
        # A tag's flag works with Filter's qualifier for that column (Big chances is scoped to shots),
        # and a tag's outcome with Successful.
        plan = self.request("/api/previews", {"match_id": project_id, "options": {"big_chances_only": True}})
        self.assertEqual(len(plan["windows"]), 1)
        plan = self.request("/api/previews", {"match_id": project_id, "options": {"successful_only": True}})
        self.assertIn("MissedShot", json.dumps(plan["windows"]))  # the shot off target tagged Successful
        plan = self.request("/api/previews", {"match_id": project_id, "options": {"unsuccessful_only": True}})
        self.assertEqual(plan["windows"], [])
        self.assertIn("Saka", json.dumps(self.request("/api/filter-options", {"match_id": project_id})))

        self.assertIn("this panel does not have", self.refused(codes, {"panel": templates.built_in("keeper")}))
        self.request(codes, {"delete": ["c000001", "c000002"]})
        switched = self.request(codes, {"panel": templates.built_in("keeper")})
        self.assertEqual([code["id"] for code in switched["codes"]][:2], ["save", "claim"])
        self.assertIn("unknown field", self.refused(codes, {"panel": {**templates.built_in(), "extra": 1}}))


if __name__ == "__main__":
    unittest.main()
