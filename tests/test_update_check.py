"""Update notice: the release feed check, how each install updates, and the engine routes."""
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.request import Request, urlopen

from packaging import update_check
from packaging.clipmaker_api_server import INSTALL_UPDATE_PATH, create_server

ROOT = Path(__file__).resolve().parents[1]


def feed(version, platforms=("windows-x86_64",), notes="Faster exports"):
    return json.dumps({"version": version, "notes": notes,
                       "platforms": {name: {"signature": "x", "url": "https://example.test/a"} for name in platforms}}).encode()


class FeedCheckTests(unittest.TestCase):
    def check(self, data=None, error=None, platform="win32", desktop=True, env=None):
        fetch = Mock(side_effect=error) if error else Mock(return_value=data)
        return update_check.check(env=env or {}, platform=platform, desktop=desktop, fetch=fetch), fetch

    def test_newer_release_is_offered_in_the_windows_desktop_app(self):
        status, fetch = self.check(feed("1.1.0"))
        fetch.assert_called_once_with(update_check.DEFAULT_FEED)
        self.assertEqual((status["available"], status["latest"], status["install"]), (True, "1.1.0", "in-app"))
        self.assertEqual(status["notes"], "Faster exports")
        self.assertEqual(status["release_url"], update_check.RELEASES_URL)

    def test_same_or_older_release_is_not_offered(self):
        for version in ("1.0.0", "v1.0.0", "0.9.9"):
            status, _ = self.check(feed(version))
            self.assertFalse(status["available"], version)
        # Versions compare as numbers, not text.
        self.assertTrue(self.check(feed("1.0.10"))[0]["available"])

    def test_each_install_kind_gets_its_own_way_to_update(self):
        self.assertEqual(self.check(feed("1.1.0"), platform="linux")[0]["install"], "download")
        self.assertEqual(self.check(feed("1.1.0"), platform="darwin", desktop=False)[0]["install"], "homebrew")
        self.assertEqual(self.check(feed("1.1.0"), platform="win32", desktop=False)[0]["install"], "download")
        # Without a signed Windows package in the feed, Windows falls back to downloading.
        self.assertEqual(self.check(feed("1.1.0", platforms=()))[0]["install"], "download")

    def test_offline_missing_or_malformed_feed_is_quietly_not_an_update(self):
        for data, error in ((None, OSError("offline")), (b"<html>404</html>", None), (b"[]", None),
                            (json.dumps({"version": "soon"}).encode(), None)):
            status, _ = self.check(data, error)
            self.assertFalse(status["available"])
            self.assertIn("Could not check for updates", status["error"])

    def test_feed_must_be_https_and_can_be_disabled(self):
        self.assertEqual(update_check.feed_url({"VIZORPLAY_UPDATE_URL": "https://127.0.0.1:9/latest.json"}),
                         "https://127.0.0.1:9/latest.json")
        for url in ("http://example.test/latest.json", "file:///C:/latest.json", "https:///latest.json"):
            with self.assertRaises(ValueError):
                update_check.feed_url({"VIZORPLAY_UPDATE_URL": url})
        status, _ = self.check(error=AssertionError("must not fetch"), env={"VIZORPLAY_UPDATE_URL": "http://x.test"})
        self.assertIn("https", status["error"])
        status, fetch = self.check(feed("9.0.0"), env={"VIZORPLAY_UPDATE_CHECK": "0"})
        self.assertTrue(status["disabled"])
        self.assertFalse(status["available"])
        fetch.assert_not_called()

    def test_notes_are_capped(self):
        self.assertEqual(len(self.check(feed("1.1.0", notes="x" * 5000))[0]["notes"]), 500)

    def test_feed_size_is_limited(self):
        response = Mock()
        response.read.return_value = b"x" * (update_check.MAX_FEED_BYTES + 1)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        from unittest.mock import patch
        with patch.object(update_check, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "large"):
                update_check.fetch_feed("https://example.test/latest.json")

    def test_one_check_per_engine_run(self):
        checker = Mock(return_value={"available": False})
        status = update_check.UpdateStatus(desktop=True, checker=checker)
        status.get()["available"] = True  # callers get copies
        self.assertEqual(status.get(), {"available": False})
        checker.assert_called_once_with(desktop=True)

    def test_release_page_is_fixed(self):
        opener = Mock(return_value=True)
        self.assertTrue(update_check.open_release_page(opener))
        opener.assert_called_once_with(update_check.RELEASES_URL)


class EngineRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(self.directory.name))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    def test_update_status_route(self):
        checker = Mock(return_value={"available": True, "latest": "1.1.0", "install": "in-app"})
        self.server.update_status = update_check.UpdateStatus(desktop=True, checker=checker)
        for _ in range(2):
            with urlopen(self.base + "/api/update", timeout=5) as response:
                self.assertEqual(json.load(response)["update"]["latest"], "1.1.0")
        checker.assert_called_once()

    def test_install_path_is_a_no_op_outside_the_desktop_shell(self):
        with urlopen(self.base + INSTALL_UPDATE_PATH, timeout=5) as response:
            self.assertEqual(response.status, 204)  # browsers stay on the page

    def test_open_release_route_opens_only_the_fixed_page(self):
        from unittest.mock import patch
        with patch.object(update_check.webbrowser, "open", return_value=True) as opened:
            request = Request(self.base + "/api/update/open-release", data=b'{"url": "https://evil.test"}',
                              headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=5) as response:
                self.assertTrue(json.load(response)["opened"])
        opened.assert_called_once_with(update_check.RELEASES_URL)

    def test_other_websites_cannot_open_the_release_page(self):
        from urllib.error import HTTPError
        request = Request(self.base + "/api/update/open-release", data=b"{}", method="POST",
                          headers={"Content-Type": "application/json", "Origin": "https://evil.test"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)


class UpdaterWiringTests(unittest.TestCase):
    def test_shell_page_and_engine_agree_on_the_install_path(self):
        lib = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        page = (ROOT / "ui/update.js").read_text(encoding="utf-8")
        self.assertIn(f'const INSTALL_UPDATE_PATH: &str = "{INSTALL_UPDATE_PATH}";', lib)
        self.assertIn(f'const INSTALL_PATH = "{INSTALL_UPDATE_PATH}";', page)
        self.assertIn("window.vizorplayUpdateStatus", lib)
        self.assertIn("window.vizorplayUpdateStatus =", page)
        for name in ("index.html", "filters.html", "analysis.html"):
            self.assertIn('src="update.js?v=', (ROOT / "ui" / name).read_text(encoding="utf-8"), name)

    def test_shell_installs_only_updates_signed_with_the_built_in_key(self):
        config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        updater = config["plugins"]["updater"]
        self.assertEqual(updater["endpoints"], [update_check.DEFAULT_FEED])
        self.assertEqual(updater["windows"]["installMode"], "passive")
        self.assertRegex(updater["pubkey"], r"^[A-Za-z0-9+/=]{100,}$")
        self.assertNotIn("dangerousInsecureTransportProtocol", json.dumps(config))
        lib = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        self.assertNotIn(".pubkey(", lib)  # tests may move the feed, never the key
        self.assertIn("is_install_request(url, port)", lib)
        self.assertIn("stop_backend(&app);\n    update\n        .install(", lib)
        # The window is created in setup so its navigations can be watched.
        self.assertFalse(next(w for w in config["app"]["windows"] if w["label"] == "main")["create"])
        self.assertIn("tauri-plugin-updater", (ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))

    def test_ci_signs_and_tests_the_windows_update_and_release_publishes_the_feed(self):
        e2e = (ROOT / ".github/workflows/e2e.yml").read_text(encoding="utf-8")
        self.assertIn('"createUpdaterArtifacts":true', e2e)
        self.assertIn("secrets.TAURI_SIGNING_PRIVATE_KEY", e2e)
        self.assertIn("python tests/windows_update.py", e2e)
        self.assertIn('--signature "$package.sig" --evidence build/update-evidence/result.json', e2e)
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("secrets: inherit", release)
        self.assertIn("release-artifacts/latest.json", release)
        self.assertTrue(re.search(r"releases/latest/download/latest\.json", update_check.DEFAULT_FEED))


if __name__ == "__main__":
    unittest.main()
