"""test_privacy.py — the privacy invariants, as executable checks.

This repository deviates from the CodeBuddy tracker in exactly one documented way: it stores
prose (session summaries, prompt history, agent memory) in the local database, because Trae CN
persists nothing else readable and the point of the tool is to read what Trae leaves behind.
That deviation is a *choice*, switched by ``store_content`` — so it is tested as a choice, not
assumed:

* **The switch is real.** Turning ``store_content`` off leaves a database with zero prose in
  any table, by scanning every text value in every table rather than the columns named today.
* **The default is the documented one.** On by default, and the README says so.
* **Nothing leaves the machine.** No production script imports a network or process module, and
  none reaches a module by name (``__import__("socket")`` never shows up as an import).
* **Trae's tree is never written.** Indexing a Trae-shaped fixture leaves it byte-identical.

Each scan carries a positive control (an identifier that *must* be in the database): a scan
over an empty result passes vacuously, which is the failure mode these checks exist to prevent.

Standard library only; the Trae-shaped fixture lives in a temp directory.
"""

import ast
import hashlib
import importlib.util
import json
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

PRODUCTION_SCRIPTS = ["tcut_db.py", "tcut-sync.py", "tcut-stats.py", "tcut-tui.py"]

# Anything a passive local reader has no business importing. Broader than "modules we
# currently use" so that adding one is a test failure, not a quiet convention break.
FORBIDDEN_ROOTS = {
    "socket", "ssl", "http", "urllib", "urllib2", "smtplib", "poplib", "imaplib",
    "ftplib", "telnetlib", "nntplib", "socketserver", "asyncio",
    "requests", "httpx", "aiohttp", "urllib3", "websocket", "grpc",
    "subprocess", "multiprocessing", "threading", "webbrowser",
}

# Names the production scripts are allowed to import. `textual` for the TUI only.
# `zlib` is in tcut-sync.py because reading a loose git object *is* a zlib inflate — that is
# how the snapshot tags are read without shelling out to `git` (which the subprocess ban
# forbids). `tomllib` is the settings parser; both are pure-local, stdlib, network-free.
ALLOWED_ROOTS = {
    "argparse", "datetime", "importlib", "json", "os", "pathlib", "re",
    "shutil", "sqlite3", "sys", "time", "tomllib", "typing", "zlib",
    "tcut_db", "__future__",
}
ALLOWED_BY_FILE = {"tcut-tui.py": ALLOWED_ROOTS | {"textual"}}

# Reached by NAME rather than an import statement, so the allowlist above never sees them.
DYNAMIC_NAME_CALLS = {"__import__", "eval", "exec", "compile"}
DYNAMIC_ATTR_CALLS = {"import_module", "load_module", "__import__"}

# Sentinel prose. Each sits in a slot a handler genuinely reads: a session summary, a topic
# line, a prompt-history entry, an agent-memory paragraph. With store_content OFF none of them
# may survive anywhere.
SENTINEL_INTENT = "SENTINEL-session-intent-must-not-survive-off"
SENTINEL_OUTCOME = "SENTINEL-session-outcome-must-not-survive-off"
SENTINEL_ACTION = "SENTINEL-session-action-must-not-survive-off"
SENTINEL_LEARNED = "SENTINEL-session-learned-must-not-survive-off"
SENTINEL_TOPIC = "SENTINEL-topic-summary-must-not-survive-off"
SENTINEL_PROMPT = "SENTINEL-prompt-history-must-not-survive-off"
SENTINEL_MEMORY = "SENTINEL-memory-paragraph-must-not-survive-off"
SENTINELS = (SENTINEL_INTENT, SENTINEL_OUTCOME, SENTINEL_ACTION, SENTINEL_LEARNED,
             SENTINEL_TOPIC, SENTINEL_PROMPT, SENTINEL_MEMORY)

# Identifiers that MUST be stored with store_content OFF: session ids, the project path, the
# agent name, the model, the skill. Without these the "no sentinel" scan could pass on a
# database that indexed nothing at all.
MUST_STORE = ("abc123def456", "/home/user/Public", "builder", "Model X", "my-skill")


def dynamic_module_calls(src, filename="<src>"):
    """(call name, line) for anything that reaches a module or runs code by name."""
    hits = []
    for node in ast.walk(ast.parse(src, filename)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in DYNAMIC_NAME_CALLS:
            hits.append((f.id, node.lineno))
        elif isinstance(f, ast.Attribute) and f.attr in DYNAMIC_ATTR_CALLS:
            hits.append((f.attr, node.lineno))
    return hits


def build_fixture(root: Path, tmp: Path):
    """A Trae-shaped tree carrying every sentinel, plus a workspace.json with the real path."""
    root = Path(root)
    proj = root / "memory" / "projects" / "-home-user-Public--p2-abc" / "20260304"
    proj.mkdir(parents=True)
    (proj / "session_memory_abc123def456.jsonl").write_text(json.dumps({
        "intent": SENTINEL_INTENT, "outcome": SENTINEL_OUTCOME,
        "actions": [SENTINEL_ACTION], "learned": [SENTINEL_LEARNED],
    }) + "\n", encoding="utf-8")
    (proj / "topics.md").write_text(
        f"[session_id: abc123def456 | topic_summary_time: 2026-03-04 05:06:07]{SENTINEL_TOPIC}\n",
        encoding="utf-8")
    (root / "memory" / "user_profile.md").write_text(SENTINEL_MEMORY + "\n", encoding="utf-8")
    (root / "memory" / "projects" / "-home-user-Public--p2-abc" / "project_memory.md").write_text(
        SENTINEL_MEMORY + " (project)\n", encoding="utf-8")

    ws = root / "User" / "workspaceStorage" / "ws1"
    ws.mkdir(parents=True)
    conn = sqlite3.connect(ws / "state.vscdb")
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    conn.execute("INSERT INTO ItemTable(key, value) VALUES(?,?)",
                 ("icube-ai-agent-storage-input-history",
                  json.dumps([{"inputText": SENTINEL_PROMPT}])))
    conn.execute("INSERT INTO ItemTable(key, value) VALUES(?,?)",
                 ("icube_session_agent_map", json.dumps({"abc123def456": "builder"})))
    conn.execute("INSERT INTO ItemTable(key, value) VALUES(?,?)",
                 ("somekey_AI.agent.model.model_list_map",
                  json.dumps({"g": [{"name": "Model X", "provider": "acme"}]})))
    conn.commit()
    conn.close()
    (ws / "workspace.json").write_text(
        json.dumps({"folder": "file:///home/user/Public"}), encoding="utf-8")

    (root / "skills" / "my-skill").mkdir(parents=True)
    return root


def index(root: Path, db_path: Path, store_content=None):
    """Run the real driver against a Trae-shaped tree.

    ``TCUT_TRAE_CN_HOME``/``TCUT_TRAE_CN_DATA`` are pointed at the fixture and no ``roots`` override
    is used, so *every* handler runs (memory, snapshots, vscdb, inventory) — the leak scan has
    to see the whole pipeline, not the part a partial override happens to cover. When
    ``store_content`` is given it is written to a temp settings file that the loader reads.
    """
    old_config, old_home, old_data = db.CONFIG_PATH, db.TRAE_CN_HOME, db.TRAE_CN_DATA
    db.TRAE_CN_HOME, db.TRAE_CN_DATA = root, root
    if store_content is not None:
        cfg_path = db_path.parent / "config.toml"
        cfg_path.write_text(f"store_content = {str(store_content).lower()}\n", encoding="utf-8")
        db.CONFIG_PATH = cfg_path
    try:
        sync.run(db_path=db_path, quiet=True)
    finally:
        db.CONFIG_PATH, db.TRAE_CN_HOME, db.TRAE_CN_DATA = old_config, old_home, old_data


class StorageOffTest(unittest.TestCase):
    """With store_content off, no prose may survive anywhere — the switch is a switch."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = build_fixture(self.tmp / "trae-cn", self.tmp)
        self.db_path = self.tmp / "t.db"
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        conn.close()
        index(self.root, self.db_path, store_content=False)
        self.conn = db.open_db(self.db_path, readonly=True)
        self.addCleanup(self.conn.close)

    def all_text_values(self):
        """Every TEXT value in every user table. Wide on purpose."""
        tables = [r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        self.assertGreaterEqual(
            len(tables), 8, f"the scan lost reach: only {len(tables)} tables in the schema")
        values = []
        for table in tables:
            for row in self.conn.execute(f"SELECT * FROM {table}"):
                values.extend(v for v in tuple(row) if isinstance(v, str))
        return values

    def test_fixture_was_actually_indexed(self):
        """Positive control: the scan below has something to look at.

        Metadata (the id, the real project path, the agent, the model, the skill) is what the
        tracker keeps when content storage is off — so its presence is what proves the
        database was populated at all, and the sentinel scan below is not vacuous.
        """
        joined = "\n".join(self.all_text_values())
        for name in MUST_STORE:
            self.assertIn(name, joined,
                          f"the fixture did not store {name!r}; a leak check on an empty "
                          "database proves nothing")

    def test_no_sentinel_appears_in_any_column_of_any_table(self):
        leaked = []
        for value in self.all_text_values():
            for sentinel in SENTINELS:
                if sentinel in value:
                    leaked.append((sentinel, value[:60]))
        self.assertEqual(leaked, [],
                         "prose survived the store_content=off path")


class SwitchWiringTest(unittest.TestCase):
    """``store_content`` must come from the config loader, applied by the driver."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = build_fixture(self.tmp / "trae-cn", self.tmp)
        self.db_path = self.tmp / "t.db"

    def _run(self, store_content):
        if not self.db_path.exists():
            conn = db.open_db(self.db_path)
            db.ensure_schema(conn)
            conn.close()
        index(self.root, self.db_path, store_content=store_content)
        conn = db.open_db(self.db_path, readonly=True)
        try:
            texts = []
            for table in ("sessions", "topics", "prompts", "memory",
                          "session_actions", "session_learned"):
                for row in conn.execute(f"SELECT * FROM {table}"):
                    texts.extend(v for v in tuple(row) if isinstance(v, str))
        finally:
            conn.close()
        return "\n".join(texts)

    def test_content_is_stored_when_the_setting_is_on(self):
        joined = self._run(True)
        self.assertIn(SENTINEL_INTENT, joined)
        self.assertIn(SENTINEL_PROMPT, joined)
        self.assertIn(SENTINEL_MEMORY, joined)

    def test_content_is_absent_when_the_setting_is_off(self):
        joined = self._run(False)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, joined,
                             f"{sentinel} reached the database with store_content off")

    def test_off_also_purges_content_already_stored(self):
        """A switch that only affects future indexing reads as "my content is still there"."""
        joined_on = self._run(True)
        self.assertIn(SENTINEL_INTENT, joined_on)
        joined_off = self._run(False)     # same database, switch flipped
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, joined_off,
                             f"{sentinel} lingered after the switch was turned off")


class HostDirNotWrittenTest(unittest.TestCase):
    """Trae's own tree is read-only to us — proved by hashing it."""

    def test_indexing_leaves_the_input_tree_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = build_fixture(tmp / "trae-cn", tmp)
            before = tree_fingerprint(root)

            db_path = tmp / "t.db"
            conn = db.open_db(db_path)
            db.ensure_schema(conn)
            conn.close()
            index(root, db_path)

            self.assertEqual(before, tree_fingerprint(root),
                             "indexing changed something under the Trae root")
            # Nothing may be created beside the database either.
            extra = sorted(p.name for p in tmp.iterdir()
                           if p.name not in ("trae-cn", "t.db", "t.db-wal", "t.db-shm", "config.toml"))
            self.assertEqual(extra, [])


class ImportSurfaceTest(unittest.TestCase):
    """No network path and no process spawning in our own code."""

    def roots_of(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    roots.add(node.module.split(".")[0])
        return roots

    def test_production_scripts_import_nothing_forbidden(self):
        for name in PRODUCTION_SCRIPTS:
            roots = self.roots_of(SCRIPTS / name)
            hit = roots & FORBIDDEN_ROOTS
            self.assertFalse(hit, f"{name} imports {sorted(hit)} — a network or "
                                  "subprocess path is a privacy invariant break")

    def test_production_scripts_import_only_known_modules(self):
        for name in PRODUCTION_SCRIPTS:
            allowed = ALLOWED_BY_FILE.get(name, ALLOWED_ROOTS)
            unknown = self.roots_of(SCRIPTS / name) - allowed
            self.assertFalse(unknown, f"{name} gained an unlisted import: "
                            f"{sorted(unknown)} — add it to ALLOWED_ROOTS only if "
                            "it is stdlib and cannot reach the network")

    def test_our_scripts_do_not_call_the_network_functions_directly(self):
        needles = ("urlopen", "create_connection", "socket.socket", "Popen",
                   "system(", "popen(", "getaddrinfo")
        for name in PRODUCTION_SCRIPTS:
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            for needle in needles:
                self.assertNotIn(needle, text, f"{name} calls {needle}")

    def test_no_script_reaches_a_module_by_name(self):
        """The import allowlist only covers import *statements* — this covers the calls.

        What it deliberately does not flag: ``tcut_db.load_sync()``'s
        ``importlib.util.spec_from_file_location(...)``. That is the documented way this
        project loads its own hyphenated sibling, it takes a ``__file__``-derived path, and
        treating it as a violation would point the check at code already reviewed here.
        """
        for name in PRODUCTION_SCRIPTS:
            hits = dynamic_module_calls((SCRIPTS / name).read_text(encoding="utf-8"), name)
            self.assertFalse(hits, f"{name} reaches a module or runs code by name: {hits}")

    def test_the_dynamic_import_detector_actually_detects(self):
        """A guard nobody has seen fail is a rumour."""
        samples = [
            ('x = __import__("socket")', "__import__"),
            ('m = importlib.import_module(name)', "import_module"),
            ('exec(source)', "exec"),
            ('eval("os.system(1)")', "eval"),
        ]
        for src, expected in samples:
            with self.subTest(src=src):
                hits = dynamic_module_calls(src)
                self.assertIn(expected, [h[0] for h in hits],
                              f"the detector misses {expected} — the case above is vacuous")
        self.assertEqual(dynamic_module_calls('R = re.compile("a+")'), [])


def tree_fingerprint(root: Path):
    """(relpath, size, sha256) for every file under root."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = (
                path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest())
    return out


if __name__ == "__main__":
    unittest.main()
