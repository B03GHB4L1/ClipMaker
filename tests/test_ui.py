"""Source-level guards for shared UI regressions, alongside browser checks."""
from pathlib import Path
import re
import unittest

UI = Path(__file__).resolve().parents[1] / "ui"


class SharedUiTests(unittest.TestCase):
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
            self.assertIn("Version 1.3.0", source)
            versions.append(re.findall(r'href="((?:styles|compact)\.css\?v=\d+)"', source))
        self.assertEqual(versions[0], versions[1])
        self.assertEqual(versions[0], versions[2])

    def test_intake_has_no_sample_kickoff_markers(self):
        source = (UI / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'data-marker="([^"]+)"', source), ["00:00:00"] * 5)
        self.assertRegex(source, r'aria-hidden="true"\s+inert')


if __name__ == "__main__":
    unittest.main()
