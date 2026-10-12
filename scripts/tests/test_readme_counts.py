"""test_readme_counts.py — the README's reported suite count is counted, not copied.

The claim was previously pinned as a literal `Ran 171 tests ... OK` in this file, which made
the guard compare the README with this file's own prose: a suite that changed size and a
README that did not could both stay green, and that is exactly what happened when tabs were
cut and tests went with them. So the total is now taken from the same discovery the documented
command runs, and both public lines must carry it.
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
        loader = unittest.TestLoader()
        suite = loader.discover(str(TESTS))
        self.assertEqual(loader.errors, [],
                         f"discovery could not import every test module: {loader.errors}")
        total = suite.countTestCases()
        self.assertGreater(total, 50,
                           f"discovery counted {total} — that is not the suite, so the "
                           "comparison below would be meaningless")
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        claims = re.findall(r"Ran ([\d,]+) tests \.\.\. OK", text)
        self.assertEqual(len(claims), 2,
                         "English and Chinese count lines must both be present")
        self.assertEqual({int(c.replace(",", "")) for c in claims}, {total},
                         f"README claims {claims} but `unittest discover` counts {total}")


if __name__ == "__main__":
    unittest.main()
