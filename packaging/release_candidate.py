"""Retain tested bytes and assemble a non-publishing release candidate."""
from __future__ import annotations

import argparse
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
PLATFORMS = {"Windows": ".exe", "Linux": ".deb", "macOS": ".tar.gz"}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate_commit(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("An exact 40-character Git commit is required")


def record_receipt(platform, payload, evidence, output, commit):
    validate_commit(commit)
    if platform not in PLATFORMS or not payload.name.endswith(PLATFORMS[platform]):
        raise ValueError("Unexpected release payload type")
    results = [json.loads(path.read_text(encoding="utf-8")) for path in evidence]
    if not results or any(result.get("status") != "passed" for result in results):
        raise ValueError("Every acceptance result must be passed")
    if platform in {"Windows", "Linux"}:
        if not any(result.get("installed_versions") == ["0.9.0", "1.0.0", "1.0.0"]
                   and result.get("shutdown_verified") and result.get("reinstall_and_uninstall")
                   for result in results):
            raise ValueError("Native upgrade, reinstall, uninstall and shutdown evidence is required")
    elif not any(result.get("installed_versions") == ["0.9.0", "1.0.0"] for result in results):
        raise ValueError("Homebrew upgrade evidence is required")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(payload, output / payload.name)
    receipt = {"schema": 1, "platform": platform, "version": "1.0.0", "commit": commit,
               "payload": payload.name, "sha256": digest(payload), "size": payload.stat().st_size,
               "acceptance": results}
    (output / f"receipt-{platform}.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def verify_receipts(directory, commit):
    validate_commit(commit)
    receipts = []
    for platform, suffix in PLATFORMS.items():
        receipt = json.loads((directory / f"receipt-{platform}.json").read_text(encoding="utf-8"))
        if (receipt.get("schema"), receipt.get("platform"), receipt.get("version"), receipt.get("commit")) != (1, platform, "1.0.0", commit):
            raise ValueError(f"Wrong commit, platform or version in {platform} receipt")
        filename = receipt["payload"]
        if not isinstance(filename, str) or Path(filename).name != filename or "/" in filename or "\\" in filename or not filename.endswith(suffix):
            raise ValueError("Payload must be a flat filename of the expected type")
        payload = directory / filename
        if payload.is_symlink() or digest(payload) != receipt["sha256"] or payload.stat().st_size != receipt["size"]:
            raise ValueError(f"Tested {platform} payload has changed")
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
    base = f"https://github.com/{repository}/releases/download/v1.0.0/"
    source = next(receipt for receipt in receipts if receipt["platform"] == "macOS")
    windows = next(receipt for receipt in receipts if receipt["platform"] == "Windows")
    subprocess.run([sys.executable, str(ROOT / "packaging/render_homebrew_formula.py"),
                    "--version", "1.0.0", "--sha256", source["sha256"],
                    "--source-url", base + quote(source["payload"]), "--output", str(output / "clipmaker.rb")], check=True)
    subprocess.run([sys.executable, str(ROOT / "packaging/render_winget_manifests.py"),
                    "--version", "1.0.0", "--installer-sha256", windows["sha256"],
                    "--installer-url", base + quote(windows["payload"]), "--output", str(output)], check=True)
    manifest = {"schema": 1, "version": "1.0.0", "commit": commit, "published": False,
                "repository": repository, "artifacts": receipts,
                "limits": ["Controlled predecessor uses the same source, not a historical binary",
                           "Unsigned Windows installer may show a security warning",
                           "macOS is a Homebrew source launcher opening the default browser",
                           "Public Homebrew tap and WinGet submissions are separate publication steps",
                           "Linux support verified on Ubuntu 22.04 DEB; RPM is not included",
                           "Skipped live-provider checks do not certify current provider availability"]}
    (output / "candidate-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "INSTALL.md").write_text(
        "# VizorPlay 1.0 candidate\n\n"
        f"Commit: `{commit}`. These are the exact acceptance-tested bytes.\n\n"
        "Verify SHA256SUMS before installing. Windows: run the setup EXE; reinstalling a newer "
        "package preserves local projects. Ubuntu 22.04: `sudo apt install ./VizorPlay_1.0.0_amd64.deb` "
        "(use the actual DEB filename). macOS: the prepared formula requires publication of the "
        "source asset and Homebrew tap before its public install command will work.\n\n"
        "No release, tap update, WinGet submission, signing or automatic updater has been published "
        "by this candidate job. See candidate-manifest.json for acceptance evidence and limits.\n",
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
    candidate = commands.add_parser("assemble")
    candidate.add_argument("--input", type=Path, required=True)
    candidate.add_argument("--output", type=Path, required=True)
    candidate.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "B03GHB4L1/ClipMaker"))
    for command in (receipt, candidate):
        command.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    args = parser.parse_args()
    if args.command == "receipt":
        record_receipt(args.platform, args.payload, args.evidence, args.output, args.commit)
    else:
        assemble(args.input, args.output, args.commit, args.repository)


if __name__ == "__main__":
    main()
