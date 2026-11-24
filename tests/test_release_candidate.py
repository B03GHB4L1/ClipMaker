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
                 "macOS": "vizorplay-1.0.0-source.tar.gz", "macOS-AppleSilicon": "VizorPlay_1.0.0_aarch64.dmg",
                 "macOS-Intel": "VizorPlay_1.0.0_x64.dmg"}
        payload = self.root / names[platform]
        payload.write_bytes((platform + " tested payload").encode())
        result = {"status": "passed", "installed_versions": ["0.9.0", "1.0.0"] if platform == "macOS"
                  else ["0.9.0", "1.0.0", "1.0.0"], "shutdown_verified": True, "reinstall_and_uninstall": True}
        if platform == "macOS":  # tests/macos_app_smoke.py: the Homebrew-built app ran its engine
            result["engine_stopped"] = {"pid": True, "parent_pid": True}
        if platform.startswith("macOS-"):  # tests/macos_dmg_smoke.py result.json
            arch = "arm64" if platform == "macOS-AppleSilicon" else "x86_64"
            result = {"status": "passed", "dmg": payload.name, "expected_arch": arch, "architectures": arch,
                      "needs_newer_than_promised": {}}
        evidence = self.root / f"{platform}.json"
        evidence.write_text(json.dumps(result))
        return payload, evidence

    def test_disk_images_need_matching_name_chip_and_passed_launch_evidence(self):
        payload, evidence = self.fixture("macOS-AppleSilicon")
        good = json.loads(evidence.read_text())
        for change in ({"architectures": "x86_64"}, {"expected_arch": "x86_64"}, {"dmg": "other.dmg"},
                       {"needs_newer_than_promised": {"libfoo.dylib": "15.0"}}, {"status": "failed"}):
            evidence.write_text(json.dumps({**good, **change}))
            with self.assertRaises(ValueError):
                record_receipt("macOS-AppleSilicon", payload, [evidence], self.receipts, self.commit)
        evidence.write_text(json.dumps(good))
        record_receipt("macOS-AppleSilicon", payload, [evidence], self.receipts, self.commit)
        intel, intel_evidence = self.fixture("macOS-Intel")
        with self.assertRaisesRegex(ValueError, "right chip"):
            record_receipt("macOS-Intel", intel, [evidence], self.receipts, self.commit)
        record_receipt("macOS-Intel", intel, [intel_evidence], self.receipts, self.commit)

    def test_release_includes_the_apple_silicon_image_and_intel_only_when_it_passed(self):
        self.record_all(intel=False)
        target = self.root / "without-intel"
        manifest = assemble(self.receipts, target, self.commit, "B03GHB4L1/ClipMaker")
        names = {item["payload"] for item in manifest["artifacts"]}
        self.assertIn("VizorPlay_1.0.0_aarch64.dmg", names)
        self.assertNotIn("VizorPlay_1.0.0_x64.dmg", names)
        self.assertIn("VizorPlay_1.0.0_aarch64.dmg", (target / "SHA256SUMS").read_text())
        (self.receipts / "receipt-macOS-AppleSilicon.json").unlink()
        with self.assertRaises(FileNotFoundError):  # the Apple Silicon image is required
            verify_receipts(self.receipts, self.commit)
        self.record_all(intel=True)
        with_intel = assemble(self.receipts, self.root / "with-intel", self.commit, "B03GHB4L1/ClipMaker")
        self.assertIn("VizorPlay_1.0.0_x64.dmg", {item["payload"] for item in with_intel["artifacts"]})

    def test_macos_needs_the_homebrew_app_launch_evidence(self):
        payload, evidence = self.fixture("macOS")
        result = json.loads(evidence.read_text())
        for stopped in (None, {"pid": True, "parent_pid": False}):
            result["engine_stopped"] = stopped
            evidence.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "VizorPlay.app"):
                record_receipt("macOS", payload, [evidence], self.receipts, self.commit)

    def updater(self, passed=True):
        signature = self.root / "VizorPlay_1.0.0_x64-setup.exe.sig"
        signature.write_text("dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkK\n")
        evidence = self.root / "update.json"
        evidence.write_text(json.dumps({"status": "passed", "update_installed": passed, "bad_signature_rejected": True}))
        return signature, evidence

    def record_all(self, signed=True, intel=False):
        for platform in ("Windows", "Linux", "macOS", "macOS-AppleSilicon") + (("macOS-Intel",) if intel else ()):
            payload, evidence = self.fixture(platform)
            if platform == "Windows" and signed:
                signature, update = self.updater()
                record_receipt(platform, payload, [evidence, update], self.receipts, self.commit, signature)
            else:
                record_receipt(platform, payload, [evidence], self.receipts, self.commit)

    def test_assembles_exact_tested_bytes_and_consistent_install_manifests(self):
        self.record_all()
        target = self.root / "candidate"
        manifest = assemble(self.receipts, target, self.commit, "B03GHB4L1/ClipMaker")
        self.assertFalse(manifest["published"])
        for receipt in manifest["artifacts"]:
            self.assertEqual(digest(target / receipt["payload"]), receipt["sha256"])
        source = next(item for item in manifest["artifacts"] if item["platform"] == "macOS")
        formula = (target / "vizorplay.rb").read_text()
        self.assertIn(source["sha256"], formula)
        self.assertIn("releases/download/v1.0.0/vizorplay-1.0.0-source.tar.gz", formula)
        windows = next(item for item in manifest["artifacts"] if item["platform"] == "Windows")
        installer = (target / "B4L1.VizorPlay.installer.yaml").read_text()
        self.assertIn(windows["sha256"].upper(), installer)
        for line in (target / "SHA256SUMS").read_text().splitlines():
            checksum, filename = line.split("  ", 1)
            self.assertEqual(Path(filename).name, filename, "Release assets are published with flat filenames")
            self.assertEqual(checksum, digest(target / filename))
        feed = json.loads((target / "latest.json").read_text())
        self.assertEqual(feed["version"], "1.0.0")
        self.assertEqual(feed["platforms"]["windows-x86_64"], {
            "signature": windows["updater_signature"],
            "url": "https://github.com/B03GHB4L1/ClipMaker/releases/download/v1.0.0/VizorPlay_1.0.0_x64-setup.exe"})
        self.assertEqual(set(feed["platforms"]), {"windows-x86_64"}, "Only Windows installs in the app")
        with self.assertRaises(ValueError):
            assemble(self.receipts, target, self.commit, "B03GHB4L1/ClipMaker")

    def test_release_needs_a_signed_windows_updater_package_and_update_evidence(self):
        self.record_all(signed=False)
        with self.assertRaisesRegex(ValueError, "signed updater"):
            assemble(self.receipts, self.root / "unsigned", self.commit, "B03GHB4L1/ClipMaker")
        payload, evidence = self.fixture("Windows")
        signature, update = self.updater(passed=False)
        record_receipt("Windows", payload, [evidence, update], self.receipts, self.commit, signature)
        with self.assertRaisesRegex(ValueError, "update evidence"):
            assemble(self.receipts, self.root / "unverified", self.commit, "B03GHB4L1/ClipMaker")
        signature.write_text("not a signature")
        with self.assertRaisesRegex(ValueError, "signature"):
            record_receipt("Windows", payload, [evidence], self.receipts, self.commit, signature)
        linux, linux_evidence = self.fixture("Linux")
        with self.assertRaisesRegex(ValueError, "Only the Windows"):
            record_receipt("Linux", linux, [linux_evidence], self.receipts, self.commit, signature)

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
