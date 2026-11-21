import unittest

from tests.macos_min_os import format_version, parse_minimums, version_tuple

THIN = """/x/libfoo.dylib:
Load command 9
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform MACOS
    minos 11.0
      sdk 15.0
   ntools 1
"""

OLD_STYLE = """/x/old.so:
Load command 7
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.9
      sdk 10.9
"""

FAT = """/x/fat.dylib (architecture x86_64):
Load command 9
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform MACOS
    minos 10.13
      sdk 14.0
/x/fat.dylib (architecture arm64):
Load command 9
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform MACOS
    minos 13.3
      sdk 14.0
"""

OTHER_PLATFORM = """/x/lib:
Load command 9
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform IOS
    minos 17.0
      sdk 17.0
"""


class MinimumMacosTests(unittest.TestCase):
    def test_reads_the_build_version_of_a_single_chip_file(self):
        self.assertEqual(parse_minimums(THIN), [(None, (11, 0))])

    def test_reads_the_older_version_command(self):
        self.assertEqual(parse_minimums(OLD_STYLE), [(None, (10, 9))])

    def test_keeps_each_chip_of_a_universal_file_apart(self):
        self.assertEqual(parse_minimums(FAT), [("x86_64", (10, 13)), ("arm64", (13, 3))])

    def test_ignores_other_platforms(self):
        self.assertEqual(parse_minimums(OTHER_PLATFORM), [])

    def test_versions_compare_numerically(self):
        self.assertGreater(version_tuple("10.15.4"), version_tuple("10.9"))
        self.assertGreater(version_tuple("13.3"), (11, 0))
        self.assertEqual(format_version((11, 0)), "11.0")


if __name__ == "__main__":
    unittest.main()
