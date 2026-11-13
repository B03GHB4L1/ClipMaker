"""Capture page network responses with the computer's own Chromium-family browser.

Replaces the bundled Playwright browser (docs/SCRAPER_BROWSER_PLAN.md). Some
pages only reveal their data feeds after their scripts run; this starts an
installed Edge, Chrome, Chromium or Brave headless with a throwaway profile,
drives it over the Chrome DevTools Protocol (CDP) and returns the bodies of the
responses the caller asks for. Only the standard library is used: CDP needs a
WebSocket to 127.0.0.1, implemented minimally below.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

NO_BROWSER_MESSAGE = ("This page needs a browser to read. Install Microsoft Edge or Google Chrome, "
                      "or try again later. (Safari and Firefox cannot be used.)")


class BrowserUnavailable(RuntimeError):
    """No supported browser is installed."""


class CaptureError(RuntimeError):
    """The browser started but the page could not be captured."""


def _candidates(platform: str, env) -> list[str]:
    if platform.startswith("win"):
        roots = [env.get(name) for name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        relative = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                    r"Chromium\Application\chrome.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        return [str(Path(root) / item) for item in relative for root in roots if root]
    if platform == "darwin":
        apps = [("Microsoft Edge", "Microsoft Edge"), ("Google Chrome", "Google Chrome"),
                ("Chromium", "Chromium"), ("Brave Browser", "Brave Browser")]
        homes = ["/Applications", str(Path(env.get("HOME", "~")).expanduser() / "Applications")]
        return [f"{home}/{app}.app/Contents/MacOS/{binary}" for app, binary in apps for home in homes]
    return []


LINUX_NAMES = ["microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
               "chromium", "chromium-browser", "brave-browser"]


def find_browser(env=None, platform: str = sys.platform, exists=os.path.isfile, which=shutil.which) -> Optional[str]:
    """Path of an installed Chromium-family browser, or None.

    ``VIZORPLAY_BROWSER`` may name one explicitly (it must exist)."""
    env = os.environ if env is None else env
    chosen = (env.get("VIZORPLAY_BROWSER") or "").strip()
    if chosen:
        return chosen if exists(chosen) else None
    for path in _candidates(platform, env):
        if exists(path):
            return path
    names = LINUX_NAMES if not platform.startswith("win") and platform != "darwin" else []
    for name in names + ["msedge", "chrome", "chromium"]:
        found = which(name)
        if found:
            return found
    return None


class WebSocket:
    """Minimal RFC 6455 client: text frames to a local CDP endpoint."""

    def __init__(self, port: int, path: str, timeout: float = 10.0) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
                          .encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CaptureError("Browser closed the DevTools connection.")
            response += chunk
        head, self._buffer = response.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise CaptureError("Browser refused the DevTools connection.")

    def _exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self.sock.recv(max(65536, count - len(self._buffer)))
            if not chunk:
                raise CaptureError("Browser closed the DevTools connection.")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _frame(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode])
        size = len(payload)
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", size)
        mask = os.urandom(4)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, message: dict) -> None:
        self._frame(0x1, json.dumps(message).encode("utf-8"))

    def recv(self, timeout: float) -> Optional[dict]:
        """Next message, or None when nothing arrives within ``timeout``."""
        self.sock.settimeout(max(0.01, timeout))
        parts = []
        try:
            while True:
                first, second = self._exact(2)
                opcode, size = first & 0x0F, second & 0x7F
                if size == 126:
                    size = struct.unpack(">H", self._exact(2))[0]
                elif size == 127:
                    size = struct.unpack(">Q", self._exact(8))[0]
                mask = self._exact(4) if second & 0x80 else b""
                payload = self._exact(size)
                if mask:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if opcode == 0x8:
                    raise CaptureError("Browser closed the DevTools connection.")
                if opcode == 0x9:
                    self._frame(0xA, payload)
                    continue
                if opcode in (0x0, 0x1, 0x2):
                    parts.append(payload)
                    if first & 0x80:
                        return json.loads(b"".join(parts).decode("utf-8"))
        except socket.timeout:
            if parts:
                raise CaptureError("Browser sent an incomplete DevTools message.")
            return None

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _debug_port(profile: Path, process: subprocess.Popen, deadline: float) -> tuple[int, str]:
    marker = profile / "DevToolsActivePort"
    while time.monotonic() < deadline:
        try:
            lines = marker.read_text(encoding="utf-8", errors="replace").split() if marker.is_file() else []
        except OSError:
            lines = []  # The browser is still writing it.
        if len(lines) >= 2 and lines[0].isdigit():
            return int(lines[0]), lines[1]
        # Edge's launcher on Windows hands off to a child and exits with 0.
        if process.poll() not in (None, 0):
            raise CaptureError(f"The browser exited before it was ready (code {process.returncode}).")
        time.sleep(0.05)
    raise CaptureError("The browser did not start in time.")


def _kill_profile_processes(profile: Path) -> None:
    """Last resort: end any browser process still using this throwaway profile.

    Needed when the launched process handed off to a child (Edge on Windows)
    and the DevTools Browser.close request could not be delivered."""
    marker = profile.name  # unique random directory name
    if os.name == "nt":
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + marker + "*' } | "
                  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        command = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    else:
        command = ["pkill", "-f", marker]
    try:
        subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        pass


def _remove(profile: Path, attempts: int) -> bool:
    for _ in range(attempts):
        shutil.rmtree(profile, ignore_errors=True)
        if not profile.exists():
            return True
        time.sleep(0.1)
    return False


def _stop(process: subprocess.Popen, profile: Path) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    # A profile still in use means a browser process is alive: end it.
    if not _remove(profile, 30):
        _kill_profile_processes(profile)
        _remove(profile, 30)


def capture_responses(url: str, classify: Callable[[str], Optional[str]], *, headers: Optional[dict] = None,
                      browser: Optional[str] = None, timeout: float = 60.0, settle: float = 3.0,
                      expected: Optional[set] = None,
                      log: Callable[[str], None] = lambda message: None) -> dict[str, str]:
    """Open ``url`` and return {kind: body} for responses ``classify`` names.

    ``classify(response_url)`` returns a kind (e.g. "match") or None to ignore
    the response; the first response of each kind wins. Capture ends when every
    ``expected`` kind is captured, or once the page has loaded and the network
    has been quiet for ``settle`` seconds (pages may pass through an
    interstitial check and load twice), or at ``timeout``. The browser and its
    temporary profile are always removed.
    """
    browser = browser or find_browser()
    if not browser:
        raise BrowserUnavailable(NO_BROWSER_MESSAGE)
    if not str(url).startswith(("http://", "https://")):
        raise ValueError("Only web pages can be captured.")
    profile = Path(tempfile.mkdtemp(prefix="vizorplay-browser-"))
    arguments = [browser, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
                 "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                 "--disable-background-networking", "--disable-sync", "--mute-audio", "about:blank"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=flags)
    except OSError as exc:
        shutil.rmtree(profile, ignore_errors=True)
        raise BrowserUnavailable(f"{NO_BROWSER_MESSAGE} ({exc})") from exc
    deadline = time.monotonic() + timeout
    socket_ = None
    try:
        # A first start on a slow or busy machine can take well over 20 s; a
        # browser that dies is noticed at once, so startup shares the deadline.
        port, path = _debug_port(profile, process, deadline)
        log(f"Started {Path(browser).stem} for network capture.")
        try:
            # A busy machine can be slow to answer the first connection too.
            socket_ = WebSocket(port, path, timeout=max(1.0, deadline - time.monotonic()))
        except OSError as exc:  # includes timeouts
            raise CaptureError(f"The browser did not accept the DevTools connection ({exc}).") from exc
        return _Session(socket_, deadline).run(url, classify, headers or {}, settle, set(expected or ()), log)
    finally:
        if socket_:
            _close_browser(socket_)
        _stop(process, profile)


def _close_browser(socket_: WebSocket) -> None:
    """Ask the browser to exit (all its processes) and wait briefly for it."""
    try:
        socket_.send({"id": 2**31 - 1, "method": "Browser.close"})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            socket_.recv(deadline - time.monotonic())
    except (CaptureError, OSError, ValueError):
        pass  # The connection closing is the expected outcome.
    finally:
        socket_.close()


class _Session:
    def __init__(self, socket_: WebSocket, deadline: float) -> None:
        self.ws, self.deadline, self.next_id = socket_, deadline, 0
        self.session: Optional[str] = None
        self.replies: dict[int, dict] = {}

    def _send(self, method: str, params: Optional[dict] = None, session: bool = True) -> int:
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params or {}}
        if session and self.session:
            message["sessionId"] = self.session
        self.ws.send(message)
        return self.next_id

    def _call(self, method: str, params: Optional[dict] = None, session: bool = True) -> dict:
        ident = self._send(method, params, session)
        while time.monotonic() < self.deadline:
            message = self.ws.recv(self.deadline - time.monotonic())
            if message and message.get("id") == ident:
                if "error" in message:
                    raise CaptureError(f"{method} failed: {message['error'].get('message', '')}")
                return message.get("result", {})
        raise CaptureError("The page did not respond in time.")

    def run(self, url, classify, headers, settle, expected, log) -> dict[str, str]:
        target = self._call("Target.createTarget", {"url": "about:blank"}, session=False)["targetId"]
        self.session = self._call("Target.attachToTarget", {"targetId": target, "flatten": True},
                                  session=False)["sessionId"]
        self._call("Network.enable")
        self._call("Page.enable")
        agent = next((value for key, value in headers.items() if key.lower() == "user-agent"), None)
        if agent:
            self._call("Network.setUserAgentOverride", {"userAgent": agent})
        extra = {key: value for key, value in headers.items() if key.lower() != "user-agent"}
        if extra:
            self._call("Network.setExtraHTTPHeaders", {"headers": extra})
        self._send("Page.navigate", {"url": url})
        kinds: dict[str, str] = {}  # requestId -> kind
        pending: dict[int, str] = {}  # body request id -> kind
        captured: dict[str, str] = {}
        loaded, quiet_since, inflight = False, time.monotonic(), set()
        while time.monotonic() < self.deadline:
            if expected and expected <= set(captured):
                break
            if loaded and not pending and not inflight and time.monotonic() - quiet_since >= settle:
                break
            message = self.ws.recv(min(0.25, self.deadline - time.monotonic()))
            if not message:
                continue
            method, params = message.get("method"), message.get("params") or {}
            if method and method.startswith("Network."):
                quiet_since = time.monotonic()
            if method == "Network.requestWillBeSent":
                inflight.add(params.get("requestId"))
            elif method in ("Network.loadingFinished", "Network.loadingFailed"):
                inflight.discard(params.get("requestId"))
            if method == "Page.loadEventFired":
                loaded, quiet_since = True, time.monotonic()
            elif method == "Network.responseReceived":
                kind = classify(params.get("response", {}).get("url", ""))
                if kind and kind not in captured and kind not in kinds.values() and kind not in pending.values():
                    kinds[params["requestId"]] = kind
            elif method == "Network.loadingFinished" and params.get("requestId") in kinds:
                kind = kinds.pop(params["requestId"])
                pending[self._send("Network.getResponseBody", {"requestId": params["requestId"]})] = kind
            elif method == "Network.loadingFailed" and params.get("requestId") in kinds:
                kinds.pop(params["requestId"])
            elif message.get("id") in pending:
                kind = pending.pop(message["id"])
                result = message.get("result")
                if result is not None and kind not in captured:
                    body = result.get("body", "")
                    captured[kind] = (base64.b64decode(body).decode("utf-8", "replace")
                                      if result.get("base64Encoded") else body)
                    log(f"Captured {kind} feed.")
        return captured
