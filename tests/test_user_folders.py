"""Default export folder (the user's videos folder + VizorPlay) and opening a finished export."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packaging import user_folders  # noqa: E402
from packaging.clipmaker_api_server import build_clip_config, create_server  # noqa: E402


def finished(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


class VideosFolderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_windows_uses_the_videos_known_folder_wherever_it_was_moved(self):
        moved = Path("D:/Media/My Videos")
        self.assertEqual(user_folders.default_export_dir(platform="win32", home=self.home, windows_lookup=lambda: moved),
                         moved / "VizorPlay")
        self.assertEqual(user_folders.videos_dir(platform="win32", home=self.home, windows_lookup=lambda: None),
                         self.home / "Videos")

    def test_macos_uses_movies(self):
        self.assertEqual(user_folders.default_export_dir(platform="darwin", home=self.home), self.home / "Movies" / "VizorPlay")

    def test_linux_asks_the_desktop_for_its_videos_folder(self):
        run = Mock(return_value=finished(f"{self.home / 'Vidéos'}\n"))
        self.assertEqual(user_folders.videos_dir(platform="linux", home=self.home, env={}, run=run), self.home / "Vidéos")
        self.assertEqual(run.call_args.args[0], ["xdg-user-dir", "VIDEOS"])

    def test_linux_falls_back_to_user_dirs_then_home_videos(self):
        unset = Mock(return_value=finished(f"{self.home}\n"))  # xdg-user-dir answers $HOME when unset
        self.assertEqual(user_folders.videos_dir(platform="linux", home=self.home, env={}, run=unset), self.home / "Videos")
        config = self.home / ".config"
        config.mkdir()
        (config / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Desktop"\nXDG_VIDEOS_DIR="$HOME/Clips"\n', encoding="utf-8")
        missing = Mock(side_effect=FileNotFoundError("xdg-user-dir"))
        self.assertEqual(user_folders.videos_dir(platform="linux", home=self.home, env={}, run=missing), self.home / "Clips")

    def test_reveal_opens_the_folder_with_the_platform_file_manager(self):
        for platform, command in (("darwin", "open"), ("linux", "xdg-open")):
            opener = Mock()
            user_folders.reveal_folder(self.home, platform=platform, run=opener)
            self.assertEqual(opener.call_args.args[0], [command, str(self.home)])
        with self.assertRaises(ValueError):
            user_folders.reveal_folder(self.home / "gone", platform="linux", run=Mock())

    def test_clip_config_uses_the_default_folder_unless_one_is_chosen(self):
        csv = self.home / "events.csv"
        csv.write_text("minute,second,period,type,team\n1,0,1,Goal,Home\n", encoding="utf-8")
        match = {"id": "m1", "csv_path": str(csv), "markers": {"1H": "00:00:00", "2H": "00:50:00"}}
        videos = self.home / "Videos" / "VizorPlay"
        self.assertEqual(Path(build_clip_config(match, {}, self.home, videos)["output_dir"]), videos.resolve())
        chosen = build_clip_config(match, {"output_dir": str(self.home / "Mine")}, self.home, videos)["output_dir"]
        self.assertEqual(Path(chosen), (self.home / "Mine").resolve())
        # Without the app's default (embedded use, tests) exports stay inside the project.
        self.assertEqual(Path(build_clip_config(match, {}, self.home)["output_dir"]),
                         (self.home / "projects" / "m1" / "exports").resolve())


class ExportFolderApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(self.temporary.name))
        self.server.default_export_dir = Path(self.temporary.name) / "Videos" / "VizorPlay"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.base + path, data=data, headers={"Content-Type": "application/json"},
                          method="GET" if payload is None else "POST")
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_default_folder_is_reported_to_the_page(self):
        status, result = self.request("/api/folders/output/default")
        self.assertEqual(status, 200)
        self.assertEqual(Path(result["path"]), Path(self.temporary.name) / "Videos" / "VizorPlay")

    def test_reveal_only_opens_a_finished_jobs_own_folder(self):
        folder = Path(self.temporary.name) / "out"
        folder.mkdir()
        jobs = self.server.jobs
        jobs._jobs["done1"] = {"id": "done1", "status": "complete", "dry_run": False, "output_dir": str(folder)}
        jobs._jobs["busy1"] = {"id": "busy1", "status": "running", "dry_run": False, "output_dir": str(folder)}
        with patch("packaging.user_folders.reveal_folder") as reveal:
            self.assertEqual(self.request("/api/jobs/busy1/reveal", {})[0], 404)
            self.assertEqual(self.request("/api/jobs/nope/reveal", {"path": "C:/Windows"})[0], 404)
            reveal.assert_not_called()
            self.assertEqual(self.request("/api/jobs/done1/reveal", {"path": "C:/Windows"}), (200, {"opened": True}))
            reveal.assert_called_once_with(folder)


if __name__ == "__main__":
    unittest.main()
