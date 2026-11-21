"""Whether a newer VizorPlay release exists, and how this install should get it.

The engine checks the release feed once per run. Installing is not done here:
on Windows the desktop shell downloads, verifies and installs the signed
installer; Linux packages and Homebrew get a notice with the way to update.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import webbrowser
from typing import Callable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

CURRENT_VERSION = "1.0.0"
RELEASES_URL = "https://github.com/B03GHB4L1/ClipMaker/releases/latest"
DEFAULT_FEED = RELEASES_URL + "/download/latest.json"
MAX_FEED_BYTES = 64 * 1024
# The desktop shell installs only Windows updates itself; this is the feed key
# its updater looks for.
WINDOWS_TARGET = "windows-x86_64"


def parse_version(value: object) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})", str(value).strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def feed_url(env: Mapping[str, str] = os.environ) -> str:
    """The feed address; VIZORPLAY_UPDATE_URL replaces it for acceptance tests."""
    url = env.get("VIZORPLAY_UPDATE_URL") or DEFAULT_FEED
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("The update feed must be an https address.")
    return url


def install_method(platform: str, desktop: bool) -> str:
    """How this install updates: in the app, with Homebrew, or by downloading."""
    if desktop and platform == "win32":
        return "in-app"
    if platform == "darwin":
        return "homebrew"
    return "download"


def fetch_feed(url: str, timeout: float = 6.0) -> bytes:
    request = Request(url, headers={"User-Agent": "VizorPlay update check", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - https only, see feed_url
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("The update feed is unexpectedly large.")
    return data


def check(env: Mapping[str, str] = os.environ, platform: str = sys.platform, desktop: bool = False,
          fetch: Callable[[str], bytes] = fetch_feed) -> dict:
    status = {"available": False, "current": CURRENT_VERSION,
              "install": install_method(platform, desktop), "release_url": RELEASES_URL}
    if env.get("VIZORPLAY_UPDATE_CHECK") == "0":
        status["disabled"] = True
        return status
    try:
        feed = json.loads(fetch(feed_url(env)))
        if not isinstance(feed, dict):
            raise ValueError("The update feed is not an object.")
        latest = parse_version(feed.get("version"))
        if latest is None:
            raise ValueError("The update feed has no valid version.")
    except (OSError, ValueError) as error:  # offline, no release yet, or a bad feed
        status["error"] = f"Could not check for updates ({error})."
        return status
    status["latest"] = "%d.%d.%d" % latest
    status["available"] = latest > parse_version(CURRENT_VERSION)  # type: ignore[operator]
    notes = feed.get("notes")
    status["notes"] = notes[:500] if isinstance(notes, str) else ""
    platforms = feed.get("platforms")
    if status["install"] == "in-app" and not (isinstance(platforms, dict) and WINDOWS_TARGET in platforms):
        status["install"] = "download"  # no signed Windows package to install in the app
    return status


class UpdateStatus:
    """One feed check per engine run, shared by every page that asks."""

    def __init__(self, desktop: bool, checker: Callable[..., dict] = check):
        self._desktop = desktop
        self._checker = checker
        self._lock = threading.Lock()
        self._status: dict | None = None

    def get(self) -> dict:
        with self._lock:
            if self._status is None:
                self._status = self._checker(desktop=self._desktop)
            return dict(self._status)


# The match sources named on the Intake screen; only these can be opened.
SOURCE_SITES = {"scoresway": "https://www.scoresway.com/", "whoscored": "https://www.whoscored.com/"}


def open_source_site(site: str, opener: Callable[[str], bool] | None = None) -> bool:
    """Open a match source's home page in the user's browser (never a caller-supplied URL)."""
    if site not in SOURCE_SITES:
        raise ValueError("Unknown match source.")
    return bool((opener or webbrowser.open)(SOURCE_SITES[site]))


def open_release_page(opener: Callable[[str], bool] | None = None) -> bool:
    """Open the fixed releases page in the user's browser (never a caller-supplied URL)."""
    return bool((opener or webbrowser.open)(RELEASES_URL))
