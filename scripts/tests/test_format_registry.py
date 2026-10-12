"""test_format_registry.py — the Trae CN format coupling is registered, not scattered.

``tcut`` reads JSON and SQLite that Trae owns. A renamed key or field raises nothing:
the panels quietly empty out, `tcut sync` prints "done", CI stays green. The registry
at the top of ``tcut-sync.py`` is the one place that states what we depend on, and these
tests read that file's AST to prove the statement is still true — in both directions, so
the block cannot decay into a description of a parser that stopped matching it.

Two enforcement styles, chosen to match how each entry is used:

* ``state.vscdb`` **keys** are **source** — the parser reaches them through
  ``VSCDB_KEYS``, and a bare literal at a call site fails;
* **JSON field names** stay **inline** in the handlers (a parser is easier to trust
  when the field it grabs is visible) and are *mirrored* by ``VSCDB_FIELDS``: an
  unregistered read fails and a registered read nobody performs fails.

The ``unparsed`` vocabulary is checked the same way as the fields: a reason the code
emits without registering fails, and a registered reason nobody emits fails.

Every failure names the offending line, because the point of the check is to point at
the call sites a rename still owes.

Standard library only; nothing is executed beyond importing the parser.
"""

import ast
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401 -- tripwire: the suite must never open the real database

sys.path.insert(0, str(SCRIPTS))
import tcut_db as db  # noqa: E402

sync = db.load_sync()
SYNC_PATH = SCRIPTS / "tcut-sync.py"
SRC = SYNC_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SRC)

# The functions that read a `state.vscdb` JSON blob. Their literal `.get("<key>")`
# arguments are claims about Trae's naming; a read outside this set is a different
# source (a file, a log line) and states nothing about the vscdb shape.
VSCDB_READERS = ("_ingest_vscdb", "_consumption_rate", "_context_window")

# Fields that can carry a custom endpoint's credentials. Absent from VSCDB_FIELDS on
# purpose, and this set is what proves they stay unread.
CREDENTIAL_FIELDS = ("ak", "sk", "base_url", "custom_config")


def get_literal_keys(tree, funcs):
    """``{key: [lineno, ...]}`` for every ``x.get("<literal>", ...)`` inside ``funcs``."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in funcs:
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "get" and sub.args
                        and isinstance(sub.args[0], ast.Constant)
                        and isinstance(sub.args[0].value, str)):
                    out.setdefault(sub.args[0].value, []).append(sub.lineno)
    return out


def note_unparsed_reasons(tree):
    """``[(lineno, reason), ...]`` for every ``note_unparsed(conn, "<reason>", ...)``."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "note_unparsed" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            out.append((node.lineno, node.args[1].value))
    return out


def bare_key_literals(tree):
    """A literal string handed to ``_vscdb_value``/``_keys_like`` — an inlined key."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("_vscdb_value", "_keys_like")
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            out.append((node.lineno, node.func.id, node.args[1].value))
    return out


def where(pairs):
    return ", ".join(f"L{p[0]}:{p[1]}" if len(p) > 1 else f"L{p}" for p in pairs)


class VscdbFieldsAreRegisteredTest(unittest.TestCase):
    """JSON field reads cannot go off the books."""

    def test_every_field_read_is_registered(self):
        reads = get_literal_keys(TREE, VSCDB_READERS)
        unregistered = {k: v for k, v in reads.items()
                        if k not in sync.VSCDB_FIELDS}
        self.assertEqual(
            unregistered, {},
            "field(s) read from a state.vscdb blob without being registered in the "
            f"format registry: {unregistered} — add them to VSCDB_FIELDS in "
            "tcut-sync.py (and check they are not argument *values*)")

    def test_no_registered_field_is_dead(self):
        """A registered field nobody reads is the `schema_version` failure mode: a
        declaration that stopped being true."""
        reads = set(get_literal_keys(TREE, VSCDB_READERS))
        dead = sync.VSCDB_FIELDS - reads
        self.assertEqual(dead, frozenset(),
                         f"registered but never read: {sorted(dead)}")

    def test_the_registry_covers_a_real_surface(self):
        # Positive control: a scan over an empty result would pass vacuously, so pin
        # that the parser really is reading a registered surface.
        self.assertGreaterEqual(len(get_literal_keys(TREE, VSCDB_READERS)), 15)

    def test_credential_fields_are_never_read(self):
        """A custom-provider entry carries `ak`/`sk`/`base_url`/`custom_config` beside
        the fields we read. If one ever appears as a `.get()` key, it can reach the
        index — this is the static half of the sentinel test in `test_sync.py`."""
        reads = get_literal_keys(TREE, VSCDB_READERS)
        leaked = {f: reads[f] for f in CREDENTIAL_FIELDS if f in reads}
        self.assertEqual(leaked, {},
                         f"a credential field is read from the catalog: {leaked}")


class VscdbKeysAreCentralizedTest(unittest.TestCase):
    """``state.vscdb`` keys must be reached through the registry."""

    def test_no_bare_literal_key(self):
        offenders = bare_key_literals(TREE)
        self.assertEqual(
            offenders, [],
            "a state.vscdb key inlined at the call site — use VSCDB_KEYS instead: "
            + ", ".join(f"L{ln}.{fn}({val!r})" for ln, fn, val in offenders))

    def test_every_registered_key_is_used(self):
        """Guards against the registry becoming a second `schema_version`: a key
        declared, plausible-looking, and read by nothing."""
        unused = [role for role in sync.VSCDB_KEYS
                  if f'VSCDB_KEYS["{role}"]' not in SRC]
        self.assertEqual(unused, [], f"declared and never used: {unused}")

    def test_every_registered_pattern_is_the_one_on_disk(self):
        # The values are what `_vscdb_value`/`_keys_like` match against; a typo would
        # read as an unclaimed source, so each must still be a literal in the file.
        missing = [p for p in sync.VSCDB_KEYS.values() if f'"{p}"' not in SRC]
        self.assertEqual(missing, [], f"registry pattern not present in the source: {missing}")


class UnparsedVocabularyIsRegisteredTest(unittest.TestCase):
    def test_every_emitted_reason_is_registered(self):
        emitted = note_unparsed_reasons(TREE)
        unregistered = sorted({r for _, r in emitted if r not in sync.UNPARSED_REASONS})
        self.assertEqual(
            unregistered, [],
            "reason(s) counted in `unparsed` without being registered in "
            f"UNPARSED_REASONS: {unregistered}")

    def test_no_registered_reason_is_dead(self):
        emitted = {r for _, r in note_unparsed_reasons(TREE)}
        dead = sorted(set(sync.UNPARSED_REASONS) - emitted)
        self.assertEqual(dead, [], f"registered but never emitted: {dead}")

    def test_the_vocabulary_is_not_empty(self):
        self.assertGreaterEqual(len(note_unparsed_reasons(TREE)), 10,
                                "the scan found no reasons, so it proves nothing")


if __name__ == "__main__":
    unittest.main()
