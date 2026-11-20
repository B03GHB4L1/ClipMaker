"""Build the VizorPlay disk image: the app and an Applications shortcut, laid out so a
user drags one onto the other, with a short note about macOS's first-launch prompt.

    python packaging/macos/make_dmg.py --app path/VizorPlay.app --output VizorPlay_1.0.0_aarch64.dmg

dmgbuild (MIT) writes Finder's window layout straight into the image, so this needs no
Finder session and works on a headless CI runner. The image is not notarized: there is no
Apple Developer membership, and the background says so instead of hiding it.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

WINDOW = (660, 420)  # points; the background is drawn at twice this for Retina screens
APP_AT = (170, 175)
APPLICATIONS_AT = (490, 175)
ICON_SIZE = 112

INK = (28, 31, 38)
MUTED = (96, 103, 116)
ACCENT = (41, 98, 255)
PAPER = (246, 247, 249)
NOTE_PANEL = (234, 238, 246)

FONT_CANDIDATES = (
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def load_font(size: int):
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def draw_background(scale: int):
    """The window background at `scale` pixels per point (1 for normal, 2 for Retina)."""
    from PIL import Image, ImageDraw

    width, height = WINDOW[0] * scale, WINDOW[1] * scale
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)

    def centred(text: str, y: float, size: int, fill) -> None:
        font = load_font(size * scale)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((width - (box[2] - box[0])) / 2 - box[0], y * scale), text, font=font, fill=fill)

    centred("Drag VizorPlay into Applications", 28, 22, INK)

    # An arrow between the two icons, pointing at Applications.
    middle = APP_AT[1] * scale
    left, right = (APP_AT[0] + 78) * scale, (APPLICATIONS_AT[0] - 78) * scale
    thick = 5 * scale
    draw.line([(left, middle), (right - 12 * scale, middle)], fill=ACCENT, width=thick)
    draw.polygon([(right, middle), (right - 22 * scale, middle - 15 * scale),
                  (right - 22 * scale, middle + 15 * scale)], fill=ACCENT)

    # The one extra step, stated plainly on the image so it is seen before the first launch.
    top = 268
    draw.rounded_rectangle([30 * scale, top * scale, (WINDOW[0] - 30) * scale, (WINDOW[1] - 24) * scale],
                           radius=12 * scale, fill=NOTE_PANEL)
    centred("The first time you open it, macOS will say it can't check VizorPlay.", top + 16, 14, INK)
    centred("Open System Settings > Privacy & Security, scroll down, and click Open Anyway.", top + 42, 13, MUTED)
    centred("On macOS 14 or earlier: Control-click VizorPlay in Applications, then choose Open.", top + 64, 13, MUTED)
    centred("This only happens the first time.", top + 90, 12, MUTED)
    return image


def build(app: Path, output: Path, volume_name: str) -> None:
    import dmgbuild

    if not (app / "Contents" / "Info.plist").is_file():
        raise SystemExit(f"{app} is not an app bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with tempfile.TemporaryDirectory() as folder:
        # dmgbuild pairs background.png with background@2x.png into one Retina-aware image.
        background = Path(folder) / "background.png"
        draw_background(1).save(background, dpi=(72, 72))
        draw_background(2).save(Path(folder) / "background@2x.png", dpi=(144, 144))
        dmgbuild.build_dmg(
            str(output),
            volume_name,
            settings={
                "format": "UDZO",
                "files": [str(app)],
                "symlinks": {"Applications": "/Applications"},
                "icon_locations": {app.name: APP_AT, "Applications": APPLICATIONS_AT},
                "background": str(background),
                "window_rect": ((200, 160), WINDOW),
                "icon_size": ICON_SIZE,
                "text_size": 13,
                "default_view": "icon-view",
                "show_status_bar": False,
                "show_tab_view": False,
                "show_toolbar": False,
                "show_pathbar": False,
                "show_sidebar": False,
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", type=Path, required=True, help="the finished VizorPlay.app")
    parser.add_argument("--output", type=Path, required=True, help="the .dmg to write")
    parser.add_argument("--volume-name", default="VizorPlay")
    parser.add_argument("--preview", type=Path, help="only write the background image here, for a look")
    args = parser.parse_args()
    if args.preview:
        draw_background(2).save(args.preview)
        return 0
    build(args.app.resolve(), args.output.resolve(), args.volume_name)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
