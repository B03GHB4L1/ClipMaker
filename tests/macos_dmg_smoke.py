"""CI-only check of the VizorPlay disk image a Mac user downloads.

What it proves, in the order a user meets it: the image verifies and mounts; it holds
VizorPlay.app plus an Applications shortcut, with the drag-to-Applications layout;
copying the app out of it (what dragging does) gives a signed app built for the expected
chip; the app opens, starts the engine bundled inside it with the projects folder it was
given, and closing it stops the engine. Gatekeeper's verdict on a downloaded (quarantined)
copy is recorded, not asserted: with no Apple Developer membership the app is not
notarized, so macOS asks for the one-time "Open Anyway" step the install guide describes.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from macos_min_os import format_version, scan  # noqa: E402

# The oldest macOS the install guide promises; nothing inside the app may need a newer one.
PROMISED_MINIMUM = (11, 0)


def run(*command: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, timeout=timeout)


def check(command: list[str], what: str) -> str:
    done = run(*command)
    assert done.returncode == 0, f"{what} failed: {(done.stderr or done.stdout).strip()}"
    return (done.stdout or done.stderr).strip()


def stage(evidence: Path, message: str) -> None:
    print(f"macOS dmg: {message}", flush=True)
    with (evidence / "stages.log").open("a", encoding="utf-8") as output:
        output.write(message + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dmg", type=Path, required=True)
    parser.add_argument("--expect-arch", choices=("arm64", "x86_64"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence
    evidence.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["version"]
    result: dict = {"status": "failed", "dmg": args.dmg.name, "expected_arch": args.expect_arch}
    mountpoint = None
    result["host_macos"] = run("sw_vers", "-productVersion").stdout.strip()
    try:
        assert args.dmg.name == f"VizorPlay_{version}_{'aarch64' if args.expect_arch == 'arm64' else 'x64'}.dmg", \
            f"Unexpected file name {args.dmg.name} for version {version}"
        check(["hdiutil", "verify", str(args.dmg)], "Disk image check")
        stage(evidence, "disk image verifies")
        with tempfile.TemporaryDirectory() as directory:
            mountpoint = Path(directory) / "mounted"
            mountpoint.mkdir()
            check(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mountpoint), str(args.dmg)],
                  "Mounting the disk image")
            listing = sorted(item.name for item in mountpoint.iterdir())
            result["image_contents"] = listing
            assert "VizorPlay.app" in listing, f"The image has no VizorPlay.app: {listing}"
            shortcut = mountpoint / "Applications"
            assert shortcut.is_symlink() and str(shortcut.readlink()) == "/Applications", \
                "The image has no Applications shortcut to drag onto"
            assert (mountpoint / ".DS_Store").is_file(), "The image has no saved window layout (.DS_Store)"
            assert any(name.startswith(".background") for name in (item.name for item in mountpoint.iterdir())), \
                "The image has no background picture"
            stage(evidence, f"image holds {listing}")

            # What dragging does: copy the app out of the image into an Applications folder.
            applications = Path(directory) / "Applications"
            applications.mkdir()
            app = applications / "VizorPlay.app"
            check(["ditto", str(mountpoint / "VizorPlay.app"), str(app)], "Copying the app out of the image")
            check(["hdiutil", "detach", str(mountpoint)], "Unmounting the disk image")
            mountpoint = None

            info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
            assert info["CFBundleShortVersionString"] == version, info["CFBundleShortVersionString"]
            minimum = info.get("LSMinimumSystemVersion")
            result["minimum_macos"] = minimum
            for binary in (app / "Contents" / "MacOS" / info["CFBundleExecutable"],
                           app / "Contents" / "Resources" / "backend" / "vizorplay-engine"):
                archs = check(["lipo", "-archs", str(binary)], f"Reading the chip of {binary.name}").split()
                assert archs == [args.expect_arch], f"{binary.name} is built for {archs}, expected {args.expect_arch}"
            result["architectures"] = args.expect_arch
            check(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], "App signature")
            stage(evidence, f"app {version} is {args.expect_arch}, minimum macOS {minimum}, signature verifies")

            # Hosted CI has no macOS 11 to 13, so read what every file inside the app needs.
            minimums = scan(app, args.expect_arch)
            highest = max(minimums.values())
            too_new = {name: format_version(need) for name, need in sorted(minimums.items()) if need > PROMISED_MINIMUM}
            result["files_checked_for_minimum_macos"] = len(minimums)
            result["highest_minimum_macos"] = format_version(highest)
            result["needs_newer_than_promised"] = too_new
            stage(evidence, f"{len(minimums)} programs and libraries inside the app need macOS {format_version(highest)} or newer")
            assert not too_new, (f"These files need a newer macOS than the promised {format_version(PROMISED_MINIMUM)}, "
                                 f"so the app would not open there: {dict(list(too_new.items())[:12])}")

            # A downloaded copy carries the quarantine flag. Record what Gatekeeper says.
            downloaded = Path(directory) / "downloaded" / "VizorPlay.app"
            downloaded.parent.mkdir()
            check(["ditto", str(app), str(downloaded)], "Copying for the Gatekeeper check")
            check(["xattr", "-w", "com.apple.quarantine", "0081;00000000;Safari;", str(downloaded)], "Marking the copy as downloaded")
            assessment = run("spctl", "--assess", "--type", "execute", "--verbose", str(downloaded), timeout=60)
            result["gatekeeper_downloaded_copy"] = {"accepted": assessment.returncode == 0,
                                                    "verdict": (assessment.stderr or assessment.stdout).strip()}
            stage(evidence, f"Gatekeeper on a downloaded copy: {result['gatekeeper_downloaded_copy']}")

            launch = subprocess.run([sys.executable, str(ROOT / "tests" / "macos_app_smoke.py"), "--app", str(app),
                                     "--evidence", str(evidence / "app"), "--timeout-seconds", "180"], timeout=600)
            assert launch.returncode == 0, "The installed app did not open, serve, and stop its engine"
            stage(evidence, "app opened, its bundled engine answered, and closing the app stopped it")
        result["status"] = "passed"
        return 0
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if mountpoint is not None:
            run("hdiutil", "detach", "-force", str(mountpoint))
        (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
