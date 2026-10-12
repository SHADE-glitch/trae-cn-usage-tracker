"""test_maintenance_docs.py — maintenance notes cannot drift from the implementation.

The format notes are the place to explain why this tracker is session-level and what each
source means. These guards keep the three linked documents present, bilingual enough for the
project convention, and anchored to the source names the parser actually handles.
"""

import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401

DOCS = ROOT / "docs" / "maintenance"


class MaintenanceDocsTest(unittest.TestCase):
    def test_exactly_the_three_public_maintenance_docs_exist(self):
        names = {p.name for p in DOCS.glob("*.md")}
        self.assertEqual(names, {"trae-cn-format.md", "compatibility.md", "measurements.md"})

    def test_format_doc_names_every_indexed_source_and_encrypted_boundary(self):
        text = (DOCS / "trae-cn-format.md").read_text(encoding="utf-8")
        for marker in ("session_memory_", "topics.md", "user_profile.md",
                       "project_memory.md", "snapshot", "state.vscdb", "skills",
                       "plugins", "mcps", "encrypted",
                       # the model axis, and the fields that must stay unread
                       "model_list_map", "session_selected_model",
                       "consumption_rate", "custom_config",
                       # the credit source and the honesty around its delta
                       "renderer.log", "credit_events", "lower bound",
                       "skipped", "credit_log:event_shape",
                       # the negative result, stated as a measurement
                       "not recoverable", "bits/byte"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_format_doc_names_the_credential_whitelist_rule(self):
        # A catalog entry sits next to `ak`/`sk`/`base_url`. If the doc stops saying
        # they are not read, the next reader of the whitelist has nothing to check.
        text = (DOCS / "trae-cn-format.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"Credential fields are never read", re.IGNORECASE)
        for needle in ("ak", "sk", "base_url"):
            with self.subTest(needle=needle):
                self.assertIn("`%s`" % needle, text)

    def test_format_doc_names_incremental_and_unparsed_semantics(self):
        text = (DOCS / "trae-cn-format.md").read_text(encoding="utf-8")
        for marker in ("byte cursor", "size, mtime", "fingerprint", "unparsed", "--full"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_compatibility_doc_has_python_trae_and_tui_contracts(self):
        text = (DOCS / "compatibility.md").read_text(encoding="utf-8")
        for marker in ("Python", "3.11", "Trae CN", "Textual 8.2", "store_content"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertGreaterEqual(len(re.findall(r"[\u4e00-\u9fff]", text)), 20)

    def test_measurement_doc_is_explicitly_safe_and_has_baseline(self):
        text = (DOCS / "measurements.md").read_text(encoding="utf-8")
        self.assertIn("TCUT_DB=/tmp/", text)
        self.assertIn("unparsed=0", text)
        self.assertRegex(text, r"sessions=49.*projects=2.*turns=89.*toolcalls=139", re.S)

    def test_measurement_doc_records_the_model_axis_and_its_negative(self):
        text = (DOCS / "measurements.md").read_text(encoding="utf-8")
        for marker in ("284 rows", "42 distinct names", "7 accounts",
                       "21 rows over 11 of the 49 sessions", "11,837"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        # The lost count is the reason the key changed. Without it the rebuild reads
        # as a cosmetic schema bump, and the next collapse would be invisible again.
        self.assertRegex(text, r"models` held \*\*42 rows\*\*")
        self.assertRegex(text, r"tokens\s+0\b", re.S)

    def test_measurement_doc_keeps_the_credit_caveat_with_the_numbers(self):
        text = (DOCS / "measurements.md").read_text(encoding="utf-8")
        for marker in ("10 balance samples + 2 declined fetches", "154.0244",
                       "at least 1700 credits", "the only fractional balance"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
