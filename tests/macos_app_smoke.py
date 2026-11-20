"""CI-only launch test for the VizorPlay.app that Homebrew builds on the Mac.

What it proves: the app bundle Homebrew installed is signed (ad hoc) and not
quarantined, opening it starts VizorPlay's engine for that window (through the
formula's launcher, with the projects folder it was given), and closing the
app stops the engine. macOS has no WebDriver for app windows, so the screens
themselves are exercised by tests/browser_smoke.py against the same engine;
this test keeps a screenshot as evidence but does not click through the UI.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))


def descendants(ps_output: str, root: int) -> dict[int, str]:
    """{pid: command} for every process below root in `ps -axo pid=,ppid=,command=` output."""
    children: dict[int, list[tuple[int, str]]] = {}
    for line in ps_output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        children.setdefault(int(parts[1]), []).append((int(parts[0]), parts[2] if len(parts) > 2 else ""))
    found, waiting = {}, [root]
    while waiting:
        for pid, command in children.get(waiting.pop(), []):
            if pid not in found:
                found[pid] = command
                waiting.append(pid)
    return found


def engine_port(ps_output: str, root: int) -> int | None:
    """The port of the VizorPlay engine started by the app (root), if it is running yet.

    Homebrew's launcher runs clipmaker_api_server.py; an app with the frozen engine inside
    (the DMG) runs Contents/Resources/backend/vizorplay-engine directly."""
    for command in descendants(ps_output, root).values():
        if "clipmaker_api_server.py" in command or "/backend/vizorplay-engine" in command:
            match = re.search(r"--port\s+(\d+)", command)
            if match:
                return int(match.group(1))
    return None


def health(port: int) -> dict | None:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
            return json.loads(response.read())
    except (OSError, ValueError):
        return None


def stage(evidence: Path, message: str) -> None:
    print(f"macOS app: {message}", flush=True)
    with (evidence / "stages.log").open("a", encoding="utf-8") as output:
        output.write(f"{time.time():.3f} {message}\n")


def bundle_checks(app: Path) -> dict:
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    executable = app / "Contents" / "MacOS" / info["CFBundleExecutable"]
    assert os.access(executable, os.X_OK), f"App executable missing: {executable}"
    assert info.get("CFBundleIdentifier") == "com.b4l1.clipmaker", info.get("CFBundleIdentifier")
    signature = subprocess.run(["codesign", "--verify", "--strict", "--verbose=2", str(app)],
                               capture_output=True, text=True, timeout=60)
    assert signature.returncode == 0, f"App signature does not verify: {signature.stderr}"
    quarantine = subprocess.run(["xattr", "-p", "com.apple.quarantine", str(app)], capture_output=True, text=True, timeout=15)
    assert quarantine.returncode != 0, "Homebrew's locally built app should not be quarantined"
    # Recorded, not asserted: without an Apple Developer ID the app is not notarized,
    # so Gatekeeper's assessment rejects it; it opens because it was built locally.
    assessment = subprocess.run(["spctl", "--assess", "--type", "execute", "--verbose", str(app)],
                                capture_output=True, text=True, timeout=60)
    return {"executable": str(executable), "version": info.get("CFBundleShortVersionString"),
            "codesign": signature.stderr.strip(), "quarantined": False,
            "gatekeeper_assessment": (assessment.stderr or assessment.stdout).strip(),
            "gatekeeper_accepted": assessment.returncode == 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True, help="VizorPlay.app installed by Homebrew")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1200)
    args = parser.parse_args()
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    from process_owner import wait_for_process_exit

    result: dict = {"status": "failed", "app": str(args.app)}
    app_process = None
    try:
        result["bundle"] = bundle_checks(args.app)
        stage(evidence, f"bundle verified: {result['bundle']['codesign']}")
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            env = {**os.environ, "VIZORPLAY_DATA_DIR": str(data_dir), "RUST_BACKTRACE": "1"}
            app_process = subprocess.Popen([result["bundle"]["executable"]], env=env,
                                           stdout=(evidence / "app.log").open("w"), stderr=subprocess.STDOUT)
            stage(evidence, f"app started, pid {app_process.pid}")
            deadline = time.monotonic() + args.timeout_seconds
            port = state = None
            while time.monotonic() < deadline:
                if app_process.poll() is not None:
                    log = (evidence / "app.log").read_text(encoding="utf-8", errors="replace")[:6000]
                    raise AssertionError(f"The app exited with {app_process.returncode}. Its log:\n{log}")
                listing = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, timeout=15).stdout
                port = port or engine_port(listing, app_process.pid)
                state = health(port) if port else None
                if state and state.get("status") == "ok":
                    break
                time.sleep(1)
            assert state, "The app's engine did not answer in time"
            assert state.get("desktop_owner_pid") == app_process.pid, f"Engine belongs to another process: {state}"
            stage(evidence, f"engine answered on port {port}: {state}")
            created = Request(f"http://127.0.0.1:{port}/api/projects", data=b'{"name": "macOS app launch"}',
                              headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(created, timeout=10) as response:
                project = json.loads(response.read())["project"]
            saved = data_dir / "projects" / project["id"] / "project.json"
            assert saved.is_file(), "The engine did not save projects in the folder the app was given"
            stage(evidence, f"project saved at {saved}")
            with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                assert b"VizorPlay" in response.read(), "The engine did not serve the VizorPlay page"
            time.sleep(5)  # let the window navigate to the engine before the screenshot
            shot = subprocess.run(["screencapture", "-x", str(evidence / "window.png")], capture_output=True, text=True, timeout=30)
            result["screenshot"] = "window.png" if shot.returncode == 0 else f"unavailable: {shot.stderr.strip()}"
            result["engine"] = state

            app_process.send_signal(signal.SIGTERM)
            app_process.wait(timeout=30)
            stopped = {key: wait_for_process_exit(state[key], timeout=30) for key in ("pid", "parent_pid")}
            result["engine_stopped"] = stopped
            assert all(stopped.values()), f"Engine still running after the app closed: {stopped}"
            stage(evidence, "app closed and its engine stopped")
        result["status"] = "passed"
        return 0
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if app_process and app_process.poll() is None:
            app_process.kill()
        (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
