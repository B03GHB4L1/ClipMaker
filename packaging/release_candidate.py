"""Retain tested bytes and assemble a non-publishing release candidate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
# "macOS" is the Homebrew source archive; the two disk images are the Mac downloads.
PLATFORMS = {"Windows": ".exe", "Linux": ".deb", "macOS": ".tar.gz",
             "macOS-AppleSilicon": ".dmg", "macOS-Intel": ".dmg"}
# The Intel disk image is still being tested: it is attached when it passed, and
# its absence does not block the other packages.
OPTIONAL_PLATFORMS = {"macOS-Intel"}
DISK_IMAGES = {"macOS-AppleSilicon": ("aarch64", "arm64"), "macOS-Intel": ("x64", "x86_64")}
# Feed keys the desktop updater looks up; Windows and Linux update from their own package.
UPDATER_TARGETS = {"Windows": "windows-x86_64", "Linux": "linux-x86_64"}
# The Mac disk-image app updates from a signed archive of the same VizorPlay.app that is inside
# the disk image (the disk image itself is only for first installs).
MAC_UPDATER_TARGETS = {"macOS-AppleSilicon": "darwin-aarch64", "macOS-Intel": "darwin-x86_64"}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate_commit(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("An exact 40-character Git commit is required")


def read_signature(path):
    """The minisign signature Tauri writes beside a signed installer (<installer>.sig)."""
    text = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9+/=]{40,4096}", text):
        raise ValueError("Updater signature is not a Tauri signature file")
    return text


def update_verified(results):
    return any(result.get("update_installed") and result.get("bad_signature_rejected") for result in results)


def record_receipt(platform, payload, evidence, output, commit, signature=None, updater_archive=None):
    validate_commit(commit)
    if platform not in PLATFORMS or not payload.name.endswith(PLATFORMS[platform]):
        raise ValueError("Unexpected release payload type")
    if platform in MAC_UPDATER_TARGETS:
        if (signature is None) != (updater_archive is None):
            raise ValueError("A Mac update archive and its signature go together")
        if updater_archive is not None and updater_archive.name != payload.name.replace(".dmg", ".app.tar.gz"):
            raise ValueError(f"Unexpected Mac update archive name {updater_archive.name}")
    elif updater_archive is not None:
        raise ValueError("Only the Mac disk-image apps have an update archive")
    elif signature is not None and platform not in UPDATER_TARGETS:
        raise ValueError("Only the Windows installer, the Linux .deb and the Mac update archives are installed by the in-app updater")
    results = [json.loads(path.read_text(encoding="utf-8")) for path in evidence]
    if not results or any(result.get("status") != "passed" for result in results):
        raise ValueError("Every acceptance result must be passed")
    if platform in {"Windows", "Linux"}:
        if not any(result.get("installed_versions") == ["0.9.0", "1.0.0", "1.0.0"]
                   and result.get("shutdown_verified") and result.get("reinstall_and_uninstall")
                   for result in results):
            raise ValueError("Native upgrade, reinstall, uninstall and shutdown evidence is required")
    elif platform in DISK_IMAGES:
        suffix, arch = DISK_IMAGES[platform]
        if payload.name != f"VizorPlay_1.0.0_{suffix}.dmg":
            raise ValueError(f"Unexpected disk image name {payload.name}")
        if not any(result.get("dmg") == payload.name and result.get("expected_arch") == arch
                   and result.get("architectures") == arch and result.get("needs_newer_than_promised") == {}
                   for result in results):
            raise ValueError("Evidence that this disk image was mounted, opened and stopped on the right chip is required")
    else:
        if not any(result.get("installed_versions") == ["0.9.0", "1.0.0"] for result in results):
            raise ValueError("Homebrew upgrade evidence is required")
        if not any(result.get("engine_stopped") and all(result["engine_stopped"].values()) for result in results):
            raise ValueError("Evidence that the Homebrew-built VizorPlay.app starts and stops its engine is required")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(payload, output / payload.name)
    if updater_archive is not None:
        shutil.copy2(updater_archive, output / updater_archive.name)
    receipt = {"schema": 1, "platform": platform, "version": "1.0.0", "commit": commit,
               "payload": payload.name, "sha256": digest(payload), "size": payload.stat().st_size,
               "acceptance": results}
    if updater_archive is not None:
        receipt["updater_archive"] = {"name": updater_archive.name, "sha256": digest(updater_archive),
                                      "size": updater_archive.stat().st_size}
    if signature is not None:
        receipt["updater_signature"] = read_signature(signature)
    (output / f"receipt-{platform}.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def verify_receipts(directory, commit):
    validate_commit(commit)
    receipts = []
    for platform, suffix in PLATFORMS.items():
        path = directory / f"receipt-{platform}.json"
        if platform in OPTIONAL_PLATFORMS and not path.exists():
            continue
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if (receipt.get("schema"), receipt.get("platform"), receipt.get("version"), receipt.get("commit")) != (1, platform, "1.0.0", commit):
            raise ValueError(f"Wrong commit, platform or version in {platform} receipt")
        filename = receipt["payload"]
        if not isinstance(filename, str) or Path(filename).name != filename or "/" in filename or "\\" in filename or not filename.endswith(suffix):
            raise ValueError("Payload must be a flat filename of the expected type")
        payload = directory / filename
        if payload.is_symlink() or digest(payload) != receipt["sha256"] or payload.stat().st_size != receipt["size"]:
            raise ValueError(f"Tested {platform} payload has changed")
        archive = receipt.get("updater_archive")
        if archive is not None:
            name = archive.get("name") if isinstance(archive, dict) else None
            if (platform not in MAC_UPDATER_TARGETS or not isinstance(name, str) or Path(name).name != name
                    or "/" in name or "\\" in name or name != filename.replace(".dmg", ".app.tar.gz")):
                raise ValueError("The update archive must be a flat filename that matches its disk image")
            tested = directory / name
            if tested.is_symlink() or digest(tested) != archive.get("sha256") or tested.stat().st_size != archive.get("size"):
                raise ValueError(f"Tested {platform} update archive has changed")
            if not receipt.get("updater_signature"):
                raise ValueError(f"The {platform} update archive has no signature")
        receipts.append(receipt)
    return receipts


def assemble(directory, output, commit, repository):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected an owner/repository GitHub identifier")
    receipts = verify_receipts(directory, commit)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Candidate output must be empty; refusing to overwrite earlier candidates")
    output.mkdir(parents=True, exist_ok=True)
    for receipt in receipts:
        shutil.copy2(directory / receipt["payload"], output / receipt["payload"])
        shutil.copy2(directory / f"receipt-{receipt['platform']}.json", output / f"receipt-{receipt['platform']}.json")
        if "updater_archive" in receipt:
            shutil.copy2(directory / receipt["updater_archive"]["name"], output / receipt["updater_archive"]["name"])
    base = f"https://github.com/{repository}/releases/download/v1.0.0/"
    source = next(receipt for receipt in receipts if receipt["platform"] == "macOS")
    windows = next(receipt for receipt in receipts if receipt["platform"] == "Windows")
    linux = next(receipt for receipt in receipts if receipt["platform"] == "Linux")
    if not windows.get("updater_signature") or not update_verified(windows["acceptance"]):
        raise ValueError("A Windows release needs a signed updater installer and passed in-app update evidence")
    subprocess.run([sys.executable, str(ROOT / "packaging/render_homebrew_formula.py"),
                    "--version", "1.0.0", "--sha256", source["sha256"],
                    "--source-url", base + quote(source["payload"]), "--output", str(output / "vizorplay.rb")], check=True)
    subprocess.run([sys.executable, str(ROOT / "packaging/render_winget_manifests.py"),
                    "--version", "1.0.0", "--installer-sha256", windows["sha256"],
                    "--installer-url", base + quote(windows["payload"]), "--output", str(output)], check=True)
    if not linux.get("updater_signature"):
        raise ValueError("A Linux release needs a signed .deb for in-app updates")
    platforms = {UPDATER_TARGETS[receipt["platform"]]: {"signature": receipt["updater_signature"],
                                                        "url": base + quote(receipt["payload"])}
                 for receipt in (windows, linux)}
    # Mac: the Apple Silicon archive is required; the Intel one is listed when that image passed.
    for receipt in receipts:
        if receipt["platform"] in MAC_UPDATER_TARGETS and "updater_archive" in receipt:
            platforms[MAC_UPDATER_TARGETS[receipt["platform"]]] = {
                "signature": receipt["updater_signature"], "url": base + quote(receipt["updater_archive"]["name"])}
    if "darwin-aarch64" not in platforms:
        raise ValueError("A Mac release needs a signed update archive for Apple Silicon")
    # The feed every installed copy reads (releases/latest/download/latest.json).
    feed = {"version": "1.0.0", "notes": "See the release page for what changed.",
            "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "platforms": platforms}
    (output / "latest.json").write_text(json.dumps(feed, indent=2) + "\n", encoding="utf-8")
    manifest = {"schema": 1, "version": "1.0.0", "commit": commit, "published": False,
                "repository": repository, "artifacts": receipts,
                "limits": ["Controlled predecessor uses the same source, not a historical binary",
                           "Unsigned Windows installer may show a security warning",
                           "macOS: the disk images are ad hoc signed and not notarized, so the first launch needs Open Anyway; Homebrew builds VizorPlay.app on the Mac instead",
                           "The Intel (x64) disk image is included only when it passed its tests; real Macs and macOS 11 to 13 are not tested",
                           "In-app updates: Windows, Linux and the Mac disk-image app install them; the Mac update has not been tried on a real Mac, and a Homebrew install updates with brew",
                           "Public Homebrew tap and WinGet submissions are separate publication steps",
                           "Linux support verified on Ubuntu 22.04 DEB; RPM is not included",
                           "Skipped live-provider checks do not certify current provider availability"]}
    (output / "candidate-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "INSTALL.md").write_text(
        "# VizorPlay 1.0 candidate\n\n"
        f"Commit: `{commit}`. These are the exact acceptance-tested bytes.\n\n"
        "Verify SHA256SUMS before installing. Windows: run the setup EXE; reinstalling a newer "
        "package preserves local projects. Ubuntu 22.04: `sudo apt install ./VizorPlay_1.0.0_amd64.deb` "
        "(use the actual DEB filename). macOS: open the disk image for your chip (aarch64 for Apple Silicon, x64 for Intel, "
        "if present), drag VizorPlay onto Applications and use Open Anyway the first time (it is "
        "not notarized). The Homebrew formula requires publication of the "
        "source asset and Homebrew tap before its public install command will work.\n\n"
        "latest.json is the update feed: once it is published with the release, installed Windows, "
        "Linux and Mac (disk image) copies offer the update in the app; a Homebrew install shows a notice.\n\n"
        "No release, tap update or WinGet submission has been published by this candidate job. "
        "See candidate-manifest.json for acceptance evidence and limits.\n",
        encoding="utf-8")
    lines = [f"{digest(path)}  {path.relative_to(output).as_posix()}\n"
             for path in sorted(output.rglob("*")) if path.is_file()]
    (output / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--platform", choices=PLATFORMS, required=True)
    receipt.add_argument("--payload", type=Path, required=True)
    receipt.add_argument("--evidence", type=Path, action="append", required=True)
    receipt.add_argument("--output", type=Path, required=True)
    receipt.add_argument("--signature", type=Path, help="Windows, Linux and Mac: the updater .sig file")
    receipt.add_argument("--updater-archive", type=Path, help="Mac disk images: the signed VizorPlay .app.tar.gz")
    candidate = commands.add_parser("assemble")
    candidate.add_argument("--input", type=Path, required=True)
    candidate.add_argument("--output", type=Path, required=True)
    candidate.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "B03GHB4L1/VizorPlay"))
    for command in (receipt, candidate):
        command.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    args = parser.parse_args()
    if args.command == "receipt":
        record_receipt(args.platform, args.payload, args.evidence, args.output, args.commit, args.signature, args.updater_archive)
    else:
        assemble(args.input, args.output, args.commit, args.repository)


if __name__ == "__main__":
    main()
