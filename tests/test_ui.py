"""Source-level guards for shared UI regressions, alongside browser checks."""
from pathlib import Path
import json
import re
import unittest

UI = Path(__file__).resolve().parents[1] / "ui"


class SharedUiTests(unittest.TestCase):
    def test_ball_respects_reduced_motion_and_limits_rendering_cost(self):
        source = (UI / "app.js").read_text(encoding="utf-8")
        self.assertIn('if (reducedMotion.matches) return;', source)
        self.assertNotIn('preserveDrawingBuffer: true', source)
        self.assertIn('time - lastFrame < 1000 / 30', source)
        self.assertIn('if (reducedMotion.matches && stillRendered) return;', source)

    def test_vizorplay_brand_and_footer_version(self):
        for name in ("index.html", "filters.html", "analysis.html"):
            source = (UI / name).read_text(encoding="utf-8")
            self.assertIn('<span class="cm-logo" aria-hidden="true">VizorPlay</span', source)
            self.assertIn('<span>VizorPlay</span><span>Version 1.0</span>', source)
            self.assertNotIn("ClipMaker", source)
            self.assertNotIn("<sup>", source)
            title = re.search(r"<title>(.*?)</title>", source).group(1)
            self.assertIn("VizorPlay", title)
            self.assertNotIn("1.0", title)
        config = json.loads((UI.parent / "src-tauri/tauri.conf.json").read_text())
        self.assertEqual(config["productName"], "VizorPlay")
        self.assertEqual(config["version"], "1.0.0")
        self.assertEqual(config["identifier"], "com.b4l1.clipmaker")
        for name in ("package.json", "package-lock.json"):
            package = json.loads((UI.parent / name).read_text())
            self.assertEqual(package["name"], "vizorplay-desktop")
            self.assertEqual(package["version"], "1.0.0")
        asset = (UI / "assets/vizorplay-football.glb").read_bytes()
        self.assertEqual(asset[:4], b"glTF")
        scene = json.loads(asset[20:20 + int.from_bytes(asset[12:16], "little")])
        nodes = [node.get("name", "") for node in scene["nodes"]]
        self.assertIn("Emerald chrome VizorPlay", nodes)
        self.assertNotIn("Emerald chrome 1.3", nodes)
        self.assertTrue((UI / "assets/vizorplay-football.png").is_file())

    def test_removed_progress_has_no_markup_or_handlers(self):
        for name in ("index.html", "app.js", "styles.css", "compact.css"):
            source = (UI / name).read_text(encoding="utf-8")
            for obsolete in ("step-track", "setWorkflowStep", "data-step-label", "data-workflow-progress"):
                self.assertNotIn(obsolete, source, name)

    def test_all_screens_use_same_shared_style_versions(self):
        versions = []
        for name in ("index.html", "filters.html", "analysis.html"):
            source = (UI / name).read_text(encoding="utf-8")
            self.assertIn('class="app-footer"', source)
            self.assertIn("Version 1.0", source)
            versions.append(re.findall(r'href="((?:styles|compact|design)\.css\?v=\d+)"', source))
        self.assertEqual(versions[0], versions[1])
        self.assertEqual(versions[0], versions[2])

    def test_intake_has_no_sample_kickoff_markers(self):
        source = (UI / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'data-marker="([^"]+)"', source), ["00:00:00"] * 5)
        self.assertRegex(source, r'aria-hidden="true"\s+inert')

    def test_geist_is_bundled_and_identical_in_chart_component(self):
        font = (UI / "assets/fonts/GeistMono-Variable.ttf").read_bytes()
        self.assertEqual(font[:4], b"\x00\x01\x00\x00")
        chart = UI.parent / "app/smp_component/frontend"
        self.assertEqual(font, (chart / "fonts/GeistMono-Variable.ttf").read_bytes())
        self.assertIn("SIL OPEN FONT LICENSE", (UI / "assets/fonts/OFL-GeistMono.txt").read_text(encoding="utf-8"))
        for name in ("index.html", "filters.html", "analysis.html"):
            self.assertIn('href="design.css?', (UI / name).read_text(encoding="utf-8"))
        self.assertNotIn("fonts.googleapis.com", (chart / "index.html").read_text(encoding="utf-8"))

    def test_analytical_chart_fonts_and_selected_tab_contrast(self):
        for name in ("comparison_helpers.py", "tactical_page.py"):
            source = (UI.parent / "app/analysis_core" / name).read_text(encoding="utf-8")
            self.assertNotIn('family="Inter, sans-serif"', source)
            self.assertNotIn('family="Space Grotesk, Inter, sans-serif"', source)
            self.assertIn('family="Geist Mono, monospace"', source)
        css = (UI / "analysis/native.css").read_text(encoding="utf-8")
        self.assertIn(".native-tabs [role=tab][aria-selected=true] { color: var(--cm-ink);", css)

    def test_analysis_page_has_no_classic_workspace(self):
        # Phase 5 retired the Streamlit workspace: no iframe, no classic switch.
        page = (UI / "analysis.html").read_text(encoding="utf-8")
        scripts = "".join((UI / name).read_text(encoding="utf-8") for name in ("analysis.js", "analysis/native.js"))
        self.assertNotIn("<iframe", page)
        for token in ("ui=classic", "/api/analysis\"", "classicUrl", "data-analysis-frame"):
            self.assertNotIn(token, scripts)

if __name__ == "__main__":
    unittest.main()
