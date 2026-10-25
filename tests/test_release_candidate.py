"""Release promotion must retain the tested bytes and reject mismatched evidence."""
import json
from pathlib import Path
import tempfile
import unittest

from packaging.release_candidate import assemble, digest, record_receipt, verify_receipts


class ReleaseCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.receipts = self.root / "tested"
        self.commit = "a" * 40

    def fixture(self, platform):
        names = {"Windows": "VizorPlay_1.0.0_x64-setup.exe", "Linux": "VizorPlay_1.0.0_amd64.deb",
                 "macOS": "vizorplay-1.0.0-source.tar.gz"}
        payload = self.root / names[platform]
        payload.write_bytes((platform + " tested payload").encode())
        result = {"status": "passed", "installed_versions": ["0.9.0", "1.0.0"] if platform == "macOS"
                  else ["0.9.0", "1.0.0", "1.0.0"], "shutdown_verified": True, "reinstall_and_uninstall": True}
        evidence = self.root / f"{platform}.json"
        evidence.write_text(json.dumps(result))
        return payload, evidence

    def record_all(self):
        for platform in ("Windows", "Linux", "macOS"):
            payload, evidence = self.fixture(platform)
            record_receipt(platform, payload, [evidence], self.receipts, self.commit)

    def test_assembles_exact_tested_bytes_and_consistent_install_manifests(self):
        self.record_all()
        target = self.root / "candidate"
        manifest = assemble(self.receipts, target, self.commit, "B03GHB4L1/ClipMaker")
        self.assertFalse(manifest["published"])
        for receipt in manifest["artifacts"]:
            self.assertEqual(digest(target / receipt["payload"]), receipt["sha256"])
        source = next(item for item in manifest["artifacts"] if item["platform"] == "macOS")
        formula = (target / "clipmaker.rb").read_text()
        self.assertIn(source["sha256"], formula)
        self.assertIn("releases/download/v1.0.0/vizorplay-1.0.0-source.tar.gz", formula)
        windows = next(item for item in manifest["artifacts"] if item["platform"] == "Windows")
        installer = (target / "B4L1.ClipMaker.installer.yaml").read_text()
        self.assertIn(windows["sha256"].upper(), installer)
        for line in (target / "SHA256SUMS").read_text().splitlines():
            checksum, filename = line.split("  ", 1)
            self.assertEqual(Path(filename).name, filename, "Release assets are published with flat filenames")
            self.assertEqual(checksum, digest(target / filename))
        with self.assertRaises(ValueError):
            assemble(self.receipts, target, self.commit, "B03GHB4L1/ClipMaker")

    def test_rejects_modified_payload_wrong_commit_and_path_escape(self):
        self.record_all()
        receipt_path = self.receipts / "receipt-Windows.json"
        receipt = json.loads(receipt_path.read_text())
        payload = self.receipts / receipt["payload"]
        original = payload.read_bytes()
        payload.write_bytes(b"replaced after testing")
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_receipts(self.receipts, self.commit)
        payload.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "Wrong commit"):
            verify_receipts(self.receipts, "b" * 40)
        receipt["payload"] = "../outside.exe"
        receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "flat filename"):
            verify_receipts(self.receipts, self.commit)

    def test_rejects_failed_or_missing_upgrade_evidence(self):
        payload, evidence = self.fixture("Windows")
        for result in ({"status": "failed"}, {"status": "passed"},
                       {"status": "passed", "installed_versions": ["1.0.0", "1.0.0"]}):
            evidence.write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                record_receipt("Windows", payload, [evidence], self.receipts, self.commit)
        with self.assertRaises(ValueError):
            record_receipt("Windows", payload, [], self.receipts, self.commit)


if __name__ == "__main__":
    unittest.main()
