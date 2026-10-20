"""Render the Homebrew formula after a release tag has been published."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-url", help="Override the archive URL for a local installation test")
    args = parser.parse_args()
    version = args.version.lstrip("v")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version):
        parser.error("version must contain two to four numeric components")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
        parser.error("SHA-256 must contain exactly 64 hexadecimal characters")

    template = Path(__file__).with_name("homebrew") / "clipmaker.rb.in"
    rendered = template.read_text(encoding="utf-8")
    rendered = rendered.replace("@VERSION@", args.version.lstrip("v"))
    rendered = rendered.replace("@SHA256@", args.sha256.lower())
    if args.source_url:
        if urlparse(args.source_url).scheme not in {"file", "https"} or any(char in args.source_url for char in ('"', '\n', '\r', '\\', '#{')):
            parser.error("source URL must be an HTTPS or file URL without Ruby string escapes")
        rendered = rendered.replace(
            f'https://github.com/B03GHB4L1/ClipMaker/archive/refs/tags/v{args.version.lstrip("v")}.tar.gz',
            args.source_url,
        )
        rendered = rendered.replace('  sha256 "', f'  version "{version}"\n  sha256 "', 1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
