"""test_readme_bilingual.py — README claims stay bilingual and actionable.

README is a user-facing contract, not a scrapbook. Every major section has an English and a
Chinese paragraph, and the pages named as maintenance links exist. These checks deliberately
pin concepts rather than every sentence, so wording can improve without making the guard noisy.
"""

import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401 -- tripwire is required by every test module


class ReadmeBilingualTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_readme_exists_and_has_english_first_title(self):
        self.assertTrue(self.readme.startswith("# Trae CN Usage Tracker"))

    def test_major_sections_have_english_and_chinese_markers(self):
        for marker in ("What is recorded", "Install", "Commands", "TUI tabs",
                       "Storage and privacy", "Settings", "Tests", "Maintenance notes"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.readme)
        # A broad sanity check: the Chinese companion is not just one footer sentence.
        chinese = re.findall(r"[\u4e00-\u9fff]", self.readme)
        self.assertGreaterEqual(len(chinese), 300)

    def test_readme_states_the_token_absence_and_the_model_axis(self):
        # The two claims most likely to be softened by a future edit: that tokens are
        # absent as a measurement, and that credential fields are outside the whitelist.
        for marker in ("Token counts are **not** on this machine",
                       "11,837", "8.000 bits/byte",
                       "the model each session was set to",
                       "`ak`, `sk`, `base_url` and `custom_config`"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.readme)

    def test_readme_mentions_the_deliberate_content_storage_deviation(self):
        self.assertIn("store_content = true", self.readme)
        self.assertIn("store_content = false", self.readme)
        self.assertIn("local SQLite only", self.readme)

    def test_all_maintenance_links_resolve(self):
        for name in ("trae-cn-format.md", "compatibility.md", "measurements.md"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "docs" / "maintenance" / name).is_file())


if __name__ == "__main__":
    unittest.main()
