"""Saved matches live in a library apart from projects (matches/<id>/), and survive projects."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from packaging.clipmaker_api_server import MatchStore, create_server, remove_unused_imports

CSV = b"minute,second,type,team,period\n1,0,Pass,Home,FirstHalf\n2,0,Goal,Away,FirstHalf\n"


def old_project(root: Path, project_id: str, **fields) -> Path:
    """A project as earlier versions saved it: one match, its files inside the project folder."""
    folder = root / "projects" / project_id
    (folder / "match-data").mkdir(parents=True)
    (folder / "imports").mkdir()
    csv = folder / "match-data" / "events.csv"
    csv.write_bytes(CSV)
    copy = folder / "imports" / "copy.mp4"
    copy.write_bytes(b"copy")
    (folder / "coded_events.json").write_text('{"version": 1, "events": []}', encoding="utf-8")
    value = {"id": project_id, "schema_version": 1, "project_name": "Old project", "home_team": "Home",
             "away_team": "Away", "csv_path": str(csv), "source": "whoscored", "source_url": "https://x/1",
             "video_path": str(copy), "period_videos": {"2H": str(folder / "imports" / "copy.mp4")},
             "markers": {"1H": "00:02:00"}, "filter_settings": {"filter_types": ["Goal"]},
             "preview_windows": [{"start": 1}], "updated_at": "2026-01-01T00:00:00+00:00", **fields}
    (folder / "project.json").write_text(json.dumps(value), encoding="utf-8")
    return folder


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_an_old_project_becomes_a_project_that_uses_a_saved_match(self):
        old_project(self.root, "p1")
        store = MatchStore(self.root)
        project = store.get("p1")
        target = self.root / "matches" / "p1"
        self.assertEqual(project["match_ids"], ["p1"])
        self.assertEqual(project["match_id"], "p1")
        self.assertEqual(project["project_name"], "Old project")
        self.assertEqual(project["filter_settings"], {"filter_types": ["Goal"]})
        self.assertEqual(project["preview_windows"], [{"start": 1}])
        self.assertEqual(Path(project["csv_path"]), target / "match-data" / "events.csv")
        self.assertEqual(Path(project["csv_path"]).read_bytes(), CSV)
        self.assertEqual(Path(project["video_path"]), target / "imports" / "copy.mp4")
        self.assertEqual(Path(project["period_videos"]["2H"]), target / "imports" / "copy.mp4")
        self.assertTrue((target / "coded_events.json").is_file())
        self.assertFalse((self.root / "projects" / "p1" / "match-data").exists())
        on_disk = json.loads((self.root / "projects" / "p1" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schema_version"], 2)
        self.assertNotIn("csv_path", on_disk)  # match fields now live in the match only
        self.assertEqual(on_disk["updated_at"], "2026-01-01T00:00:00+00:00")  # the list keeps its order

    def test_migration_finishes_after_a_crash_part_way(self):
        folder = old_project(self.root, "p1")
        target = self.root / "matches" / "p1"
        target.mkdir(parents=True)
        (folder / "match-data").rename(target / "match-data")  # files moved, nothing else written yet
        project = MatchStore(self.root).get("p1")
        self.assertEqual(Path(project["csv_path"]), target / "match-data" / "events.csv")
        self.assertTrue(Path(project["csv_path"]).is_file())

    def test_a_data_folder_copied_from_elsewhere_still_finds_its_files(self):
        # Paths name the old computer's data folder; the files are here under the same projects/<id>/ tail.
        old_project(self.root, "p1", csv_path=r"D:\old pc\VizorPlay\projects\p1\match-data\events.csv")
        project = MatchStore(self.root).get("p1")
        self.assertEqual(Path(project["csv_path"]), self.root / "matches" / "p1" / "match-data" / "events.csv")

    def test_a_trashed_project_finds_files_named_by_its_old_folder(self):
        folder = old_project(self.root, "p9")
        trash = self.root / "project-trash" / "p9-20260101T000000000000"
        trash.parent.mkdir()
        folder.rename(trash)  # its paths still say projects/p9/...
        [match] = MatchStore(self.root).matches()
        self.assertEqual(Path(match["csv_path"]).read_bytes(), CSV)

    def test_videos_outside_the_project_keep_their_paths(self):
        video = self.root / "elsewhere" / "match.mp4"
        video.parent.mkdir()
        video.write_bytes(b"v")
        old_project(self.root, "p1", video_path=str(video), period_videos={})
        self.assertEqual(MatchStore(self.root).get("p1")["video_path"], str(video))

    def test_an_empty_old_project_uses_no_match(self):
        folder = self.root / "projects" / "blank"
        folder.mkdir(parents=True)
        (folder / "project.json").write_text(json.dumps({"id": "blank", "project_name": "Untitled project"}))
        store = MatchStore(self.root)
        self.assertEqual(store.get("blank")["match_ids"], [])
        self.assertEqual(store.matches(), [])

    def test_trashed_projects_are_deleted_for_good_and_their_matches_kept(self):
        folder = old_project(self.root, "gone")
        trash = self.root / "project-trash" / "gone-20260101T000000000000"
        trash.parent.mkdir()
        folder.rename(trash)
        store = MatchStore(self.root)
        self.assertEqual(store.list(), [])
        self.assertFalse((self.root / "project-trash").exists())
        [match] = store.matches()
        self.assertEqual(match["home_team"], "Home")
        self.assertEqual(Path(match["csv_path"]).read_bytes(), CSV)
        self.assertTrue(Path(match["csv_path"]).is_relative_to(self.root / "matches"))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = MatchStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_match_fields_go_to_the_match_and_project_fields_to_the_project(self):
        project = self.store.create("Mine")
        saved = self.store.upsert({"id": project["id"], "home_team": "A", "markers": {"1H": "00:00:10"},
                                   "filter_settings": {"x": 1}})
        match = self.store.get_match(saved["match_id"])
        self.assertEqual((match["home_team"], match["markers"]), ("A", {"1H": "00:00:10"}))
        self.assertNotIn("filter_settings", match)
        on_disk = json.loads(self.store.project_path(project["id"]).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["filter_settings"], {"x": 1})
        self.assertNotIn("markers", on_disk)

    def test_requests_cannot_relink_a_project_by_upsert(self):
        project = self.store.upsert({"id": self.store.create()["id"], "home_team": "A"})
        same = self.store.upsert({"id": project["id"], "match_ids": ["other"], "active_match_id": "other",
                                  "match_id": "other"})
        self.assertEqual(same["match_ids"], [project["match_id"]])

    def test_a_kickoff_fixed_once_reaches_every_project_using_the_match(self):
        first = self.store.upsert({"id": self.store.create()["id"], "home_team": "A", "source_url": "u"})
        second = self.store.create()
        self.store.use_match(second["id"], first["match_id"])
        self.store.upsert({"id": second["id"], "preview_windows": [{"start": 2}]})
        self.store.upsert({"id": first["id"], "markers": {"1H": "00:05:00"}})
        other = self.store.get(second["id"])
        self.assertEqual(other["markers"], {"1H": "00:05:00"})
        self.assertEqual(other["preview_windows"], [])  # windows built on the old kick-off are cleared

    def test_deleting_a_match_unlinks_it_from_projects_and_keeps_videos(self):
        video = self.root / "v.mp4"
        video.write_bytes(b"v")
        project = self.store.upsert({"id": self.store.create()["id"], "home_team": "A", "video_path": str(video)})
        self.store.delete_match(project["match_id"])
        after = self.store.get(project["id"])
        self.assertEqual((after["match_ids"], after["match_id"], after["video_path"]), ([], "", ""))
        self.assertEqual(self.store.matches(), [])
        self.assertTrue(video.exists())
        with self.assertRaisesRegex(ValueError, "no longer available"):
            self.store.delete_match(project["match_id"])
        with self.assertRaisesRegex(ValueError, "Invalid match id"):
            self.store.delete_match("../projects")

    def test_unused_copies_count_against_the_library_not_projects(self):
        project = self.store.upsert({"id": self.store.create()["id"], "home_team": "A"})
        imports = self.root / "matches" / project["match_id"] / "imports"
        imports.mkdir()
        used, unused = imports / "used.mp4", imports / "unused.mp4"
        used.write_bytes(b"u")
        unused.write_bytes(b"x")
        self.store.upsert({"id": project["id"], "video_path": str(used)})
        self.store.delete(project["id"])  # the match, and the copy it uses, live on
        self.assertEqual(remove_unused_imports(self.store), 1)
        self.assertTrue(used.exists())
        self.assertFalse(unused.exists())


class SeveralMatchesTests(unittest.TestCase):
    """A project can use several saved matches; Intake edits the active one."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = MatchStore(self.root)
        self.project = self.store.upsert({"id": self.store.create("Two games")["id"], "home_team": "A",
                                          "away_team": "B", "csv_path": self.csv("a.csv")})

    def tearDown(self):
        self.temporary.cleanup()

    def csv(self, name):
        path = self.root / name
        path.write_bytes(CSV)
        return str(path)

    def test_adding_a_match_keeps_the_first_and_makes_the_new_one_active(self):
        added = self.store.add_match(self.project["id"])
        self.assertEqual(len(added["match_ids"]), 2)
        self.assertEqual(added["match_id"], added["match_ids"][1])
        self.assertEqual(added["csv_path"], "")  # the new match is empty until it is scraped
        first = added["matches"][0]
        self.assertEqual((first["title"], first["has_events"], first["kickoffs_set"]), ("A v B", True, False))

    def test_adding_twice_reuses_the_empty_match_waiting(self):
        once = self.store.add_match(self.project["id"])
        twice = self.store.add_match(self.project["id"])
        self.assertEqual(once["match_ids"], twice["match_ids"])

    def test_each_match_keeps_its_own_kickoffs_and_video(self):
        first = self.project["match_id"]
        second = self.store.add_match(self.project["id"])
        self.store.upsert({"id": self.project["id"], "home_team": "C", "away_team": "D",
                           "csv_path": self.csv("b.csv"), "markers": {"1H": "00:10:00", "2H": "01:00:00"}})
        self.store.set_active_match(self.project["id"], first)
        self.store.upsert({"id": self.project["id"], "markers": {"1H": "00:02:00"}})
        views = {view["match_id"]: view for view in self.store.match_views(self.project["id"])}
        self.assertEqual(views[first]["markers"], {"1H": "00:02:00"})
        self.assertEqual(views[second["match_id"]]["markers"], {"1H": "00:10:00", "2H": "01:00:00"})
        self.assertEqual({view["id"] for view in views.values()}, {self.project["id"]})  # still one project

    def test_summaries_say_what_each_match_still_needs(self):
        second = self.store.add_match(self.project["id"])
        self.store.upsert({"id": self.project["id"], "home_team": "C", "away_team": "D", "csv_path": self.csv("b.csv"),
                           "video_path": "", "markers": {"1H": "00:10:00", "2H": "01:00:00"}})
        summaries = {item["id"]: item for item in self.store.get(self.project["id"])["matches"]}
        done = summaries[second["match_id"]]
        self.assertEqual((done["has_events"], done["kickoffs_set"], done["has_video"]), (True, True, False))

    def test_using_a_saved_match_replaces_only_the_active_one(self):
        other = self.store.upsert({"id": self.store.create()["id"], "home_team": "X", "away_team": "Y",
                                   "csv_path": self.csv("x.csv")})
        self.store.add_match(self.project["id"])  # an empty second match, active
        used = self.store.use_match(self.project["id"], other["match_id"])
        self.assertEqual(used["match_ids"], [self.project["match_id"], other["match_id"]])
        self.assertEqual(len(self.store.matches()), 2)  # the empty one is gone, nothing else is

    def test_removing_a_match_keeps_it_in_the_library(self):
        second = self.store.add_match(self.project["id"])
        self.store.upsert({"id": self.project["id"], "home_team": "C", "csv_path": self.csv("b.csv")})
        left = self.store.remove_match(self.project["id"], second["match_id"])
        self.assertEqual(left["match_ids"], [self.project["match_id"]])
        self.assertEqual(left["match_id"], self.project["match_id"])
        self.assertIsNotNone(self.store.get_match(second["match_id"]))
        with self.assertRaisesRegex(ValueError, "not in this project"):
            self.store.remove_match(self.project["id"], second["match_id"])

    def test_removing_an_empty_match_deletes_it(self):
        empty = self.store.add_match(self.project["id"])["match_id"]
        self.store.remove_match(self.project["id"], empty)
        self.assertIsNone(self.store.get_match(empty))

    def test_clip_windows_are_cleared_when_the_set_of_matches_changes(self):
        self.store.upsert({"id": self.project["id"], "preview_windows": [{"start": 1}]})
        self.assertEqual(self.store.add_match(self.project["id"])["preview_windows"], [])

    def test_activating_a_match_outside_the_project_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not in this project"):
            self.store.set_active_match(self.project["id"], "nope")


class LibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server("127.0.0.1", 0, self.root)
        self.store = self.server.match_store
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def request(self, path, payload=None, raw=None, headers=None):
        data = raw if raw is not None else (None if payload is None else json.dumps(payload).encode())
        request = Request(self.base + path, data=data, method="GET" if data is None else "POST",
                          headers=headers or {"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def import_csv(self, project_id):
        return self.request(f"/api/files/upload?project={project_id}", raw=CSV,
                            headers={"Content-Type": "application/octet-stream", "X-File-Name": "m.csv"})["match"]

    def test_library_lists_matches_with_the_projects_using_them(self):
        project = self.request("/api/projects", {"name": "Mine"})["project"]
        self.import_csv(project["id"])
        [match] = self.request("/api/library")["matches"]
        self.assertEqual(match["projects"], [{"id": project["id"], "project_name": "Mine"}])
        self.assertTrue(Path(match["csv_path"]).is_relative_to(self.root / "matches" / match["id"]))

    def test_a_second_csv_is_a_new_match_and_the_first_stays_saved(self):
        project = self.request("/api/projects", {"name": "Mine"})["project"]
        first = self.import_csv(project["id"])
        second = self.import_csv(project["id"])
        self.assertNotEqual(first["match_id"], second["match_id"])
        self.assertEqual(len(self.request("/api/library")["matches"]), 2)
        self.assertTrue(Path(first["csv_path"]).is_file())

    def test_a_bad_csv_leaves_the_projects_match_alone(self):
        project = self.request("/api/projects", {"name": "Mine"})["project"]
        first = self.import_csv(project["id"])
        with self.assertRaises(HTTPError) as context:
            self.request(f"/api/files/upload?project={project['id']}", raw=b"no,columns\n1,2\n",
                         headers={"Content-Type": "application/octet-stream", "X-File-Name": "bad.csv"})
        context.exception.close()
        self.assertEqual(self.store.get(project["id"])["match_id"], first["match_id"])
        self.assertEqual(len(self.store.matches()), 1)

    def test_scraping_a_saved_address_reuses_the_saved_match(self):
        first = self.request("/api/projects", {"name": "First"})["project"]
        csv = self.root / "feed.csv"
        csv.write_bytes(CSV)
        saved = self.store.upsert({"id": first["id"], "csv_path": str(csv), "source": "whoscored",
                                   "source_url": "https://site/match/1", "home_team": "H", "away_team": "A",
                                   "markers": {"1H": "00:01:00"}})
        second = self.request("/api/projects", {"name": "Untitled project"})["project"]
        with patch("packaging.clipmaker_api_server.scrape_match") as scrape:
            result = self.request("/api/scrape", {"url": "https://site/match/1", "project_id": second["id"]})["match"]
        scrape.assert_not_called()
        self.assertTrue(result["reused"])
        self.assertEqual(result["match_id"], saved["match_id"])
        self.assertEqual(result["markers"], {"1H": "00:01:00"})  # its kick-offs come too
        self.assertEqual(result["project_name"], "H vs A")
        self.assertEqual(result["event_count"], 2)

    def test_scraping_another_address_keeps_the_previous_match_saved(self):
        project = self.request("/api/projects", {"name": "Mine"})["project"]
        csv = self.root / "feed.csv"
        csv.write_bytes(CSV)
        before = self.store.upsert({"id": project["id"], "csv_path": str(csv), "source": "whoscored",
                                    "source_url": "https://site/match/1"})

        def scraped(url, directory):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "new.csv").write_bytes(CSV)
            return {"csv_path": str(directory / "new.csv"), "source": "whoscored", "source_url": url,
                    "home_team": "X", "away_team": "Y", "event_count": 2, "events": []}

        with patch("packaging.clipmaker_api_server.scrape_match", side_effect=scraped):
            result = self.request("/api/scrape", {"url": "https://site/match/2", "project_id": project["id"]})["match"]
        self.assertNotEqual(result["match_id"], before["match_id"])
        self.assertTrue(Path(result["csv_path"]).is_relative_to(self.root / "matches" / result["match_id"]))
        self.assertIsNotNone(self.store.get_match(before["match_id"]))

    def test_the_matches_route_adds_switches_and_removes(self):
        project = self.request("/api/projects", {"name": "Two"})["project"]
        first = self.import_csv(project["id"])
        added = self.request(f"/api/projects/{project['id']}/matches", {"action": "add"})["project"]
        self.assertEqual((len(added["matches"]), added["csv_path"]), (2, ""))
        csv = self.import_csv(project["id"])  # fills the new match; the first stays
        self.assertEqual(len(csv["matches"]), 2)
        self.assertNotEqual(csv["match_id"], first["match_id"])
        back = self.request(f"/api/projects/{project['id']}/matches",
                            {"action": "activate", "match_id": first["match_id"]})["project"]
        self.assertEqual((back["match_id"], back["event_count"]), (first["match_id"], 2))
        left = self.request(f"/api/projects/{project['id']}/matches",
                            {"action": "remove", "match_id": csv["match_id"]})["project"]
        self.assertEqual([item["id"] for item in left["matches"]], [first["match_id"]])
        self.assertEqual(len(self.request("/api/library")["matches"]), 2)
        with self.assertRaises(HTTPError) as context:
            self.request(f"/api/projects/{project['id']}/matches", {"action": "explode"})
        context.exception.close()

    def test_a_saved_match_can_be_added_to_a_project_that_has_another(self):
        first = self.request("/api/projects", {"name": "First"})["project"]
        match_id = self.import_csv(first["id"])["match_id"]
        second = self.request("/api/projects", {"name": "Second"})["project"]
        self.import_csv(second["id"])
        added = self.request(f"/api/projects/{second['id']}/matches", {"action": "add", "match_id": match_id})["project"]
        self.assertEqual(len(added["match_ids"]), 2)
        self.assertEqual(added["match_id"], match_id)

    def test_a_project_can_use_a_saved_match_and_delete_it_from_the_library(self):
        first = self.request("/api/projects", {"name": "First"})["project"]
        match_id = self.import_csv(first["id"])["match_id"]
        second = self.request("/api/projects", {"name": "Second"})["project"]
        used = self.request(f"/api/projects/{second['id']}/use-match", {"match_id": match_id})["project"]
        self.assertEqual((used["match_id"], used["event_count"]), (match_id, 2))
        self.request(f"/api/projects/{first['id']}/delete", {})
        self.assertEqual(self.store.get(second["id"])["match_id"], match_id)  # survives the first project
        result = self.request("/api/library/delete", {"match_id": match_id})
        self.assertEqual(result["matches"], [])
        self.assertEqual(self.store.get(second["id"])["match_ids"], [])


if __name__ == "__main__":
    unittest.main()
