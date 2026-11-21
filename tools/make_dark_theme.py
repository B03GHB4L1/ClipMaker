"""Write ui/theme-dark.css: a dark version of every colour the app's stylesheets set.

Each rule that sets a colour gets a twin under :root[data-theme="dark"] with the
colour moved to its dark-theme partner: greys flip (paper becomes near-black, ink
becomes near-white), dark brand and team colours are lifted so they read on dark,
and bright colours (the lime accent) stay as they are. Shadows keep their colour.
Hand-tuned rules live in ui/theme.css, which loads after this file.

Run after changing a colour in a stylesheet:  python tools/make_dark_theme.py
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import tinycss2

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ["styles.css", "filters.css", "compact.css", "design.css", "editor.css", "analysis/native.css", "annotate.css", "code.css"]
OUT = ROOT / "ui" / "theme-dark.css"
SCOPE = ':root[data-theme="dark"]'
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(white|black)\b")
SKIP_PROPS = {"box-shadow", "text-shadow", "filter", "-webkit-box-shadow", "caret-color"}
COLOR_PROPS = re.compile(r"(^|-)(color|background|border|outline|fill|stroke|shadow|accent|decoration)|^--")
NOT_COLOR_PROPS = re.compile(r"-(radius|width|style|collapse|spacing|size|position|repeat|attachment|origin|clip|offset|blend-mode|line|thickness)$|^border-image")


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def to_oklch(r, g, b):
    r, g, b = (_lin(v / 255) for v in (r, g, b))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(a, bb), math.atan2(bb, a)


def from_oklch(L, C, h):
    a, b = C * math.cos(h), C * math.sin(h)
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return tuple(round(_gam(v) * 255) for v in (r, g, bl))


def parse(text):
    text = text.lower()
    if text == "white":
        return 255, 255, 255, 1.0
    if text == "black":
        return 0, 0, 0, 1.0
    if text.startswith("#"):
        h = text[1:]
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        alpha = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha
    parts = [p.strip() for p in re.split(r"[,\s/]+", text[text.index("(") + 1:-1]) if p.strip()]
    if len(parts) < 3 or any(p.startswith("var") for p in parts):
        return None
    try:
        r, g, b = (float(p.rstrip("%")) * (2.55 if p.endswith("%") else 1) for p in parts[:3])
        alpha = float(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1) if len(parts) > 3 else 1.0
    except ValueError:
        return None
    return r, g, b, alpha


def dark(text):
    """The dark-theme partner of one colour."""
    parsed = parse(text)
    if parsed is None:
        return text
    r, g, b, alpha = parsed
    L, C, h = to_oklch(r, g, b)
    if L > 0.8 and 0.015 <= C < 0.11:
        # Pale tints (notices, selections, warning borders) become a see-through
        # wash of their own hue, so they tint whatever surface sits below instead
        # of turning into an opaque olive or brown block.
        r2, g2, b2 = from_oklch(0.8, min(0.15, max(C * 2.5, 0.07)), h)
        # The palest (backgrounds) become a light wash; the deeper ones (borders) stay visible.
        return f"rgba({r2},{g2},{b2},{round(alpha * (0.2 if L > 0.9 else 0.5), 3)})"
    if C < 0.045 and L < 0.35 and 0.2 <= alpha < 0.999:
        # A heavy see-through dark is a scrim behind a drawer or dialog: it stays
        # dark (flipped, it would wash the page out). Faint ones are hover tints
        # and rules, and flip with the other greys below.
        return f"rgba(0,0,0,{round(min(0.8, alpha * 1.8), 3)})"
    if C < 0.045:
        # Greys flip onto a graphite ramp, not near-black. Pure white (cards,
        # fields) sits a step above the page so raised surfaces stay raised;
        # page greys and rules spread over the darks; ink and muted text land
        # on the light end with comfortable contrast.
        C2 = min(C, 0.01)
        if L >= 0.99:
            L2 = 0.305
        elif L > 0.9:
            L2 = 0.262 + max(0.0, 0.975 - L) * 1.2
        else:
            L2 = min(0.94, 0.375 + 0.565 * ((0.9 - L) / 0.7) ** 0.75)
    elif L > 0.72:
        L2, C2 = L, C  # bright colours (the lime accent) already read on dark
    else:
        # Dark brand, team and status colours are lifted so they read on
        # graphite, with a little chroma taken off so they do not glare.
        L2 = min(0.84, max(0.72, 1.08 - L * 0.55))
        C2 = C * 0.82
    r2, g2, b2 = from_oklch(L2, C2, h)
    if alpha >= 0.999:
        return f"#{r2:02x}{g2:02x}{b2:02x}"
    return f"rgba({r2},{g2},{b2},{round(alpha, 3)})"


ACCENT_INK = "#171817"


def is_accent(value):
    """A solid lime fill: text on it stays dark in both themes."""
    if "var(--cm-accent)" in value:
        return True
    for match in COLOR.finditer(value):
        parsed = parse(match.group(0))
        if parsed and parsed[3] > 0.9:
            L, C, _ = to_oklch(*parsed[:3])
            if L > 0.8 and C > 0.15:
                return True
    return False


def convert(value):
    return COLOR.sub(lambda m: dark(m.group(0)), value)


def rules(nodes, out, wrap=None):
    for node in nodes:
        if node.type == "qualified-rule":
            selectors = tinycss2.serialize(node.prelude).strip()
            decls = []
            on_accent = False
            for item in tinycss2.parse_declaration_list(node.content, skip_comments=True, skip_whitespace=True):
                if item.type != "declaration":
                    continue
                name = item.lower_name
                value = tinycss2.serialize(item.value).strip()
                if name in SKIP_PROPS or not COLOR_PROPS.search(name) or "url(" in value:
                    continue
                # Every colour declaration gets a twin, converted or not. A twin
                # carries the extra :root[data-theme] specificity, so if only
                # rules with literal colours were twinned, a dark "button
                # { background: #fff }" would beat a more specific light
                # ".play-toggle { background: var(--cm-ink) }" (or "none") and
                # leave a dark icon on a dark button.
                if NOT_COLOR_PROPS.search(name) or (name.startswith("--") and not COLOR.search(value)):
                    continue
                if name == "color" and on_accent:
                    continue
                if name in ("background", "background-color") and is_accent(value):
                    on_accent = True
                    decls = [d for d in decls if not d.startswith("  color:")]
                    decls.append(f"  color: {ACCENT_INK};")
                decls.append(f"  {name}: {convert(value)}{' !important' if item.important else ''};")
            if not decls:
                continue
            scoped = []
            for sel in (s.strip() for s in selectors.split(",")):
                if sel in (":root", "html"):
                    scoped.append(SCOPE)
                elif sel.startswith("html"):
                    scoped.append(SCOPE + sel[4:])
                elif sel.startswith(":root"):
                    scoped.append(SCOPE + sel[5:])
                else:
                    scoped.append(f"{SCOPE} {sel}")
            block = ",\n".join(scoped) + " {\n" + "\n".join(decls) + "\n}"
            out.append(block if wrap is None else f"{wrap} {{\n{block}\n}}")
        elif node.type == "at-rule" and node.lower_at_keyword in {"media", "supports"} and node.content:
            prelude = f"@{node.lower_at_keyword}{tinycss2.serialize(node.prelude)}".strip()
            if "prefers-color-scheme" in prelude:
                continue
            rules(tinycss2.parse_rule_list(node.content, skip_comments=True, skip_whitespace=True), out, prelude)


def main():
    out = ["/* Generated by tools/make_dark_theme.py. Do not edit: tune ui/theme.css instead. */"]
    for name in SHEETS:
        sheet = ROOT / "ui" / name
        out.append(f"\n/* {name} */")
        rules(tinycss2.parse_stylesheet(sheet.read_text(encoding="utf-8"), skip_comments=True, skip_whitespace=True), out)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
