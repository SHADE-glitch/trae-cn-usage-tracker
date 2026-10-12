"""test_maintenance_docs.py — the maintenance documents cannot drift from the code.

`docs/maintenance/trae-cn-format.md` carries a block **generated** from the format
registry in `tcut-sync.py`. A hand-copied list is how `schema_version` once became a
value nothing read: written, plausible, and disconnected from the code. These checks
are the difference between a document and a claim.

Three further rules are held here: every file under `docs/maintenance/` is reachable
from its index, the writer refuses to rewrite a document whose markers are gone, and
the CI matrix a document states is the one the workflow runs.

Standard library only. Nothing in the repository is written by these tests.
"""

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401 -- tripwire: the suite must never open the real database

sys.path.insert(0, str(SCRIPTS))
import tcut_db as db  # noqa: E402

_spec = importlib.util.spec_from_file_location("tcut_stats", SCRIPTS / "tcut-stats.py")
stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats)

DOC = REPO / "docs" / "maintenance" / "trae-cn-format.md"
DOCDIR = REPO / "docs" / "maintenance"


def block_of(text: str) -> str:
    head, _, rest = text.partition(stats.FORMAT_BEGIN + "\n")
    if head == text:
        raise AssertionError("the document has no generated block marker")
    body, _, _tail = rest.partition(stats.FORMAT_END)
    return body


class GeneratedFormatBlockTest(unittest.TestCase):
    def test_the_block_matches_the_registry(self):
        """The point of the file: what it states is decided by the parser."""
        self.assertEqual(
            block_of(DOC.read_text(encoding="utf-8")),
            db.load_sync().format_doc(),
            "docs/maintenance/trae-cn-format.md is stale — run "
            "`tcut format --write` in the same change as the registry")

    def test_every_read_field_appears_in_the_document(self):
        """Positive control. The comparison above would also pass on a renderer that
        returned an empty string, which would leave a tidy document saying nothing
        about the fields the parser actually reads."""
        text = DOC.read_text(encoding="utf-8")
        fields = db.load_sync().VSCDB_FIELDS
        self.assertGreater(len(fields), 15)
        missing = [f for f in fields if f"`{f}`" not in text]
        self.assertEqual(missing, [], f"read by the parser, undocumented: {missing}")

    def test_a_registry_change_does_leave_the_document_stale(self):
        """The guard must be capable of failing: add a field to the registry and the
        checked-in block no longer matches what the code reads."""
        sync = db.load_sync()
        original = sync.VSCDB_FIELDS
        try:
            sync.VSCDB_FIELDS = original | {"aNewUpstreamField"}
            drifted = sync.format_doc()
        finally:
            sync.VSCDB_FIELDS = original
        self.assertNotEqual(block_of(DOC.read_text(encoding="utf-8")), drifted)
        self.assertIn("`aNewUpstreamField`", drifted)

    def test_the_writer_refuses_a_document_without_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "prose.md"
            doc.write_text("# hand-written notes\n", encoding="utf-8")
            before = doc.read_text(encoding="utf-8")
            self.assertFalse(stats._replace_generated_block(doc, "- generated\n"))
            self.assertEqual(doc.read_text(encoding="utf-8"), before,
                             "a file it refused was modified anyway")

    def test_the_writer_replaces_only_the_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text(
                f"intro\n{stats.FORMAT_BEGIN}\nold\n{stats.FORMAT_END}\ntrailer\n",
                encoding="utf-8")
            self.assertTrue(
                stats._replace_generated_block(doc, "fresh\n"),
                "a correctly marked document was refused")
            self.assertEqual(
                doc.read_text(encoding="utf-8"),
                f"intro\n{stats.FORMAT_BEGIN}\nfresh\n{stats.FORMAT_END}\ntrailer\n")

    def test_the_writer_is_idempotent(self):
        body = db.load_sync().format_doc()
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text(f"{stats.FORMAT_BEGIN}\n{stats.FORMAT_END}\n",
                           encoding="utf-8")
            stats._replace_generated_block(doc, body)
            once = doc.read_text(encoding="utf-8")
            stats._replace_generated_block(doc, body)
            self.assertEqual(doc.read_text(encoding="utf-8"), once)


class DocTreeTest(unittest.TestCase):
    def test_the_maintenance_docs_exist(self):
        for name in ("README.md", "trae-cn-format.md", "compatibility.md",
                     "measurements.md"):
            path = DOCDIR / name
            self.assertTrue(path.is_file(), f"missing {path}")
            self.assertGreater(len(path.read_text(encoding="utf-8")), 200,
                               f"{name} is a stub")

    def test_every_document_is_reachable_from_the_index(self):
        index = (DOCDIR / "README.md").read_text(encoding="utf-8")
        for path in sorted(DOCDIR.glob("*.md")):
            if path.name == "README.md":
                continue
            self.assertIn(f"({path.name})", index,
                          f"{path.name} is not linked from the index")

    def test_both_readmes_point_into_docs(self):
        """The landing pages carry the repository layout; a directory nobody can walk
        to from them is a directory that does not get read."""
        for name in ("README.md", "README.zh-CN.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            self.assertIn("docs/", text, f"{name} never mentions docs/")


class FormatDocContentTest(unittest.TestCase):
    def test_format_doc_names_every_indexed_source_and_encrypted_boundary(self):
        text = DOC.read_text(encoding="utf-8")
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
        text = DOC.read_text(encoding="utf-8")
        self.assertRegex(text, r"Credential fields are never read", re.IGNORECASE)
        for needle in ("ak", "sk", "base_url"):
            with self.subTest(needle=needle):
                self.assertIn("`%s`" % needle, text)

    def test_format_doc_names_incremental_and_unparsed_semantics(self):
        text = DOC.read_text(encoding="utf-8")
        for marker in ("byte cursor", "size, mtime", "fingerprint", "unparsed", "--full"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_compatibility_doc_has_python_trae_and_tui_contracts(self):
        text = (DOCDIR / "compatibility.md").read_text(encoding="utf-8")
        for marker in ("Python", "3.11", "Trae CN", "Textual 8.2", "store_content"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertGreaterEqual(len(re.findall(r"[\u4e00-\u9fff]", text)), 20)
        # The schema version belongs to the code, not to whoever last edited the table.
        # This doc said "currently 3" through the v4 migration; a reader who trusted it
        # would open a database the indexer is about to upgrade.
        stated = re.search(r"schema version is currently (\d+)", text)
        self.assertTrue(stated, "the compatibility note no longer states a schema version")
        self.assertEqual(int(stated.group(1)), db.SCHEMA_VERSION,
                         f"the doc claims v{stated.group(1)} but `ensure_schema` writes "
                         f"v{db.SCHEMA_VERSION}")

    def test_measurement_doc_is_explicitly_safe_and_has_baseline(self):
        text = (DOCDIR / "measurements.md").read_text(encoding="utf-8")
        self.assertIn("TCUT_DB=/tmp/", text)
        self.assertIn("unparsed=0", text)
        self.assertRegex(text, r"sessions=49.*projects=2.*turns=89.*toolcalls=139", re.S)

    def test_measurement_doc_records_the_model_axis_and_its_negative(self):
        text = (DOCDIR / "measurements.md").read_text(encoding="utf-8")
        for marker in ("284 rows", "42 distinct names", "7 accounts",
                       "21 rows over 11 of the 49 sessions", "11,837"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        # The lost count is the reason the key changed. Without it the rebuild reads
        # as a cosmetic schema bump, and the next collapse would be invisible again.
        self.assertRegex(text, r"models` held \*\*42 rows\*\*")
        self.assertRegex(text, r"tokens\s+0\b", re.S)

    def test_measurement_doc_keeps_the_credit_caveat_with_the_numbers(self):
        text = (DOCDIR / "measurements.md").read_text(encoding="utf-8")
        for marker in ("10 balance samples + 2 declined fetches", "154.0244",
                       "at least 1700 credits", "the only fractional balance"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class CiMatrixIsDocumentedAsItRuns(unittest.TestCase):
    """What CI runs is stated in more than one file, and one of them can silently stop
    being true. `docs/maintenance/compatibility.md` exists to be the version matrix; it
    even carries a row declaring what CI runs. On 2026-10-11 the CodeBuddy sibling's
    workflow became a `3.11` + `3.14` matrix and the document went on announcing `3.12`
    with all cases green and CI reporting success. A description of a check that no
    longer describes the check is the same failure as `schema_version`: it was true once
    and nobody re-read it. This class makes re-reading mandatory.
    """

    WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
    DOCS = ("AGENTS.md", "docs/maintenance/compatibility.md")

    MATRIX_RE = re.compile(r'^\s*python-version:\s*\[([^\]]*)\]', re.M)
    VERSION_RE = re.compile(r'\b3\.\d+\b')
    # A line only makes a claim about CI when it names the workflow file or says what CI
    # runs / is / holds / documents. Prose about the local venv is somebody else's fact
    # and must not be swept into this comparison.
    CLAIM_RE = re.compile(r'ci\.yml|CI (runs|is|matrix|section)')

    def setUp(self):
        text = self.WORKFLOW.read_text(encoding="utf-8")
        lists = self.MATRIX_RE.findall(text)
        self.assertTrue(lists, f"{self.WORKFLOW} has no python-version list to compare against")
        self.matrix = {v.strip().strip("\"'") for chunk in lists for v in chunk.split(",")}

    def offending(self, text):
        """Lines that state a CI version, with the versions they state."""
        out = []
        for number, line in enumerate(text.splitlines(), 1):
            if not self.CLAIM_RE.search(line):
                continue
            versions = set(self.VERSION_RE.findall(line))
            if versions and versions != self.matrix:
                out.append((number, sorted(versions), line.strip()[:72]))
        return out

    def test_the_workflow_states_the_versions_it_runs(self):
        self.assertTrue(self.matrix, "empty matrix: the guard would pass every document")
        for version in self.matrix:
            self.assertRegex(version, r"^3\.\d+$",
                             f"unexpected token in the CI matrix: {version!r}")

    def test_every_ci_claim_in_the_docs_states_the_real_matrix(self):
        wrong = {}
        for name in self.DOCS:
            found = self.offending((REPO / name).read_text(encoding="utf-8"))
            if found:
                wrong[name] = found
        self.assertEqual(
            wrong, {},
            f"CI runs {sorted(self.matrix)}, but these lines say otherwise: {wrong}")

    def test_the_docs_really_do_make_ci_claims(self):
        """Positive control. Both checks above would pass on documents that never
        mention CI at all — the same emptiness that makes a scan over no fields a free
        pass. So the scan's coverage is asserted, not assumed."""
        for name in self.DOCS:
            lines = [(number, line) for number, line
                     in enumerate((REPO / name).read_text(encoding="utf-8").splitlines(), 1)
                     if self.CLAIM_RE.search(line) and self.VERSION_RE.search(line)]
            self.assertGreaterEqual(len(lines), 1,
                                    f"{name} no longer states a CI version anywhere the "
                                    "check can see it, so it is unguarded")

    def test_a_stale_version_next_to_a_ci_claim_is_detected(self):
        """The failure mode being guarded against, reproduced on a synthetic document:
        the workflow moved on and the prose did not."""
        fake = ("| `.github/workflows/ci.yml` | 3.12 | the only interpreter CI runs |\n"
                "| `pyproject.toml` `requires-python` | `>=3.11` | the floor |\n")
        found = self.offending(fake)
        self.assertEqual(len(found), 1,
                         f"a document that still says 3.12 must be caught, got {found}")
        self.assertEqual(found[0][1], ["3.12"])
        # The second line states 3.11 but makes no CI claim: it is the packaging floor.
        self.assertNotIn(2, [hit[0] for hit in found])


if __name__ == "__main__":
    unittest.main()
