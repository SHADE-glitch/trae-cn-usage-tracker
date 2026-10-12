"""test_record_coverage.py — the changelog records the complete initial delivery.

This standalone workspace has no git history yet, so commit-to-record coverage is not
applicable. The useful invariant here is that the shipped release entry names every delivery
surface instead of pretending the changelog is complete while omitting tests or docs.
"""

import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401


class RecordCoverageTest(unittest.TestCase):
    def test_initial_release_record_covers_code_tests_docs_and_privacy(self):
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 0.1.0 — 2026-10-12", text)
        for marker in ("standalone", "incremental indexing", "nine-tab", "SQLite",
                       "configuration", "privacy", "regression coverage"):
            with self.subTest(marker=marker):
                self.assertRegex(text, re.escape(marker), re.IGNORECASE)


if __name__ == "__main__":
    unittest.main()
