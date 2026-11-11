"""The scraper's browser fallback uses the installed browser, not a bundled one.

docs/SCRAPER_BROWSER_PLAN.md. Unit tests cover the browser locator, the CDP
session logic against a scripted peer and the Scoresway wiring; the
integration test drives the real installed browser against a local page.
CI sets VIZORPLAY_REQUIRE_BROWSER_TEST=1 so a missing browser fails there
instead of skipping.
"""
import base64
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import browser_capture as bc  # noqa: E402
import scoresway_scraper as scoresway  # noqa: E402


class BrowserLocatorTests(unittest.TestCase):
    def test_windows_prefers_edge_then_chrome(self):
        env = {"PROGRAMFILES(X86)": r"C:\PF86", "PROGRAMFILES": r"C:\PF", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
        edge = str(Path(r"C:\PF86") / r"Microsoft\Edge\Application\msedge.exe")
        chrome = str(Path(r"C:\PF") / r"Google\Chrome\Application\chrome.exe")
        installed = {edge, chrome}
        found = bc.find_browser(env, "win32", exists=installed.__contains__, which=lambda name: None)
        self.assertEqual(found, edge)
        installed.discard(edge)
        self.assertEqual(bc.find_browser(env, "win32", exists=installed.__contains__, which=lambda name: None), chrome)

    def test_macos_application_bundles(self):
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        self.assertEqual(bc.find_browser({"HOME": "/Users/u"}, "darwin", exists={chrome}.__contains__,
                                         which=lambda name: None), chrome)

    def test_linux_uses_path_names(self):
        which = {"chromium": "/usr/bin/chromium"}.get
        self.assertEqual(bc.find_browser({}, "linux", exists=lambda path: False, which=which), "/usr/bin/chromium")

    def test_explicit_choice_must_exist_and_nothing_found_is_none(self):
        env = {"VIZORPLAY_BROWSER": "/opt/custom/chrome"}
        self.assertEqual(bc.find_browser(env, "linux", exists={"/opt/custom/chrome"}.__contains__), "/opt/custom/chrome")
        self.assertIsNone(bc.find_browser(env, "linux", exists=lambda path: False, which=lambda name: "/usr/bin/x"))
        self.assertIsNone(bc.find_browser({}, "linux", exists=lambda path: False, which=lambda name: None))

    def test_no_browser_gives_actionable_error_and_only_web_pages(self):
        with patch.object(bc, "find_browser", return_value=None):
            with self.assertRaisesRegex(bc.BrowserUnavailable, "Install Microsoft Edge or Google Chrome"):
                bc.capture_responses("https://example.test/", lambda url: None)
        with self.assertRaises(ValueError):
            bc.capture_responses("file:///etc/passwd", lambda url: None, browser=sys.executable)

    def test_slow_browser_start_may_use_the_whole_capture_timeout(self):
        # CI saw a cold Chrome start take over 20 s; startup must not have a shorter limit.
        seen = {}

        def fake_debug_port(profile, process, deadline):
            seen["budget"] = deadline - bc.time.monotonic()
            raise bc.CaptureError("stop here")

        with patch.object(bc, "_debug_port", fake_debug_port):
            with self.assertRaises(bc.CaptureError):
                bc.capture_responses("https://example.test/", lambda url: None, browser=sys.executable, timeout=90)
        self.assertGreater(seen["budget"], 80)

    def test_browser_that_exits_early_fails_at_once(self):
        process = type("P", (), {"returncode": 1, "poll": lambda self: 1})()
        with tempfile.TemporaryDirectory() as profile:
            started = bc.time.monotonic()
            with self.assertRaisesRegex(bc.CaptureError, "exited before it was ready"):
                bc._debug_port(Path(profile), process, started + 60)
        self.assertLess(bc.time.monotonic() - started, 5)


class ScriptedPeer:
    """Stands in for the DevTools WebSocket: replies to commands, then plays events."""

    def __init__(self, events, bodies):
        self.events, self.bodies, self.sent, self.queue = list(events), bodies, [], []

    def send(self, message):
        self.sent.append(message)
        method, ident = message["method"], message["id"]
        if method == "Target.createTarget":
            self.queue.append({"id": ident, "result": {"targetId": "T"}})
        elif method == "Target.attachToTarget":
            self.queue.append({"id": ident, "result": {"sessionId": "S"}})
        elif method == "Network.getResponseBody":
            body = self.bodies[message["params"]["requestId"]]
            self.queue.append({"id": ident, "result": body} if body else
                              {"id": ident, "error": {"message": "No resource"}})
        elif method != "Page.navigate":
            self.queue.append({"id": ident, "result": {}})
        if method == "Page.navigate":
            self.queue.extend(self.events)

    def recv(self, timeout):
        return self.queue.pop(0) if self.queue else None


def response(request, url):
    return [{"method": "Network.requestWillBeSent", "params": {"requestId": request}},
            {"method": "Network.responseReceived", "params": {"requestId": request, "response": {"url": url}}},
            {"method": "Network.loadingFinished", "params": {"requestId": request}}]


class CdpSessionTests(unittest.TestCase):
    def run_session(self, events, bodies, expected=(), headers=None, settle=0.05):
        import time
        peer = ScriptedPeer(events, bodies)
        result = bc._Session(peer, time.monotonic() + 5).run(
            "https://example.test/", lambda url: "match" if "/match/" in url else ("event" if "/event/" in url else None),
            headers or {}, settle, set(expected), lambda message: None)
        return result, peer

    def test_captures_bodies_including_base64_and_ignores_others(self):
        events = (response("1", "https://x.test/other.js") + response("2", "https://x.test/match/a")
                  + response("3", "https://x.test/event/a") + [{"method": "Page.loadEventFired", "params": {}}])
        bodies = {"2": {"body": "M", "base64Encoded": False},
                  "3": {"body": base64.b64encode(b"E").decode(), "base64Encoded": True}}
        result, peer = self.run_session(events, bodies, headers={"User-Agent": "UA", "Referer": "r"})
        self.assertEqual(result, {"match": "M", "event": "E"})
        methods = [message["method"] for message in peer.sent]
        self.assertIn("Network.setUserAgentOverride", methods)
        extra = next(m for m in peer.sent if m["method"] == "Network.setExtraHTTPHeaders")["params"]["headers"]
        self.assertEqual(extra, {"Referer": "r"})
        self.assertTrue(all(m.get("sessionId") == "S" for m in peer.sent if m["method"].startswith(("Network", "Page"))))

    def test_first_response_of_a_kind_wins_and_failures_are_skipped(self):
        failed = [{"method": "Network.requestWillBeSent", "params": {"requestId": "1"}},
                  {"method": "Network.responseReceived", "params": {"requestId": "1", "response": {"url": "https://x.test/match/a"}}},
                  {"method": "Network.loadingFailed", "params": {"requestId": "1"}}]
        events = failed + response("2", "https://x.test/match/b") + response("3", "https://x.test/match/c")
        events += [{"method": "Page.loadEventFired", "params": {}}]
        result, peer = self.run_session(events, {"2": {"body": "B"}, "3": {"body": "C"}})
        self.assertEqual(result, {"match": "B"})
        fetched = [m["params"]["requestId"] for m in peer.sent if m["method"] == "Network.getResponseBody"]
        self.assertEqual(fetched, ["2"])

    def test_stops_as_soon_as_expected_kinds_arrive(self):
        events = response("1", "https://x.test/match/a") + response("2", "https://x.test/event/a")
        result, peer = self.run_session(events, {"1": {"body": "M"}, "2": {"body": "E"}}, expected={"match"})
        self.assertEqual(result, {"match": "M"})

    def test_waits_for_quiet_network_after_load(self):
        # A load event followed by more requests (an interstitial reloads the page).
        events = ([{"method": "Page.loadEventFired", "params": {}}]
                  + response("1", "https://x.test/match/a") + [{"method": "Page.loadEventFired", "params": {}}])
        result, _ = self.run_session(events, {"1": {"body": "M"}})
        self.assertEqual(result, {"match": "M"})

    def test_body_errors_are_not_captured(self):
        events = response("1", "https://x.test/match/a") + [{"method": "Page.loadEventFired", "params": {}}]
        result, _ = self.run_session(events, {"1": None})
        self.assertEqual(result, {})


class ScoreswayFallbackTests(unittest.TestCase):
    URL = ("https://www.scoresway.com/en_GB/soccer/uefa-champions-league-2026-2027/99jev9kv55deht65t6myggxlg/"
           "match/sabah-vs-borussia-dortmund/5jw1jlw8iscij2mmc7rz17f9w/match-summary")

    def test_match_id_is_the_opta_id_not_the_team_slug(self):
        self.assertEqual(scoresway.extract_match_id(self.URL), "5jw1jlw8iscij2mmc7rz17f9w")
        self.assertEqual(scoresway.extract_match_id("https://www.scoresway.com/match/view/abc123"), "abc123")

    def test_feed_kinds_respect_the_match_id(self):
        base = "https://api.performfeeds.com/soccerdata"
        self.assertEqual(scoresway.performfeeds_kind(f"{base}/match/key/mid?_fmt=jsonp", "mid"), "match")
        self.assertEqual(scoresway.performfeeds_kind(f"{base}/matchevent/key/mid", "mid"), "matchevent")
        self.assertIsNone(scoresway.performfeeds_kind(f"{base}/match/key/?tmcl=season", "mid"))
        self.assertIsNone(scoresway.performfeeds_kind(f"{base}/match/key/other", "mid"))
        self.assertIsNone(scoresway.performfeeds_kind(f"{base}/commentary/key/mid", "mid"))

    def test_event_feed_is_derived_from_the_captured_match_feed(self):
        match_url = "https://api.performfeeds.com/soccerdata/match/key/mid?_rt=c&_fmt=jsonp"

        def capture(url, classify, **options):
            self.assertEqual(options["expected"], {"match"})
            self.assertEqual(classify(match_url), "match")
            return {"match": "MATCH"}
        with patch("browser_capture.capture_responses", side_effect=capture), \
                patch.object(scoresway, "_fetch_url", return_value="EVENTS") as fetch:
            self.assertEqual(scoresway.discover_with_browser(self.URL, match_id="mid"), ("MATCH", "EVENTS"))
        fetch.assert_called_once_with("https://api.performfeeds.com/soccerdata/matchevent/key/mid?_rt=c&_lcl=en&_fmt=json")

    def test_static_discovery_never_starts_a_browser(self):
        feeds = {"match": "https://m", "matchevent": "https://e"}
        with patch.object(scoresway, "discover_scoresway_feed_urls", return_value=feeds), \
                patch.object(scoresway, "_fetch_url", side_effect=["M", "E"]), \
                patch.object(scoresway, "discover_with_browser") as browser:
            self.assertEqual(scoresway.fetch_scoresway_feed_data(self.URL)[:2], ("M", "E"))
        browser.assert_not_called()

    def test_missing_browser_is_reported_not_skipped(self):
        with patch.object(scoresway, "discover_scoresway_feed_urls", return_value={}), \
                patch("browser_capture.find_browser", return_value=None):
            with self.assertRaisesRegex(ValueError, "did not list its data feeds.*Install Microsoft Edge or Google Chrome"):
                scoresway.fetch_scoresway_feed_data(self.URL)


class FeedPage(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            body = (b"<script>setTimeout(() => { fetch('/soccerdata/match/key/mid?_fmt=json');"
                    b" fetch('/soccerdata/matchevent/key/mid'); fetch('/other.json'); }, 200)</script>")
            kind = "text/html"
        else:
            body = ('{"feed": "%s"}' % self.path.split("?")[0]).encode() + b" " * 200_000
            kind = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class InstalledBrowserIntegrationTests(unittest.TestCase):
    def test_real_browser_captures_feeds_and_cleans_up(self):
        browser = bc.find_browser()
        if not browser:
            if os.environ.get("VIZORPLAY_REQUIRE_BROWSER_TEST") == "1":
                self.fail("No Edge/Chrome/Chromium/Brave found; the scraper fallback is untested here")
            self.skipTest("No Chromium-family browser installed")
        server = ThreadingHTTPServer(("127.0.0.1", 0), FeedPage)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        profiles = []
        original = tempfile.mkdtemp

        def mkdtemp(*args, **kwargs):
            profiles.append(Path(original(*args, **kwargs)))
            return str(profiles[-1])
        with patch.object(bc.tempfile, "mkdtemp", side_effect=mkdtemp):
            captured = bc.capture_responses(
                f"http://127.0.0.1:{server.server_address[1]}/",
                lambda url: scoresway.performfeeds_kind(url.replace(f"127.0.0.1:{server.server_address[1]}",
                                                                    "api.performfeeds.com"), "mid"),
                browser=browser, timeout=60, settle=1, expected={"match", "matchevent"})
        self.assertEqual(set(captured), {"match", "matchevent"})
        self.assertTrue(captured["match"].startswith('{"feed": "/soccerdata/match/key/mid"}'))
        self.assertEqual(len(captured["matchevent"]), len('{"feed": "/soccerdata/matchevent/key/mid"}') + 200_000)
        self.assertEqual(len(profiles), 1)
        self.assertFalse(profiles[0].exists(), "temporary browser profile left behind")


if __name__ == "__main__":
    unittest.main()
