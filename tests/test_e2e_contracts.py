"""Test automation wiring without invoking a GUI or touching real user projects."""
import hashlib
import io
import json
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from packaging import clipmaker_bootstrap as bootstrap

ROOT = Path(__file__).resolve().parents[1]


class AutomationContracts(unittest.TestCase):
    def test_native_lookup_scrolls_before_testing_reveal_visibility(self):
        from tests.native_smoke import ready_element
        driver = Mock()
        target = driver.find_element.return_value
        target.is_displayed.return_value = False
        driver.execute_script.side_effect = lambda *args: setattr(target.is_displayed, "return_value", True)
        wait = Mock()
        wait.until.side_effect = lambda condition: condition(driver)
        self.assertIs(ready_element(driver, wait, "[data-continue]"), target)
        driver.execute_script.assert_called_once()
        target.is_displayed.assert_called_once()

    def test_live_checks_preserve_success_and_report_response_body(self):
        from tests.live_scrape import check_providers
        match = {"event_count": 23, "home_team": "Home", "away_team": "Away"}
        denied = HTTPError("http://localhost/api/scrape", 500, "error", {},
                           io.BytesIO(b'{"error":"WhoScored blocked the request (403)"}'))
        replies = [{"project": {"id": "first"}}, {"match": match}, {"project": match},
                   {"project": {"id": "second"}}, denied]
        with tempfile.TemporaryDirectory() as directory, \
             patch("tests.live_scrape.request", side_effect=replies):
            result = check_providers("http://localhost", {"scoresway": "one", "whoscored": "two"}, Path(directory))
            self.assertEqual(result["scoresway"], {"status": "passed", "events": 23})
            self.assertEqual(result["whoscored"]["status"], "failed")
            self.assertIn("403", result["whoscored"]["error"])
            self.assertEqual(json.loads((Path(directory) / "result.json").read_text()), result)

    def test_live_checks_continue_after_first_provider_fails(self):
        from tests.live_scrape import check_providers
        with tempfile.TemporaryDirectory() as directory, \
             patch("tests.live_scrape.request", side_effect=RuntimeError("provider unavailable")) as fetch:
            result = check_providers("http://localhost", {"scoresway": "one", "whoscored": "two"}, Path(directory))
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(item["status"] == "failed" for item in result.values()))

    def test_whoscored_keeps_provider_error_in_queue(self):
        from app import whoscored_scraper
        messages = queue.Queue()
        session = Mock()
        session.get.return_value.status_code = 403
        with patch("curl_cffi.requests.Session", return_value=session), \
             patch.object(whoscored_scraper.time, "sleep"):
            whoscored_scraper.scrape_whoscored("https://www.whoscored.com/matches/1", messages, str(ROOT / "app"))
        errors = [item for item in list(messages.queue) if item["type"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("403", errors[0]["msg"])

    def test_native_driver_waits_for_protocol_readiness(self):
        from tests.native_smoke import wait_for_driver
        process = Mock()
        process.poll.return_value = None
        responses = [OSError("native driver is not listening yet"),
                     io.BytesIO(b'{"value":{"ready":false}}'),
                     io.BytesIO(b'{"value":{"ready":true}}')]
        with patch("tests.native_smoke.urlopen", side_effect=responses) as query, \
             patch("tests.native_smoke.time.sleep"):
            wait_for_driver(process, 4444)
        self.assertEqual(query.call_count, 3)

    def test_launcher_accepts_isolated_data_and_suppresses_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            python = bootstrap.venv_python(runtime / "venv")
            python.parent.mkdir(parents=True)
            python.touch()
            requirements = root / "requirements.txt"
            requirements.write_bytes(b"fixture\n")
            (runtime / "requirements.sha256").write_text(hashlib.sha256(requirements.read_bytes()).hexdigest())
            process = Mock()
            process.wait.return_value = 0
            with patch.object(bootstrap, "__file__", str(root / "clipmaker_bootstrap.py")), \
                 patch.object(bootstrap, "runtime_root", return_value=runtime), \
                 patch.object(bootstrap, "wait_until_ready", return_value=True), \
                 patch.object(bootstrap.subprocess, "Popen", return_value=process) as start, \
                 patch.object(bootstrap.webbrowser, "open") as browser, \
                 patch.object(sys, "argv", ["launcher", "--no-browser", "--port", "4188", "--data-dir", str(root / "isolated")]):
                self.assertEqual(bootstrap.main(), 0)
            self.assertEqual(start.call_args.args[0][-4:], ["--port", "4188", "--data-dir", str((root / "isolated").resolve())])
            browser.assert_not_called()

    def test_formula_override_does_not_rewrite_repository_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "clipmaker.rb"
            command = [sys.executable, str(ROOT / "packaging/render_homebrew_formula.py"),
                       "--version", "1.0.0", "--sha256", "a" * 64, "--output", str(target)]
            subprocess.run([*command, "--source-url", "file:///tmp/vizorplay.tar.gz"], check=True, capture_output=True)
            source = target.read_text()
            self.assertIn('url "file:///tmp/vizorplay.tar.gz"', source)
            self.assertIn('version "1.0.0"', source)
            self.assertIn('homepage "https://github.com/B03GHB4L1/ClipMaker"', source)
            rejected = subprocess.run([*command, "--source-url", 'file:///tmp/a"; system("bad")'], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)

    def test_native_selectors_exist_in_shipped_pages(self):
        intake = (ROOT / "ui/index.html").read_text(encoding="utf-8")
        filters = (ROOT / "ui/filters.html").read_text(encoding="utf-8")
        for selector in ("data-new-project", "data-continue", "data-engine-state"):
            self.assertIn(selector, intake)
        for selector in ("filter-preview-button", "data-export-button", "data-preview-count", "data-job-state"):
            self.assertIn(selector, filters)
        self.assertIn('id="timing"', filters)

    def test_full_workflow_is_read_only_and_covers_all_os(self):
        # PyYAML is a CI-only dependency; source guards still run locally without it.
        source = (ROOT / ".github/workflows/e2e.yml").read_text()
        self.assertNotIn("github.event.repository.private", source)
        self.assertIn("contents: read", source)
        self.assertNotIn("contents: write", source)
        for runner in ("windows-latest", "ubuntu-22.04", "macos-latest"):
            self.assertIn(runner, source)
        for script in ("browser_smoke.py", "native_smoke.py", "live_scrape.py"):
            self.assertIn(script, source)
        self.assertIn("if: always()", source)
        self.assertNotIn("action-gh-release", source)
        try:
            import yaml
        except ImportError:
            return
        parsed = yaml.safe_load(source)
        triggers = parsed.get("on", parsed.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch", "push"})
        self.assertEqual(triggers["push"]["branches"], ["codex/release-packaging"])
        self.assertEqual(parsed["permissions"], {"contents": "read"})
        self.assertEqual(set(parsed["jobs"]["verdict"]["needs"]),
                         {"core", "installed-desktop", "homebrew", "live-providers"})


if __name__ == "__main__":
    unittest.main()
