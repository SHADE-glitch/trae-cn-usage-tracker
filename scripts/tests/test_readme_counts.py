"""test_readme_counts.py — the README's reported suite count is checked in.

The count is intentionally explicit: changing the suite without updating the public claim is
drift. This guard is one test, so the current total is 171 after the documentation guards are added.
"""

import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401


class ReadmeCountsTest(unittest.TestCase):
    def test_readme_pins_the_current_unittest_total(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"Ran 171 tests \.\.\. OK")
        self.assertEqual(len(re.findall(r"Ran 171 tests \.\.\. OK", text)), 2,
                         "English and Chinese count lines must stay in sync")


if __name__ == "__main__":
    unittest.main()
