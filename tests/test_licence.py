"""Licence (2026-11-22): VizorPlay moved from MIT to the PolyForm Strict License 1.0.0,
noncommercial and source-available, with commercial licences sold separately. Earlier
versions stay MIT, so that notice is kept. The packaging templates must say the same."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LicenceTests(unittest.TestCase):
    def test_licence_is_polyform_strict_with_a_commercial_contact(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("# PolyForm Strict License 1.0.0", text)
        self.assertIn("other than distributing the software or making changes", text)
        self.assertIn("Commercial licences", text)
        self.assertIn("granvskaia@gmail.com", text)
        self.assertNotIn("Permission is hereby granted", text)  # the MIT grant lives in its own file

    def test_the_earlier_mit_notice_is_kept(self):
        text = (ROOT / "LICENSE-MIT-EARLIER.md").read_text(encoding="utf-8")
        self.assertIn("Permission is hereby granted, free of charge", text)
        self.assertIn("552e33f", text)

    def test_packaging_templates_do_not_claim_mit(self):
        formula = (ROOT / "packaging/homebrew/vizorplay.rb.in").read_text(encoding="utf-8")
        winget = (ROOT / "packaging/winget/B4L1.VizorPlay.locale.en-US.yaml.in").read_text(encoding="utf-8")
        self.assertIn("license :cannot_represent", formula)
        self.assertIn("License: PolyForm Strict 1.0.0", winget)
        self.assertNotIn("MIT", formula + winget)


if __name__ == "__main__":
    unittest.main()
