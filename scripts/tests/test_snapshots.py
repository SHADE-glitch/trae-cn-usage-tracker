"""test_snapshots.py — a destructive step must always have a way back.

A ``--full`` rebuild deletes every indexed row before re-reading Trae's data, and a schema
migration clears the tables a future version cannot interpret. Both are only safe if the old
state is kept, so these cases assert the two halves of that promise:

* the snapshot is taken **before** the change, so it still shows the old shape — a snapshot
  taken afterwards could not roll the change back;
* restoring it actually brings the rows back.

Retention is tested too, including the one thing that must never happen: pruning a
``usage.db.bak-*`` file somebody made by hand.

Standard library only; every database here lives in a temp directory.
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401 -- tripwire: the suite must never open the real database
sys.path.insert(0, str(SCRIPTS))

import tcut_db as db  # noqa: E402
sync = db.load_sync()


def build_old_database(path: Path) -> None:
    """A database as an earlier release of this tool would have left it.

    Enough to make ``_has_indexed_state`` true (so a migration snapshots) and with a
    shape the current schema would rewrite — a v1 ``sessions`` table carrying a row.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, project TEXT,"
        " project_key TEXT, day TEXT, agent TEXT, intent TEXT, outcome TEXT,"
        " turns INTEGER DEFAULT 0, toolcalls INTEGER DEFAULT 0,"
        " first_ts INTEGER, last_ts INTEGER);"
        "INSERT INTO sessions(session_id, project, day) VALUES"
        " ('old-1','/old','20260101'),('old-2','/old','20260102');"
    )
    conn.commit()
    conn.close()


class MigrationSnapshotTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "usage.db"

    def test_migrate_snapshots_the_old_shape(self):
        build_old_database(self.db_path)
        self.assertNotIn("failed", db.migrate(self.db_path), "migrate reported failure")

        snaps = db.list_backups(self.db_path)
        pre = [p for p in snaps if "pre-migration" in p.name]
        self.assertEqual(len(pre), 1, f"expected one pre-migration snapshot: {snaps}")

        # The snapshot must be the BEFORE state: the old rows are there.
        conn = sqlite3.connect(pre[0])
        try:
            n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 2, "the snapshot is not the pre-migration state")

    def test_migrate_on_a_current_database_snapshots_nothing(self):
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        conn.close()
        db.migrate(self.db_path)
        db.migrate(self.db_path)
        self.assertEqual(db.list_backups(self.db_path), [],
                         "a no-op migration that still snapshots would fill the backups "
                         "directory on every TUI launch")


class ModelsMigrationTest(unittest.TestCase):
    """v1 keyed ``models`` on the name; v2 keys it on (account, group, name).

    The rebuild is safe only because the rows are re-derivable from Trae, and only the
    source that changed may be re-read: resetting every cursor would throw away
    offsets that have nothing to do with the catalog.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "usage.db"

    def _build_v1(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta(key, value) VALUES('schema_version','1');"
            "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, project TEXT,"
            " project_key TEXT, day TEXT, agent TEXT, intent TEXT, outcome TEXT,"
            " turns INTEGER DEFAULT 0, toolcalls INTEGER DEFAULT 0,"
            " first_ts INTEGER, last_ts INTEGER);"
            "INSERT INTO sessions(session_id, project) VALUES('old-1','/old');"
            "CREATE TABLE models (name TEXT PRIMARY KEY, provider TEXT);"
            "INSERT INTO models VALUES('DeepSeek-V4','volc');"
            "INSERT INTO models VALUES('Doubao-Seed-Code','acme');"
            "CREATE TABLE sync_state (source TEXT PRIMARY KEY, size INTEGER,"
            " mtime REAL, offset INTEGER);"
            "INSERT INTO sync_state VALUES('/x/User/workspaceStorage/w1/state.vscdb',"
            " 100, 1.0, 0);"
            "INSERT INTO sync_state VALUES('/x/memory/projects/p/20260304/"
            "session_memory_a.jsonl', 200, 1.0, 64);"
        )
        conn.commit()
        conn.close()

    def _columns(self, conn, table):
        return [r[1] for r in conn.execute('PRAGMA table_info("%s")' % table)]

    def test_v1_models_table_is_rebuilt_and_only_vscdb_cursors_reset(self):
        self._build_v1()
        self.assertEqual(db.migrate(self.db_path), "migrated")

        conn = db.open_db(self.db_path, readonly=True)
        try:
            cols = self._columns(conn, "models")
            self.assertIn("account", cols, "the name-only key survived")
            self.assertIn("consumption_rate", cols)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM models").fetchone()[0], 0,
                             "v1 rows were copied into a key that collides on the name")
            sources = [r[0] for r in conn.execute(
                "SELECT source FROM sync_state ORDER BY source")]
            self.assertEqual(len(sources), 1,
                             "a cursor unrelated to the catalog was reset")
            self.assertIn("session_memory_a.jsonl", sources[0])
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM sessions").fetchone()[0], 1,
                "the migration touched indexed sessions")
            self.assertEqual(
                conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                str(db.SCHEMA_VERSION))
            self.assertIn("agent_label", self._columns(conn, "session_models"))
        finally:
            conn.close()

    def test_a_current_database_reports_current_not_migrated(self):
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        conn.close()
        self.assertEqual(db.migrate(self.db_path), "current",
                         "the v2 migration claimed to change something twice")

    def test_the_old_shape_is_kept_before_the_rebuild(self):
        self._build_v1()
        self.assertEqual(db.migrate(self.db_path), "migrated")
        pre = [p for p in db.list_backups(self.db_path) if "pre-migration" in p.name]
        self.assertEqual(len(pre), 1, "a migration that drops a table must snapshot first")
        conn = sqlite3.connect(pre[0])
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM models").fetchone()[0], 2,
                             "the snapshot is not the pre-migration state")
        finally:
            conn.close()



class CreatedTsMigrationTest(unittest.TestCase):
    """v4 adds a column for a *derived* time; upgrading must fill it, not leave 25
    sessions unplaceable — and must never write into `last_ts`, which means measured.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "usage.db"

    def _columns(self, conn, table):
        return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]

    def _build_v3(self):
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        # Exactly the v3 shape: every current table, minus the new column.
        conn.execute("ALTER TABLE sessions DROP COLUMN created_ts")
        conn.execute("INSERT INTO sessions(session_id, agent, last_ts) VALUES"
                     "('6a6e9c0d36e7526885aad757','builder',NULL)")
        conn.execute("INSERT INTO sessions(session_id, agent, last_ts) VALUES"
                     "('measured000000000000000001','builder',1700000000000)")
        conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
        conn.commit()
        conn.close()

    def test_upgrading_a_v3_database_adds_the_column_and_backfills_it(self):
        self._build_v3()
        self.assertEqual(db.migrate(self.db_path), "migrated")
        conn = db.open_db(self.db_path)
        try:
            self.assertIn("created_ts", self._columns(conn, "sessions"))
            got = conn.execute("SELECT created_ts, last_ts FROM sessions"
                               " WHERE session_id LIKE '6a6e%'").fetchone()
            self.assertEqual(got[0], int("6a6e9c0d", 16) * 1000,
                             "the derived creation second was not backfilled")
            self.assertIsNone(got[1], "the migration wrote a derived time into last_ts,"
                                      " which means measured activity")
            odd = conn.execute("SELECT created_ts FROM sessions"
                               " WHERE session_id = 'measured000000000000000001'").fetchone()
            self.assertIsNone(odd[0],
                              "an id whose prefix is not a hex second got guessed at")
            self.assertEqual(
                conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                str(db.SCHEMA_VERSION))
        finally:
            conn.close()

    def test_an_id_that_is_not_a_plausible_second_is_left_undated(self):
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        for sid in ("0000000000000000000000ff",   # 1970 — not this app's era
                    "ffffffff0000000000000000",   # year 2096 — not this app's era
                    "6a6e9c0d36e7526885aad757"):  # a real session id
            conn.execute("INSERT INTO sessions(session_id) VALUES(?)", (sid,))
        conn.commit()
        self.assertEqual(db.stamp_created_ts(conn), 1,
                         "both impossible prefixes were stamped, or the real one was not")
        conn.commit()
        stamped = {r[0] for r in conn.execute(
            "SELECT session_id FROM sessions WHERE created_ts IS NOT NULL")}
        self.assertEqual(stamped, {"6a6e9c0d36e7526885aad757"})
        conn.close()


class FullRebuildSnapshotTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.db_path = self.tmp / "usage.db"
        self.root = self.tmp / "trae-cn"

    def _write(self, n=4):
        proj = self.root / "memory" / "projects" / "-p--p2-a" / "20260304"
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "session_memory_abc123.jsonl").write_text(
            "".join(json.dumps({"intent": f"i{k}", "outcome": "o"}) + "\n"
                    for k in range(n)), encoding="utf-8")

    def _index(self, full=False):
        old_home, old_data = db.TRAE_CN_HOME, db.TRAE_CN_DATA
        db.TRAE_CN_HOME, db.TRAE_CN_DATA = self.root, self.root
        try:
            sync.run(db_path=self.db_path, full=full, quiet=True)
        finally:
            db.TRAE_CN_HOME, db.TRAE_CN_DATA = old_home, old_data

    def test_full_rebuild_snapshots_then_restore_returns_the_rows(self):
        self._write(4)
        self._index()
        self._index(full=True)

        pre = [p for p in db.list_backups(self.db_path) if "pre-full-rebuild" in p.name]
        self.assertEqual(len(pre), 1, "a rebuild that clears tables must snapshot")

        conn = db.open_db(self.db_path)
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()

        db.restore(pre[0], db_path=self.db_path)
        conn = db.open_db(self.db_path, readonly=True)
        try:
            after = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(after, 1, "restore did not bring the row back")

    def test_restore_also_saves_what_it_is_overwriting(self):
        self._write(2)
        self._index()
        conn = db.open_db(self.db_path)
        try:
            snap = db.snapshot(conn, reason="manual")
        finally:
            conn.close()

        conn = db.open_db(self.db_path)
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()

        db.restore(snap, db_path=self.db_path)
        reasons = [p.name for p in db.list_backups(self.db_path)]
        self.assertTrue(any("pre-restore" in r for r in reasons),
                        f"the overwritten database was not kept: {reasons}")

    def test_empty_database_is_not_snapshotted_by_full(self):
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        conn.close()
        self._index(full=True)
        self.assertEqual(db.list_backups(self.db_path), [],
                         "snapshotting an empty index is clutter, not safety")


class RetentionTest(unittest.TestCase):
    """Pruning may only ever delete snapshots this module made."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "usage.db"
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        conn.close()

    def _make(self, name, age_seconds):
        path = db.backup_dir(self.db_path) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t(x)")
        conn.commit()
        conn.close()
        stamp = 1_700_000_000 - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_only_the_newest_keep_survive_and_in_mtime_order(self):
        made = [self._make(f"usage-2023010{i}-120000-manual.db", i * 10)
                for i in range(1, 8)]          # 7 snapshots, oldest = i=7
        gone = db.prune_backups(self.db_path, keep=db.BACKUP_KEEP)
        left = sorted(p.name for p in db.backup_dir(self.db_path).glob(db.BACKUP_PATTERN))
        self.assertEqual(len(left), db.BACKUP_KEEP, f"kept {left}")
        self.assertEqual({p.name for p in gone}, {made[5].name, made[6].name},
                         "pruning must remove exactly the two oldest")

    def test_same_second_snapshots_are_ordered_by_mtime_not_name(self):
        first = self._make("usage-20230101-120000-manual.db", 60)
        second = self._make("usage-20230101-120000-manual-1.db", 10)
        gone = db.prune_backups(self.db_path, keep=1)
        self.assertEqual([p.name for p in gone], [first.name],
                         "the older of two same-second snapshots must be the one pruned")
        self.assertTrue(second.exists())

    def test_hand_made_backups_are_never_pruned_but_are_restorable(self):
        hand = self.db_path.parent / "usage.db.bak-20261007-093557"
        conn = sqlite3.connect(hand)
        conn.execute("CREATE TABLE t(x)")
        conn.commit()
        conn.close()
        for i in range(1, 9):
            self._make(f"usage-2023010{i}-120000-manual.db", i * 10)

        gone = db.prune_backups(self.db_path, keep=3)
        self.assertNotIn(hand, gone)
        self.assertTrue(hand.exists(), "pruning deleted a hand-made backup")
        self.assertIn(hand, db.list_backups(self.db_path),
                      "a hand-made snapshot should still be offered as a restore source")


class RestoreErrorTest(unittest.TestCase):
    def test_unknown_backup_is_refused_before_anything_is_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "usage.db"
            conn = db.open_db(live)
            db.ensure_schema(conn)
            conn.close()
            with self.assertRaises(FileNotFoundError):
                db.restore(Path(tmp) / "nope.db", db_path=live)
            self.assertEqual(db.list_backups(live), [])


if __name__ == "__main__":
    unittest.main()
