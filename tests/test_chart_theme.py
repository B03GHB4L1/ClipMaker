"""Dark theme, the VizorPlay credit on chart pictures, and the chart changes that came with them."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
COMPONENT = ROOT / "app" / "smp_component" / "frontend" / "index.html"


class ThemeTests(unittest.TestCase):
    def test_every_screen_loads_the_theme_first_and_its_sheets_last(self):
        for name in ("index.html", "filters.html", "analysis.html", "annotate.html", "code.html"):
            page = (UI / name).read_text(encoding="utf-8")
            head = page.split("</head>")[0]
            self.assertLess(head.index("theme.js"), head.index('rel="stylesheet"'), name)
            sheets = re.findall(r'href="([^"]+\.css)[^"]*"', head)
            self.assertEqual([Path(s.split("?")[0]).name for s in sheets[-2:]], ["theme-dark.css", "theme.css"], name)
            self.assertIn('class="app-footer"', page, name)  # where the theme switch goes

    def test_generated_dark_sheet_is_current(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_dark_theme", ROOT / "tools" / "make_dark_theme.py")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError:
            self.skipTest("tinycss2 is not installed")
        before = (UI / "theme-dark.css").read_text(encoding="utf-8")
        module.main()
        self.assertEqual((UI / "theme-dark.css").read_text(encoding="utf-8"), before,
                         "run python tools/make_dark_theme.py after changing a stylesheet colour")

    def test_dark_partner_colours(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_dark_theme", ROOT / "tools" / "make_dark_theme.py")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ModuleNotFoundError:
            self.skipTest("tinycss2 is not installed")
        lum = lambda hex_: module.to_oklch(*(int(hex_[i:i + 2], 16) for i in (1, 3, 5)))[0]
        self.assertLess(lum(module.dark("#ffffff")), 0.33)      # paper goes dark
        self.assertGreater(lum(module.dark("#171817")), 0.8)    # ink goes light
        self.assertEqual(module.dark("#c8f135"), "#c8f135")      # the lime accent already reads on dark
        self.assertTrue(module.dark("rgba(0,0,0,0.2)").startswith("rgba("))
        # Graphite, not near-black: the page and cards sit mid-dark, cards above the page.
        self.assertGreater(lum(module.dark("#f7f7f7")), 0.25)
        self.assertGreater(lum(module.dark("#ffffff")), lum(module.dark("#f7f7f7")))
        # Pale tints become a see-through wash of their hue, not an opaque olive block.
        self.assertTrue(module.dark("#e6f2c5").startswith("rgba("))

    def test_dark_selectors_keep_lists_inside_brackets_whole(self):
        # The generator once split ":is(button, select)" at its comma, so the browser dropped
        # 14 dark rules (focus rings, Annotate and Code buttons, the pitch lines).
        sheet = (UI / "theme-dark.css").read_text(encoding="utf-8")
        for selectors in re.findall(r"^([^{}@/][^{}]*)\{", sheet, re.M):
            for selector in selectors.split(",\n"):  # the generator puts one selector per line
                for bracket, closing in (("(", ")"), ("[", "]")):
                    self.assertEqual(selector.count(bracket), selector.count(closing), selector.strip()[:120])
        self.assertIn('.code-main :is(button, select, input, a, summary):focus-visible {', sheet)
        self.assertIn('.code-pitch-lines :is(rect, path, circle) {', sheet)

    def test_dark_twins_keep_the_light_cascade(self):
        # A twin of a plain rule must not out-rank a more specific light rule that uses a
        # variable: the play button once lost its dark fill and its icon disappeared.
        sheet = (UI / "theme-dark.css").read_text(encoding="utf-8")
        self.assertRegex(sheet, r'\.transport \.play-toggle \{[^}]*background: var\(--cm-ink\)')
        # Text on a solid lime fill stays dark.
        self.assertRegex(sheet, r'\.export-bar \.export-button \{[^}]*color: #171817')

    def test_dark_charts_use_the_graphite_palette(self):
        sources = [COMPONENT, ROOT / "app/analysis_core/comparison_helpers.py", ROOT / "app/analysis_core/tactical_page.py"]
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for old in ("#071008", "#0b0e14", "rgba(11,14,20,", "142,255,113"):
                self.assertNotIn(old, text, f"{path.name}: {old}")

    def test_analysis_requests_carry_the_theme_and_redraw_on_change(self):
        projects = (UI / "projects.js").read_text(encoding="utf-8")
        self.assertIn('path.startsWith("/api/analysis/")', projects)
        self.assertIn("theme: window.vizorTheme", projects)
        self.assertIn('"vizorplay-theme"', (UI / "analysis" / "native.js").read_text(encoding="utf-8"))
        server = (ROOT / "packaging" / "clipmaker_api_server.py").read_text(encoding="utf-8")
        self.assertIn('light_mode=body.get("theme") != "dark"', server)
        self.assertIn('light=body.get("theme") != "dark"', server)

    def test_tactical_render_follows_the_theme(self):
        import inspect
        import sys
        sys.path.insert(0, str(ROOT / "app"))
        from analysis_core import tactical
        self.assertIn("light", inspect.signature(tactical.render).parameters)


class CreditTests(unittest.TestCase):
    def test_no_handle_text_credit_left_in_charts(self):
        for path in [COMPONENT, *(ROOT / "app" / "analysis_core").glob("*.py")]:
            self.assertNotIn("@B03GHB4L1", path.read_text(encoding="utf-8"), path.name)

    def test_every_export_path_adds_the_logo_strip(self):
        self.assertIn("brandPicture", (UI / "save-clip.js").read_text(encoding="utf-8"))
        component = COMPONENT.read_text(encoding="utf-8")
        self.assertIn('import("/analysis/brand-export.js")', component)
        self.assertIn("module.brandCanvas(canvas, brand)", component)  # GIF frames
        brand = (UI / "analysis" / "brand-export.js").read_text(encoding="utf-8")
        for asset in ("vizorplay-mark.svg", "vizorplay-wordmark.svg", "vizorplay-mark-on-dark.svg", "vizorplay-wordmark-on-dark.svg"):
            self.assertIn(asset, brand)
            self.assertTrue((UI / "assets" / "brand" / asset).is_file(), asset)


class ChartTests(unittest.TestCase):
    def test_event_trace_is_not_offered_as_a_picture(self):
        source = (ROOT / "app" / "analysis_core" / "tactical_page.py").read_text(encoding="utf-8")
        call = source[source.index("_sequence_trace(window, selected"):][:400]
        self.assertIn('"displayModeBar": False', call)

    def test_shot_markers_scale_by_area_with_a_floor_and_a_key(self):
        component = COMPONENT.read_text(encoding="utf-8")
        self.assertIn("SHOT_SIZE_MIN + SHOT_SIZE_SPAN * Math.sqrt(", component)
        self.assertIn("shotSizeKey(", component)

    def test_build_up_pictures_name_players(self):
        component = COMPONENT.read_text(encoding="utf-8")
        body = component[component.index("function renderBuildUpMap"):component.index("function renderPenaltyShootout")]
        self.assertIn("_cmExportLabels = labels.length", body)
        self.assertIn("placeExportLabels(chart, plan)", component)


if __name__ == "__main__":
    unittest.main()
