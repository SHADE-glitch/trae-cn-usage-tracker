"""test_readme_counts.py — the counts and the settings table in the READMEs are the real ones.

The suite total was once pinned as a literal in this file, which made the guard compare the
README with this file's own prose: a suite that changed size and a README that did not could
both stay green. The total is now taken from the same discovery the documented command runs,
and both public pages must carry it.

The second half is not about a count: both pages document the whole settings surface (every
key with its shipped default, every variable that overrides it), and that list is hand-copied
— the loader is the only complete copy, so the page is checked against it.

Standard library only. Nothing is executed — the modules are imported and counted.
"""

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401 -- tripwire: the suite must never open the real database

sys.path.insert(0, str(SCRIPTS))
import tcut_db as db  # noqa: E402


class ReadmeCountsTest(unittest.TestCase):
    def test_both_readmes_pin_the_current_unittest_total(self):
        loader = unittest.TestLoader()
        suite = loader.discover(str(TESTS))
        self.assertEqual(loader.errors, [],
                         f"discovery could not import every test module: {loader.errors}")
        total = suite.countTestCases()
        self.assertGreater(total, 50,
                           f"discovery counted {total} — that is not the suite, so the "
                           "comparison below would be meaningless")
        for name in ("README.md", "README.zh-CN.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            claims = [c for c in __import__("re").findall(r"Ran ([\d,]+) tests \.\.\. OK", text)]
            self.assertTrue(claims, f"{name} prints no 'Ran N tests ... OK' line")
            for claimed in claims:
                self.assertEqual(int(claimed.replace(",", "")), total,
                                 f"{name} claims {claimed} but `unittest discover` "
                                 f"counts {total}")

    def test_both_readmes_document_every_setting(self):
        """A setting nobody can find is a setting nobody uses. Every key shown with the
        default it ships with, and every variable that can override it named."""
        for name in ("README.md", "README.zh-CN.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            missing_keys = [k for k in sorted(db.DEFAULTS) if f"`{k}`" not in text]
            self.assertFalse(missing_keys,
                             f"{name} never names these settings: {missing_keys}")
            missing_defaults = [f"`{k}` = `{str(v).lower()}`"
                                for k, v in sorted(db.DEFAULTS.items())
                                if f"`{str(v).lower()}`" not in text]
            self.assertFalse(missing_defaults,
                             f"{name} does not show these settings with their shipped "
                             f"default: {missing_defaults}")
            missing_env = sorted(v for v in db.ENV_NAMES.values() if v not in text)
            self.assertFalse(missing_env,
                             f"{name} never names the variable that overrides these: "
                             f"{missing_env}")


if __name__ == "__main__":
    unittest.main()
