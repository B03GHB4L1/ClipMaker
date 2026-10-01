"""Render WinGet manifests from a tagged Windows installer."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--installer-url", required=True)
    parser.add_argument("--installer-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    version = args.version.lstrip("v")
    if not VERSION_RE.fullmatch(version):
        parser.error("version must contain two to four numeric components")
    if not SHA256_RE.fullmatch(args.installer_sha256):
        parser.error("installer SHA-256 must contain exactly 64 hexadecimal characters")

    parsed_url = urlparse(args.installer_url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "github.com":
        parser.error("installer URL must be an HTTPS github.com URL")

    template_dir = Path(__file__).with_name("winget")
    args.output.mkdir(parents=True, exist_ok=True)
    replacements = {
        "@VERSION@": version,
        "@INSTALLER_URL@": args.installer_url,
        "@INSTALLER_SHA256@": args.installer_sha256.upper(),
    }

    for template in sorted(template_dir.glob("*.yaml.in")):
        rendered = template.read_text(encoding="utf-8")
        for marker, value in replacements.items():
            rendered = rendered.replace(marker, value)
        if "@" in rendered:
            raise ValueError(f"unresolved template marker in {template.name}")
        output_name = template.name.removesuffix(".in")
        (args.output / output_name).write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
