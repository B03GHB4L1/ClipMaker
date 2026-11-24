"""The oldest macOS each program inside VizorPlay.app can run on.

macOS refuses to load a program (or library) built for a newer macOS than the Mac has, so
the app only opens on a Mac that satisfies the highest requirement among everything inside
it: the app, the frozen engine and every bundled library. Hosted CI has no macOS 11 to 13,
so this reads each file's own declared minimum instead of guessing from the build target.
Used by tests/macos_dmg_smoke.py; the parser is unit-tested on any OS.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

Version = tuple[int, ...]
MACHO_MAGIC = {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
               b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def version_tuple(text: str) -> Version:
    return tuple(int(part) for part in text.split("."))


def parse_minimums(vtool_output: str) -> list[tuple[str | None, Version]]:
    """(architecture, minimum macOS) pairs from `vtool -show-build`; the architecture is
    None for a single-chip file. Only macOS requirements count."""
    found: list[tuple[str | None, Version]] = []
    arch: str | None = None
    command = ""
    platform = ""
    for line in vtool_output.splitlines():
        header = re.search(r"\(architecture (\w+)\)", line)
        if header:
            arch = header.group(1)
            continue
        tokens = line.split()
        if len(tokens) >= 2 and tokens[0] == "cmd":
            command, platform = tokens[1], ""
        elif len(tokens) >= 2 and tokens[0] == "platform":
            platform = tokens[1]
        elif len(tokens) >= 2 and tokens[0] == "minos" and command == "LC_BUILD_VERSION" and platform == "MACOS":
            found.append((arch, version_tuple(tokens[1])))
        elif len(tokens) >= 2 and tokens[0] == "version" and command == "LC_VERSION_MIN_MACOSX":
            found.append((arch, version_tuple(tokens[1])))
    return found


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACHO_MAGIC
    except OSError:
        return False


def minimum_for(path: Path, arch: str) -> Version | None:
    done = subprocess.run(["vtool", "-show-build", str(path)], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        return None  # not a Mach-O file after all (a Java class shares the magic number)
    versions = [version for file_arch, version in parse_minimums(done.stdout) if file_arch in (None, arch)]
    return max(versions) if versions else None


def scan(app: Path, arch: str) -> dict[str, Version]:
    """Every Mach-O file under the app with its declared minimum macOS for `arch`."""
    result: dict[str, Version] = {}
    for folder, _, names in os.walk(app):
        for name in names:
            path = Path(folder) / name
            if path.is_symlink() or not is_macho(path):
                continue
            minimum = minimum_for(path, arch)
            if minimum is not None:
                result[str(path.relative_to(app))] = minimum
    return result


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)
