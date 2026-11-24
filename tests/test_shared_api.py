import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from packaging.clipmaker_api_server import (
    build_clip_config,
    create_server,
    detect_source,
    infer_score,
    normalize_period,
    compute_clip_windows,
    remove_unused_imports,
    render_preview_clip,
)


class SharedApiTests(unittest.TestCase):
    def preview_match(self):
        import pandas as pd
        path = Path(self.temporary.name) / 'preview-events.csv'
        pd.DataFrame([
            {'minute': 1, 'second': 0, 'period': 1, 'type': 'Goal', 'team': 'Home'},
            {'minute': 2, 'second': 0, 'period': 1, 'type': 'Goal', 'team': 'Home'},
            {'minute': 46, 'second': 0, 'period': 2, 'type': 'Goal', 'team': 'Away'},
        ]).to_csv(path, index=False)
        return {'id': 'preview-test', 'csv_path': str(path), 'markers': {'1H': '00:00:00', '2H': '00:50:00'}}

    def test_preview_correction_boundary_and_period(self):
        match = self.preview_match()
        config = build_clip_config(match, {}, Path(self.temporary.name))
        original = compute_clip_windows(config)
        config['timeline_corrections'] = [{'period': 1, 'at_seconds': 120, 'seconds': -10}]
        corrected = compute_clip_windows(config)
        self.assertEqual(len(original), 3)
        self.assertEqual(corrected[0]['start'], original[0]['start'])
        self.assertEqual(corrected[1]['start'], original[1]['start'] - 10)
        self.assertEqual(corrected[2]['start'], original[2]['start'])

    def test_edited_window_and_export_settings(self):
        match = self.preview_match()
        window = {'start': 14.5, 'end': 18.5, 'period': 1, 'label': 'Edited'}
        config = build_clip_config(match, {'clip_windows': [window], 'output_format': '.mkv',
            'output_filename': 'test.mp4', 'video_crf': 24, 'encoder_preset': 'fast',
            'audio_bitrate': '96k'}, Path(self.temporary.name))
        # Each window keeps its timeline number (here, the first and only clip).
        self.assertEqual(config['clip_windows'], [{**window, 'number': 1}])
        self.assertEqual(config['output_filename'], 'test.mkv')
        self.assertEqual(config['video_crf'], 24)
        self.assertEqual(config['encoder_preset'], 'fast')
        self.assertEqual(config['audio_bitrate'], '96k')

    def test_a_chosen_set_keeps_its_timeline_numbers(self):
        match = self.preview_match()
        windows = [{'start': 1, 'end': 3, 'period': 1, 'number': 3}, {'start': 6, 'end': 9, 'period': 1, 'number': 7},
                   {'start': 10, 'end': 12, 'period': 1}]
        config = build_clip_config(match, {'clip_windows': windows}, Path(self.temporary.name))
        self.assertEqual([window['number'] for window in config['clip_windows']], [3, 7, 3])
        for number in (0, 10000, 'x'):
            with self.subTest(number=number), self.assertRaises(ValueError):
                build_clip_config(match, {'clip_windows': [{'start': 1, 'end': 3, 'number': number}]},
                                  Path(self.temporary.name))

    def test_invalid_windows_rejected(self):
        match = self.preview_match()
        for start, end in [(5, 4), (-1, 4), (0, float('nan')), (0, float('inf'))]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                build_clip_config(match, {'clip_windows': [{'start': start, 'end': end}]}, Path(self.temporary.name))

    def test_preview_endpoint_returns_windows(self):
        match = self.preview_match()
        self.server.match_store.upsert(match)
        _, result = self.request('/api/previews', 'POST', {'match_id': match['id'], 'options': {}})
        self.assertEqual(len(result['windows']), 3)
        self.assertGreater(result['windows'][0]['end'], result['windows'][0]['start'])

    def test_preview_render_rejects_reversed_window(self):
        video = Path(self.temporary.name) / 'source.mp4'
        video.touch()
        with self.assertRaises(ValueError):
            render_preview_clip(str(video), 10, 5, Path(self.temporary.name), 20, 'veryfast', '128k')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(self.temporary.name))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())

    def test_engine_queues_a_burst_of_page_load_connections(self):
        # A page load opens about a dozen connections at once. With the standard
        # backlog of 5, Windows refused the extra ones while the engine was busy,
        # and a reloaded filters page lost its engine connection.
        import socket
        with tempfile.TemporaryDirectory() as name:
            busy = create_server("127.0.0.1", 0, Path(name))  # listening, not accepting yet
            sockets = []
            try:
                for _ in range(20):
                    sockets.append(socket.create_connection(("127.0.0.1", busy.server_port), timeout=2))
            finally:
                for connection in sockets:
                    connection.close()
                busy.server_close()
        self.assertEqual(len(sockets), 20)

    def test_error_reply_to_a_closed_connection_is_dropped_quietly(self):
        from http import HTTPStatus
        from types import SimpleNamespace
        from unittest.mock import Mock
        from packaging.clipmaker_api_server import ClipMakerHandler
        gone = SimpleNamespace(close_connection=False, send_json=Mock(side_effect=ConnectionAbortedError),
                               send_post_error=Mock(side_effect=BrokenPipeError))
        ClipMakerHandler.reply_error(gone, HTTPStatus.BAD_REQUEST, "bad")
        ClipMakerHandler.reply_error(gone, HTTPStatus.BAD_REQUEST, "bad", post=True)
        self.assertTrue(gone.close_connection)
        alive = SimpleNamespace(close_connection=False, send_json=Mock())
        ClipMakerHandler.reply_error(alive, HTTPStatus.BAD_REQUEST, "bad")
        alive.send_json.assert_called_once_with(HTTPStatus.BAD_REQUEST, {"error": "bad"})

    def test_health_and_static_frontend(self):
        status, body = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        with urlopen(self.base_url + "/", timeout=3) as response:
            self.assertIn(b"Match Intake", response.read())

    def test_match_history_round_trip(self):
        status, body = self.request(
            "/api/matches",
            method="POST",
            payload={
                "home_team": "Arsenal",
                "away_team": "Newcastle",
                "event_count": 1486,
                "markers": {"1H": "00:03:18", "2H": "00:50:46"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["match"]["id"], "arsenal-vs-newcastle")
        _, history = self.request("/api/matches")
        self.assertEqual(len(history["matches"]), 1)
        self.assertEqual(history["matches"][0]["markers"]["2H"], "00:50:46")

    def test_invalid_scrape_url_is_rejected(self):
        with self.assertRaises(HTTPError) as context:
            self.request("/api/scrape", method="POST", payload={"url": "https://example.com"})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_source_detection(self):
        self.assertEqual(detect_source("https://www.scoresway.com/match/1"), "scoresway")
        self.assertEqual(detect_source("https://www.whoscored.com/Matches/1"), "whoscored")

    def test_score_is_inferred_from_goal_events(self):
        import pandas as pd

        frame = pd.DataFrame(
            [
                {"type": "Goal", "team": "Home", "period": 1},
                {"type": "Goal", "team": "Away", "period": 2},
                {"type": "Goal", "team": "Away", "period": 2, "is_own_goal": True},
                {"type": "Goal", "team": "Away", "period": 5},
            ]
        )
        self.assertEqual(infer_score(frame, "Home", "Away"), (2, 1))

    def test_score_resolves_fixture_labels_to_event_team_names(self):
        import pandas as pd

        frame = pd.DataFrame(
            [
                {"type": "Goal", "team": "Arsenal FC", "period": "FirstHalf"},
                {"type": "Goal", "team": "Paris Saint-Germain FC", "period": "SecondHalf"},
                {"type": "Goal", "team": "Paris Saint-Germain FC", "period": "PenaltyShootout"},
                {"type": "Goal", "team": "Arsenal FC", "period": "PenaltyShootout"},
            ]
        )
        self.assertEqual(infer_score(frame, "Paris SG", "Arsenal"), (1, 1))

    def test_named_periods_are_normalized(self):
        self.assertEqual(normalize_period("FirstHalf"), 1)
        self.assertEqual(normalize_period("SecondHalf"), 2)
        self.assertEqual(normalize_period("PenaltyShootout"), 5)

    def test_full_event_table_reads_saved_csv(self):
        csv_path = Path(self.temporary.name) / "events.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team,xT,is_header,pitch_zone\n"
            "12,30,Goal,FirstHalf,Player One,Home,0.5,True,Centre\n"
            "68,5,SavedShot,SecondHalf,Player Two,Away,0.2,False,\n",
            encoding="utf-8",
        )
        self.server.match_store.upsert({"id": "table-test", "csv_path": str(csv_path)})
        status, result = self.request(
            "/api/events",
            method="POST",
            payload={"csv_path": str(csv_path)},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["event_count"], 2)
        # Every CSV column comes through (qualifiers included) as compact rows,
        # with each row's normalized period for the half filter.
        table = result["events"]
        self.assertEqual(table["columns"], ["minute", "second", "type", "period", "playerName",
                                            "team", "xT", "is_header", "pitch_zone"])
        self.assertEqual(table["rows"][0], [12, 30, "Goal", "FirstHalf", "Player One", "Home", 0.5, True, "Centre"])
        self.assertEqual(table["rows"][1][-2:], [False, None])
        self.assertEqual(table["periods"], [1, 2])

    def test_filter_options_follow_the_saved_scrape(self):
        csv_path = Path(self.temporary.name) / "filter-options.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team,outcomeType,is_cross,is_own_goal,prog_pass,xT\n"
            "1,0,Pass,1,Player One,Home,Successful,True,False,4.5,0.2\n"
            "2,0,Goal,1,Player Two,Away,Successful,False,False,0,0.8\n",
            encoding="utf-8",
        )
        # Event data paths are set server-side (scrape/import), not by requests.
        saved = {"match": self.server.match_store.upsert({
                "home_team": "Home",
                "away_team": "Away",
                "csv_path": str(csv_path),
                "markers": {"1H": "00:00:00", "2H": "00:48:00"},
            })}
        status, result = self.request(
            "/api/filter-options",
            method="POST",
            payload={"match_id": saved["match"]["id"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["action_types"], ["Goal", "Pass"])
        self.assertEqual(result["team_players"]["Home"], ["Player One"])
        qualifier_map = {item["flag"]: item for item in result["qualifiers"]}
        self.assertTrue(qualifier_map["crosses_only"]["available"])
        self.assertTrue(qualifier_map["progressive_only"]["available"])
        self.assertFalse(qualifier_map["own_goals_only"]["available"])
        # The page counts per scope from this event index.
        events = result["events"]
        self.assertEqual(events["teams"], ["Away", "Home"])
        self.assertEqual(events["players"], ["Player One", "Player Two"])
        self.assertEqual(events["team"], [1, 0])
        self.assertEqual(events["player"], [0, 1])
        self.assertEqual(events["type"], [1, 0])
        self.assertEqual(events["period"], [1, 1])
        self.assertEqual(events["qualifiers"]["successful_only"], [0, 1])
        self.assertEqual(events["qualifiers"]["crosses_only"], [0])
        self.assertEqual(events["qualifiers"]["progressive_only"], [0])
        self.assertNotIn("own_goals_only", events["qualifiers"])

    def test_filter_event_index_handles_missing_and_unknown_values(self):
        csv_path = Path(self.temporary.name) / "sparse.csv"
        csv_path.write_text(
            "minute,second,type,period,team,outcomeType\n"
            "1,0,Pass,FirstHalf,Home,Successful\n"
            "2,0,,SecondHalf,,Unsuccessful\n"
            "3,0,TakeOn,,Home,Successful\n",
            encoding="utf-8",
        )
        saved = self.server.match_store.upsert({"id": "sparse", "csv_path": str(csv_path)})
        status, result = self.request(
            "/api/filter-options", method="POST", payload={"match_id": saved["id"]}
        )
        self.assertEqual(status, 200)
        events = result["events"]
        self.assertEqual(events["players"], [])
        self.assertEqual(events["player"], [-1, -1, -1])  # no playerName column
        self.assertEqual(events["team"], [0, -1, 0])
        self.assertEqual(events["type"], [0, -1, 1])
        self.assertEqual(events["period"], [1, 2, 0])
        self.assertEqual(events["qualifiers"]["unsuccessful_only"], [1])

    def test_config_applies_team_players_and_extended_qualifiers(self):
        csv_path = Path(self.temporary.name) / "scope.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team,is_goal_kick\n"
            "1,0,Pass,1,Player One,Home,True\n"
            "2,0,Pass,1,Player Two,Home,False\n"
            "3,0,Pass,1,Player Three,Away,True\n",
            encoding="utf-8",
        )
        match = {
            "id": "home-vs-away",
            "csv_path": str(csv_path),
            "video_path": "",
            "markers": {"1H": "00:00:00", "2H": "00:48:00"},
        }
        config = build_clip_config(
            match,
            {
                "dry_run": True,
                "team_filter": "Home",
                "player_filters": ["Player One"],
                "qualifier_logic": "all",
                "goal_kicks_only": True,
            },
            Path(self.temporary.name),
        )
        import pandas as pd

        filtered = pd.read_csv(config["data_file"])
        self.assertEqual(filtered["playerName"].tolist(), ["Player One"])
        self.assertEqual(config["qualifier_logic"], "all")
        self.assertTrue(config["goal_kicks_only"])
        Path(config["_temporary_data_file"]).unlink()

    def test_dry_run_job_uses_saved_match_and_real_engine(self):
        csv_path = Path(self.temporary.name) / "events.csv"
        csv_path.write_text(
            "minute,second,type,period,playerName,team\n"
            "12,30,Goal,1,Player One,Home\n"
            "68,5,SavedShot,2,Player Two,Away\n",
            encoding="utf-8",
        )
        # Event data paths are set server-side (scrape/import), not by requests.
        saved = {"match": self.server.match_store.upsert({
                "home_team": "Home",
                "away_team": "Away",
                "csv_path": str(csv_path),
                "event_count": 2,
                "markers": {"1H": "00:00:10", "2H": "00:48:00"},
            })}
        status, started = self.request(
            "/api/jobs",
            method="POST",
            payload={
                "match_id": saved["match"]["id"],
                "options": {
                    "dry_run": True,
                    "filter_types": ["Goal", "SavedShot"],
                    "before_buffer": 4,
                    "after_buffer": 7,
                },
            },
        )
        self.assertEqual(status, 202)

        job = started["job"]
        deadline = time.time() + 5
        while job["status"] not in {"complete", "failed", "cancelled"} and time.time() < deadline:
            time.sleep(0.05)
            _, result = self.request(f"/api/jobs/{job['id']}")
            job = result["job"]

        self.assertEqual(job["status"], "complete", "\n".join(job["logs"]))
        self.assertTrue(any("2 clips" in line for line in job["logs"]))
        self.assertTrue(any("DRY RUN complete" in line for line in job["logs"]))

    def test_render_job_requires_native_video_path(self):
        csv_path = Path(self.temporary.name) / "events.csv"
        csv_path.write_text("minute,second,type,period\n1,0,Goal,1\n", encoding="utf-8")
        # Event data paths are set server-side (scrape/import), not by requests.
        saved = {"match": self.server.match_store.upsert({
                "home_team": "Home",
                "away_team": "Away",
                "csv_path": str(csv_path),
                "markers": {"1H": "00:00:00", "2H": "00:48:00"},
            })}
        with self.assertRaises(HTTPError) as context:
            self.request(
                "/api/jobs",
                method="POST",
                payload={"match_id": saved["match"]["id"], "options": {"dry_run": False}},
            )
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_native_video_picker_returns_path_and_streams_ranges(self):
        video_path = Path(self.temporary.name) / "match.mp4"
        video_path.write_bytes(b"0123456789")
        with patch(
            "packaging.clipmaker_api_server.choose_video_file",
            return_value=video_path,
        ), patch("packaging.clipmaker_api_server.sys.platform", "linux"):
            status, result = self.request("/api/files/video", method="POST", payload={})

        self.assertEqual(status, 200)
        self.assertTrue(Path(result["file"]["path"]).samefile(video_path))
        request = Request(
            self.base_url + result["file"]["url"],
            headers={"Range": "bytes=2-5"},
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
            self.assertEqual(response.read(), b"2345")

    def test_macos_video_picker_uses_the_system_dialog_and_keeps_the_path(self):
        # macOS used to fall back to a browser upload, which copied the whole video.
        video_path = Path(self.temporary.name) / "mac match.mov"
        video_path.write_bytes(b"0123456789")
        finished = type("Done", (), {"returncode": 0, "stdout": f"{video_path}\n", "stderr": ""})()
        with patch("packaging.clipmaker_api_server.sys.platform", "darwin"), \
             patch.dict("os.environ", {}, clear=False) as env, \
             patch("subprocess.run", return_value=finished) as run:
            env.pop("VIZORPLAY_TEST_VIDEO_PICK", None)
            status, result = self.request("/api/files/video", method="POST", payload={"period": "2H"})
        self.assertEqual(status, 200)
        self.assertTrue(Path(result["file"]["path"]).samefile(video_path))
        script = run.call_args.args[0]
        self.assertEqual(script[0], "osascript")
        self.assertIn("second-half", script[2])

    def test_macos_picker_cancel_is_not_an_error(self):
        cancelled = type("Done", (), {"returncode": 1, "stdout": "", "stderr": "User canceled. (-128)"})()
        with patch("packaging.clipmaker_api_server.sys.platform", "darwin"), \
             patch.dict("os.environ", {}, clear=False) as env, \
             patch("subprocess.run", return_value=cancelled):
            env.pop("VIZORPLAY_TEST_VIDEO_PICK", None)
            status, result = self.request("/api/files/video", method="POST", payload={})
        self.assertEqual((status, result), (200, {"cancelled": True}))

    def test_video_picker_refuses_files_that_are_not_videos(self):
        document = Path(self.temporary.name) / "notes.txt"
        document.write_text("not a video", encoding="utf-8")
        with patch("packaging.clipmaker_api_server.choose_video_file", return_value=document):
            with self.assertRaises(HTTPError) as context:
                self.request("/api/files/video", method="POST", payload={})
        self.assertEqual(context.exception.code, 400)
        self.assertIn("Choose a video file", json.loads(context.exception.read())["error"])
        context.exception.close()

    def test_video_picker_rejects_unknown_periods(self):
        with patch("packaging.clipmaker_api_server.choose_video_file") as picker:
            with self.assertRaises(HTTPError) as context:
                self.request("/api/files/video", method="POST", payload={"period": "../../x"})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()
        picker.assert_not_called()

    def test_test_harness_pick_file_names_the_chosen_video(self):
        video_path = Path(self.temporary.name) / "picked.mp4"
        video_path.write_bytes(b"abc")
        pick = Path(self.temporary.name) / "pick.txt"
        pick.write_text(str(video_path), encoding="utf-8")
        with patch.dict("os.environ", {"VIZORPLAY_TEST_VIDEO_PICK": str(pick)}):
            status, result = self.request("/api/files/video", method="POST", payload={"period": "PEN"})
        self.assertEqual(status, 200)
        self.assertTrue(Path(result["file"]["path"]).samefile(video_path))

    def test_video_uploads_are_refused_so_nothing_is_copied(self):
        project = self.server.match_store.create()
        request = Request(f"{self.base_url}/api/files/upload?project={project['id']}", data=b"0" * 64,
                          method="POST", headers={"Content-Type": "application/octet-stream",
                                                  "X-File-Name": "match.mp4"})
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=3)
        self.assertEqual(context.exception.code, 400)
        self.assertIn("not copied", json.loads(context.exception.read())["error"])
        context.exception.close()
        imports = Path(self.temporary.name) / "projects" / project["id"] / "imports"
        self.assertEqual([path for path in imports.glob("*")] if imports.exists() else [], [])

    def test_missing_saved_video_says_how_to_find_it_again(self):
        project = self.server.match_store.upsert({"id": "gone", "video_name": "away.mp4",
                                                  "video_path": str(Path(self.temporary.name) / "away.mp4")})
        with self.assertRaises(HTTPError) as context:
            self.request("/api/files/reopen", method="POST", payload={"match_id": project["id"]})
        message = json.loads(context.exception.read())["error"]
        context.exception.close()
        self.assertIn("away.mp4", message)
        self.assertIn("Find it again on Intake", message)

    def test_unused_video_copies_from_older_versions_are_removed(self):
        store = self.server.match_store
        kept = store.upsert({"id": "kept"})
        imports = store.project_path(kept["id"]).parent / "imports"
        imports.mkdir(parents=True)
        in_use, period_in_use, unused, csv = (imports / "a.mp4", imports / "b.mkv", imports / "c.mp4", imports / "d.csv")
        old_part, new_part = imports / "e.part", imports / "f.part"
        for path in (in_use, period_in_use, unused, csv, old_part, new_part):
            path.write_bytes(b"x")
        old = time.time() - 7200
        os.utime(old_part, (old, old))
        store.upsert({"id": "kept", "video_path": str(in_use), "period_videos": {"2H": str(period_in_use)}})
        self.assertEqual(remove_unused_imports(store), 2)
        self.assertEqual(sorted(path.name for path in imports.iterdir()), ["a.mp4", "b.mkv", "d.csv", "f.part"])

    def test_replacing_a_video_removes_the_copy_it_replaced(self):
        store = self.server.match_store
        project = store.create()
        imports = store.project_path(project["id"]).parent / "imports"
        imports.mkdir(parents=True)
        copy = imports / "old-copy.mp4"
        copy.write_bytes(b"x")
        store.upsert({"id": project["id"], "video_path": str(copy)})
        original = Path(self.temporary.name) / "original.mp4"
        original.write_bytes(b"y")
        status, _ = self.request(f"/api/projects/{project['id']}", method="POST",
                                 payload={"video_path": str(original), "video_name": original.name})
        self.assertEqual(status, 200)
        self.assertFalse(copy.exists())
        self.assertTrue(original.exists())

    def test_saved_video_can_be_reopened(self):
        video_path = Path(self.temporary.name) / "saved-match.mp4"
        video_path.write_bytes(b"abcdefghij")
        # Event data paths are set server-side (scrape/import), not by requests.
        saved = {"match": self.server.match_store.upsert({
                "home_team": "Home",
                "away_team": "Away",
                "video_name": video_path.name,
                "video_path": str(video_path),
            })}
        status, result = self.request(
            "/api/files/reopen",
            method="POST",
            payload={"match_id": saved["match"]["id"]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(Path(result["file"]["path"]).samefile(video_path))



class ServerStartTests(unittest.TestCase):
    def test_starting_never_looks_up_the_computers_network_name(self):
        # socket.getfqdn() can search the local network, which makes macOS ask
        # the user to let "Python" find devices on local networks.
        with tempfile.TemporaryDirectory() as directory,                 patch("socket.getfqdn", side_effect=AssertionError("network name lookup")) as lookup:
            server = create_server("127.0.0.1", 0, Path(directory))
            try:
                self.assertEqual(server.server_name, "127.0.0.1")
                self.assertGreater(server.server_port, 0)
            finally:
                server.server_close()
        lookup.assert_not_called()

if __name__ == "__main__":
    unittest.main()
