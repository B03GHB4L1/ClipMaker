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
        self.assertIn("vizorplayapp@gmail.com", text)
        self.assertNotIn("Permission is hereby granted", text)  # the MIT grant lives in its own file

    def test_licence_summary_speaks_to_the_public(self):
        # Readers of the installed app or the repo front page know releases, not commits or source paths.
        summary = (ROOT / "LICENSE").read_text(encoding="utf-8").split("# PolyForm Strict License")[0]
        self.assertNotIn("552e33f", summary)
        for path in ("ui/", "app/", ".txt"):
            self.assertNotIn(path, summary)
        for part in ("three.js", "Geist Mono", "ViT"):
            self.assertIn(part, summary)

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

    def test_every_installer_ships_the_licence_files(self):
        # Tauri copies these resources next to the installed program, where people can open them.
        import ast, json
        resources = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["bundle"]["resources"]
        bundled = {target: source for source, target in resources.items()}
        self.assertEqual(bundled["LICENSE.txt"], "../LICENSE")
        self.assertEqual(bundled["LICENSE-MIT-EARLIER.txt"], "../LICENSE-MIT-EARLIER.md")
        for source in resources:
            self.assertTrue((ROOT / "src-tauri" / source).exists(), source)
        for smoke in ("tests/native_smoke.py", "tests/macos_dmg_smoke.py"):
            tree = ast.parse((ROOT / smoke).read_text(encoding="utf-8"))
            checked = next(ast.literal_eval(node.value) for node in tree.body
                           if isinstance(node, ast.Assign) and node.targets[0].id == "INSTALLED_LICENCES")
            self.assertEqual(set(checked), set(bundled) - {"backend/"}, smoke)


if __name__ == "__main__":
    unittest.main()
