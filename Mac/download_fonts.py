"""
ClipMaker — Font Downloader
Run this once to download all fonts locally (eliminates Google Fonts network requests).

Usage:
    python download_fonts.py
"""

import os
import re
import urllib.request

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")

GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2[CLR]"
    "family=Iosevka+Charon+Mono:ital,wght@0,300;0,400;0,500;0,700;1,400;1,500"
    "&family=Inter:wght@400;500;600;700;800;900"
    "&family=JetBrains+Mono:wght@400;500"
    "&display=swap"
)

# Spoof a modern browser so Google Fonts returns woff2 URLs
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    os.makedirs(FONT_DIR, exist_ok=True)
    print("Fetching font CSS from Google Fonts...")

    css_bytes = fetch(GOOGLE_FONTS_URL, HEADERS)
    css = css_bytes.decode("utf-8")

    # Extract all woff2 URLs and their font-face context
    font_faces = re.findall(
        r"/\*\s*([\w\s\-]+[CLR])\s*\*/.*[CLR]font-style:\s*(\w+).*[CLR]font-weight:\s*(\w+).*[CLR]url\((https://[^)]+\.woff2)\)",
        css, re.DOTALL
    )

    if not font_faces:
        # Fallback: just grab all woff2 URLs
        urls = re.findall(r"url\((https://[^\)]+\.woff2)\)", css)
        font_faces = [(f"font_{i}", "normal", "400", url) for i, url in enumerate(urls)]

    print(f"Found {len(font_faces)} font files to download.\n")

    downloaded = []
    for family, style, weight, url in font_faces:
        family_clean = re.sub(r"\s+", "-", family.strip())
        style_suffix = "-italic" if style == "italic" else ""
        filename = f"{family_clean}-{weight}{style_suffix}.woff2"
        dest = os.path.join(FONT_DIR, filename)

        if os.path.exists(dest):
            print(f"  [skip] {filename} (already exists)")
            downloaded.append((family.strip(), style, weight, filename))
            continue

        try:
            data = fetch(url)
            with open(dest, "wb") as f:
                f.write(data)
            print(f"  [OK]   {filename} ({len(data)//1024}KB)")
            downloaded.append((family.strip(), style, weight, filename))
        except Exception as e:
            print(f"  [FAIL] {filename}: {e}")

    # Write a local CSS file referencing the downloaded fonts
    css_out = []
    for family, style, weight, filename in downloaded:
        css_out.append(f"""@font-face {{
  font-family: '{family}';
  font-style: {style};
  font-weight: {weight};
  font-display: swap;
  src: url('app/static/fonts/{filename}') format('woff2');
}}""")

    local_css_path = os.path.join(FONT_DIR, "fonts.css")
    with open(local_css_path, "w") as f:
        f.write("\n\n".join(css_out))

    print(f"\nDone. {len(downloaded)} fonts saved to: {FONT_DIR}")
    print("Restart ClipMaker — fonts will now load locally with no internet required.")


if __name__ == "__main__":
    main()
