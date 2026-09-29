"""Render the Homebrew formula after a release tag has been published."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    template = Path(__file__).with_name("homebrew") / "clipmaker.rb.in"
    rendered = template.read_text(encoding="utf-8")
    rendered = rendered.replace("@VERSION@", args.version.lstrip("v"))
    rendered = rendered.replace("@SHA256@", args.sha256.lower())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
