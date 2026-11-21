# VizorPlay brand files

Vector versions of the VizorPlay logo, traced from the 1254 × 1254 master PNG.
Each file is a self-contained SVG with a tight viewBox, so it scales to any
size; set only a width or a height where it is used.

| File | What it is |
|---|---|
| `vizorplay-mark.svg` | The glasses with the green play nose, on its own (app icon, favicon, avatars) |
| `vizorplay-wordmark.svg` | "VizorPlay" lettering on its own (headers, footers, the brand panel) |
| `vizorplay-lockup.svg` | Glasses above the wordmark (splash, README, About) |
| `*-on-dark.svg` | The same three with the black parts in off-white `#F4F4F0`, for dark backgrounds |

Colours: ink `#161616`, green `#1C9938`.

The files are in `ui/assets/brand/`. The app shows the wordmark in the brand
panel of every screen and uses the mark as the browser tab icon; the README
uses the lockup. The desktop app icons (`src-tauri/icons/icon.png` and
`icon.ico`) are the mark on a transparent background with the lenses filled
white, so the glasses stay visible on dark taskbars. The chrome football on
the Intake screen carries the mark embossed on its front
(`design/chrome_ball/create_chrome_ball.py --brand VizorPlay`).
