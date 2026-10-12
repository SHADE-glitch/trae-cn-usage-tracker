"""tcut_db — storage layer for the Trae CN usage tracker.

Defines the SQLite schema (tables + views) and small helpers shared by the
indexer (tcut-sync.py), the headless CLI (tcut-stats.py) and the TUI
(tcut-tui.py).

The tracker is a *passive reader*: it never writes into Trae's own
directories. It only reads ``~/.trae-cn`` and ``~/.config/Trae CN`` and writes
this one database.

Unlike the CodeBuddy tracker, Trae CN does **not** persist per-tool-call records
in plaintext — its agent store (``ModularData/ai-agent/database.db``) is
encrypted. So this schema is *session-level*: one row per agent session, the model
each session was set to, the account-scoped model catalog, and the inventory of what
is installed. Token counts are not on disk at all; see the measurements in
``docs/maintenance/trae-cn-format.md`` before adding any parser that claims them.

Standard library only.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sqlite3
import sys
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

SCHEMA_VERSION = 3

# --- locations -------------------------------------------------------------

# The agent's own home: skills, plugins, mcps, memory (session summaries).
TRAE_CN_HOME = Path(
    os.environ.get("TCUT_TRAE_CN_HOME", str(Path.home() / ".trae-cn"))
)

# The VS Code (Electron) user-data dir: workspaceStorage/*/state.vscdb, logs.
TRAE_CN_DATA = Path(
    os.environ.get("TCUT_TRAE_CN_DATA", str(Path.home() / ".config" / "Trae CN"))
)

DB_PATH = Path(
    os.environ.get(
        "TCUT_DB",
        str(Path.home() / ".local" / "share" / "trae-cn-usage-tracker" / "usage.db"),
    )
)


# --- settings --------------------------------------------------------------
#
# One file, outside the repository, read with the standard library's own TOML parser
# (``tomllib``, Python 3.11+ — which is the floor this project already promises), so a
# settings layer cost no dependency. Precedence is environment > file > DEFAULTS.
#
# A file that cannot be read is an error, not a fallback. Someone editing
# ``~/.config/tcut/config.toml`` and being silently ignored is the worst outcome this
# layer can produce, so every failure names the path or variable and the key.

CONFIG_PATH = Path(os.environ.get("TCUT_CONFIG") or (
    Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    / "tcut" / "config.toml"
))

# Defaults are the values the interface already shipped with. Changing one here is a
# behaviour change, and ``test_config.py`` pins each against the constant it replaces.
DEFAULTS = {
    "top_n": 5,            # rows in the Dashboard's Top projects / Top agents
    "log_limit": 100,      # Prompts page rows
    "detail_limit": 200,   # rows on a history screen
    "name_cap": 28,        # widest cell a table renders
    "refresh_secs": 5,     # TUI redraw timer
    "sync_secs": 30,       # TUI auto-sync timer
    # Session summaries and prompt history are prose written by the model and by
    # you. Storing them is a deliberate, documented deviation from the CodeBuddy
    # tracker's metadata-only rule; this switch turns it off (metadata only).
    "store_content": True,
}

ENV_NAMES = {
    "top_n": "TCUT_TOP_N",
    "log_limit": "TCUT_LOG_LIMIT",
    "detail_limit": "TCUT_DETAIL_LIMIT",
    "name_cap": "TCUT_NAME_CAP",
    "refresh_secs": "TCUT_REFRESH_SECS",
    "sync_secs": "TCUT_SYNC_SECS",
    "store_content": "TCUT_STORE_CONTENT",
}

# (low, high, accepted types). Ranges are wide enough to be useful and tight enough that
# a typo fails loudly: 0 rows of anything is not a preference, it is a blank panel.
_BOUNDS = {
    "top_n": (1, 100, int),
    "log_limit": (1, 1000, int),
    "detail_limit": (1, 1000, int),
    # below 8 nothing readable survives the cut; above ~200 the cap is not a cap
    "name_cap": (8, 200, int),
    "refresh_secs": (0.5, 3600, (int, float)),
    "sync_secs": (1, 86400, (int, float)),
    "store_content": (None, None, bool),
}

_TRUE_STRINGS = {"1", "true", "yes", "on"}


class ConfigError(ValueError):
    """The settings file, or an environment value, is not usable."""


def _setting_value(key, value, source):
    low, high, kind = _BOUNDS[key]
    if kind is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{source}: {key} = {value!r} must be true or false")
        return value
    # bool is an int subclass: ``top_n = true`` must not quietly become top_n = 1.
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ConfigError(
            f"{source}: {key} = {value!r} must be "
            f"{'a whole number' if kind is int else 'a number'}")
    if not low <= value <= high:
        raise ConfigError(f"{source}: {key} = {value!r} is outside {low}..{high}")
    return value


def _env_value(key, raw, source):
    low, high, kind = _BOUNDS[key]
    if kind is bool:
        text = raw.strip().lower()
        if text in _TRUE_STRINGS:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ConfigError(f"{source}: {key} = {raw!r} must be true or false")
    try:
        value = int(raw)
    except ValueError:
        try:
            value = float(raw)
        except ValueError:
            raise ConfigError(f"{source}: {key} = {raw!r} is not a number") from None
    return _setting_value(key, value, source)


def load_config(path=None):
    """Resolve settings from environment, then file, then ``DEFAULTS``.

    Never raises for a *missing* file — that is the normal case — but raises
    ``ConfigError`` for a malformed one, an unknown key, or an unusable value in
    either source.
    """
    cfg = dict(DEFAULTS)
    source = Path(path if path is not None else CONFIG_PATH)
    if source.is_file():
        try:
            parsed = tomllib.loads(source.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{source}: not valid TOML ({exc})") from None
        for key, value in parsed.items():
            if key not in DEFAULTS:
                raise ConfigError(
                    f"{source}: unknown setting {key!r} — known keys are "
                    f"{', '.join(sorted(DEFAULTS))}")
            cfg[key] = _setting_value(key, value, str(source))
    for key, env in ENV_NAMES.items():
        raw = os.environ.get(env)
        if raw is None:
            continue
        cfg[key] = _env_value(key, raw, f"{env} environment variable")
    return cfg


def load_sync():
    """Import ``tcut-sync.py`` — a hyphenated name cannot be imported normally.

    The TUI's sync worker, ``tcut format`` and the tests all need the parser as
    a module, so the loader lives here instead of being copied a third time.
    """
    name = "tcut_sync_embedded"
    mod = sys.modules.get(name)
    if mod is None:
        path = Path(__file__).with_name("tcut-sync.py")
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


# --- schema ----------------------------------------------------------------

TABLES_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- One row per agent session. A session is identified by its id and located by
-- the project it ran in. `intent`/`outcome` are the model-written summary from
-- Trae's memory layer (prose); when `store_content` is off they stay NULL.
-- `turns`/`toolcalls` are *counts* derived from the per-session snapshot git
-- tags — Trae never writes the tool NAMES anywhere readable.
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project    TEXT,             -- decoded project path, or the raw key
    project_key TEXT,            -- the on-disk directory name under memory/projects
    day        TEXT,             -- YYYYMMDD of the summary file's folder
    agent      TEXT,             -- agent id from the session->agent map
    intent     TEXT,
    outcome    TEXT,
    turns      INTEGER DEFAULT 0,
    toolcalls  INTEGER DEFAULT 0,
    first_ts   INTEGER,          -- epoch ms, best known
    last_ts    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sessions_last ON sessions(last_ts);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_key);

-- session_memory.actions[] — the model's own natural-language list of what it
-- did. Ordered; `idx` preserves the order the summary recorded.
CREATE TABLE IF NOT EXISTS session_actions (
    session_id TEXT,
    idx        INTEGER,
    text       TEXT,
    PRIMARY KEY (session_id, idx)
);

-- session_memory.learned[] — the same, for the "learned" list.
CREATE TABLE IF NOT EXISTS session_learned (
    session_id TEXT,
    idx        INTEGER,
    text       TEXT,
    PRIMARY KEY (session_id, idx)
);

-- One row per topics.md line: `[session_id: X | topic_summary_time: T]正文`.
CREATE TABLE IF NOT EXISTS topics (
    session_id TEXT,
    ts         INTEGER,
    project_key TEXT,
    summary    TEXT,
    PRIMARY KEY (session_id, ts)
);

-- User input history from each workspace's state.vscdb. Keyed by workspace and
-- position; the history carries no timestamp of its own.
CREATE TABLE IF NOT EXISTS prompts (
    workspace  TEXT,
    idx        INTEGER,
    text       TEXT,
    PRIMARY KEY (workspace, idx)
);

-- Workspace id -> the real folder it opened (from workspace.json). Used to
-- label prompts and to resolve a memory project_key to a real path.
CREATE TABLE IF NOT EXISTS workspaces (
    workspace TEXT PRIMARY KEY,
    folder    TEXT
);

-- Agent definitions (from state.vscdb currentAgentData) and the agents that
-- appear in the session->agent map. `kind` is the definition's `type`.
CREATE TABLE IF NOT EXISTS agents (
    name        TEXT PRIMARY KEY,
    kind        TEXT,
    description TEXT
);

-- Models advertised to the client (state.vscdb `<uid>_AI.agent.model.model_list_map`).
-- Keyed by (account, group_name, name), NOT by name: one real footprint holds 284
-- catalog entries under only 42 distinct names, so a name-only key silently drops
-- 242 of them. `consumption_rate` is Trae's own credits-per-call multiplier — it is
-- a price, not a measurement of what was spent.
CREATE TABLE IF NOT EXISTS models (
    account          TEXT,
    group_name       TEXT,
    name             TEXT,
    display_name     TEXT,
    provider         TEXT,
    model_type       TEXT,
    fee_level        INTEGER,
    consumption_rate REAL,
    context_window   INTEGER,
    prompt_max       INTEGER,
    PRIMARY KEY (account, group_name, name)
);

-- Which model Trae had selected for a session, per agent label
-- (state.vscdb `<uid>:AI.agent.model.session_selected_model`). Partial by nature:
-- Trae keeps only the current selection per session, not the history, and only for
-- sessions that are still in that map.
CREATE TABLE IF NOT EXISTS session_models (
    session_id  TEXT,
    account     TEXT,
    agent_label TEXT,
    model_id    TEXT,
    mode        INTEGER,
    PRIMARY KEY (session_id, agent_label)
);

-- The agent's memory documents (project_memory.md, user_profile.md) split into
-- paragraphs. Prose; governed by `store_content`.
CREATE TABLE IF NOT EXISTS memory (
    scope TEXT,
    idx   INTEGER,
    text  TEXT,
    PRIMARY KEY (scope, idx)
);

-- Per-session turn ids from the snapshot git tags (`before/after-chat-turn-*`).
CREATE TABLE IF NOT EXISTS turns (
    session_id TEXT,
    turn_id    TEXT,
    ts         INTEGER,
    PRIMARY KEY (session_id, turn_id)
);

-- Per-session tool-call ids from the snapshot git tags
-- (`toolcall-<messageId>-<toolcallId>`). Ids only: Trae stores no tool name
-- anywhere readable, so this is a COUNT, not a name.
CREATE TABLE IF NOT EXISTS toolcall_events (
    session_id  TEXT,
    message_id  TEXT,
    toolcall_id TEXT,
    ts          INTEGER,
    PRIMARY KEY (session_id, message_id, toolcall_id)
);

-- What is installed / available, whatever its provenance.
CREATE TABLE IF NOT EXISTS inventory (
    kind         TEXT,            -- skill | plugin | mcp | model | agent
    name         TEXT,
    owner_plugin TEXT,
    version      TEXT,
    path         TEXT,
    source       TEXT,            -- builtin | user | plugin
    PRIMARY KEY (kind, name, owner_plugin)
);

-- One balance observation per row, read out of Trae's own renderer log
-- (`[ICubeUsageService] credits mutation refresh completed {…}`). `kind` is
-- `balance` (a `remaining` number was reported) or `skipped` (the fetch was
-- declined and no number exists). Only these fields are stored — never the log
-- line around them, which is Trae's prose, not ours.
-- A balance is a *level*, not consumption: Trae writes it roughly once per app
-- start, and credit grants push it up between observations. So the spend between
-- two rows is only bounded below (`q_credits` derives `spent_at_least`); it is
-- never stored as if it were measured.
CREATE TABLE IF NOT EXISTS credit_events (
    source     TEXT,
    ts         INTEGER,
    kind       TEXT,
    remaining  REAL,
    generation INTEGER,
    PRIMARY KEY (source, ts)
);

-- Per-source incremental cursor. `source` is a filesystem path or a logical
-- key (e.g. a state.vscdb path); `offset` is a byte offset for streamed files
-- and unused (0) for whole-file sources.
CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    size   INTEGER,
    mtime  REAL,
    offset INTEGER
);

-- Records the indexer saw but could not use: a summary file that is not JSON,
-- a topics line that does not match, a git object that will not inflate. The
-- count is what turns a Trae format change into something visible.
CREATE TABLE IF NOT EXISTS unparsed (
    reason TEXT PRIMARY KEY,       -- "session_memory:not_json" | "topic:no_match" | ...
    count  INTEGER NOT NULL DEFAULT 0
);
"""

# --- views -----------------------------------------------------------------
#
# Views are the export/back-compat path (``tcut export``). The ``q_*`` functions
# below aggregate the base tables directly so they can take an optional window
# (SQLite views cannot be parameterised).

VIEWS_SQL = """
DROP VIEW IF EXISTS v_sessions;
CREATE VIEW v_sessions AS
SELECT s.session_id,
       s.project,
       s.project_key,
       s.day,
       s.agent,
       s.intent,
       s.outcome,
       s.turns,
       s.toolcalls,
       s.first_ts,
       s.last_ts,
       (SELECT COUNT(*) FROM session_actions a WHERE a.session_id = s.session_id)
           AS actions,
       (SELECT COUNT(*) FROM session_learned l WHERE l.session_id = s.session_id)
           AS learned
FROM sessions s;

DROP VIEW IF EXISTS v_projects;
CREATE VIEW v_projects AS
SELECT project_key,
       MAX(project)                 AS project,
       COUNT(*)                     AS sessions,
       MIN(first_ts)                AS first_seen,
       MAX(last_ts)                 AS last_seen
FROM sessions
WHERE project_key IS NOT NULL
GROUP BY project_key;

DROP VIEW IF EXISTS v_agents;
CREATE VIEW v_agents AS
SELECT a.name AS agent,
       a.kind,
       (SELECT COUNT(*) FROM sessions s WHERE s.agent = a.name) AS sessions
FROM agents a;

DROP VIEW IF EXISTS v_inventory;
CREATE VIEW v_inventory AS
SELECT kind, name, owner_plugin, version, path, source FROM inventory;
"""

SCHEMA_SQL = TABLES_SQL + VIEWS_SQL


# --- helpers ---------------------------------------------------------------


def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def open_db(path: Path | str = DB_PATH, readonly: bool = False) -> sqlite3.Connection:
    """Open the tracker DB. Creates the file/schema unless ``readonly``."""
    path = Path(path)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        ensure_dir(path)
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


# --- snapshots -------------------------------------------------------------
#
# A migration or a ``--full`` rebuild deletes indexed state, and the only way
# back is re-reading Trae's data — which the host may rotate away at any time.
# So every destructive path takes a snapshot first.
#
# Managed snapshots live in their own ``backups/`` directory. Hand-made
# ``usage.db.bak-*`` files beside the database are listed as restore sources but
# never pruned: this code did not create them and does not get to delete them.

BACKUP_KEEP = 5
BACKUP_GLOB = "usage.db.bak-*"          # the shape a person makes by hand
BACKUP_PATTERN = "usage-*.db"           # the shape this module makes


def db_file(conn) -> Path | None:
    """The file behind an open connection (``None`` for an in-memory one)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2]) if row and row[2] else None


def backup_dir(db_path=None) -> Path:
    return Path(db_path or DB_PATH).parent / "backups"


def snapshot(conn, reason: str = "manual", db_path=None) -> Path:
    """Copy the live database aside using SQLite's online backup API.

    ``conn.backup`` rather than a file copy: with WAL on, the newest committed
    frames can still be sitting in ``-wal``, so a copied main file is a stale
    database — exactly the thing you need the snapshot to not be.
    """
    src = Path(db_path) if db_path else db_file(conn)
    dest_dir = backup_dir(src)
    dest_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    base = f"usage-{now:%Y%m%d-%H%M%S}"
    dest = dest_dir / f"{base}-{reason}.db"
    n = 1
    while dest.exists():            # never overwrite an earlier snapshot
        dest = dest_dir / f"{base}-{reason}-{n}.db"
        n += 1
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    prune_backups(src)
    return dest


def prune_backups(db_path=None, keep: int = BACKUP_KEEP) -> list[Path]:
    """Delete managed snapshots beyond the newest ``keep``.

    Only files matching :data:`BACKUP_PATTERN` inside the managed directory are
    eligible. Ordered by mtime, not by name: several snapshots can land in the
    same second, and the ``-1``/``-2`` suffixes that disambiguate them do not
    sort in creation order — trusting them would delete the newer file.
    """
    d = backup_dir(db_path)
    if not d.is_dir():
        return []
    newest_first = sorted(d.glob(BACKUP_PATTERN),
                          key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    stale = newest_first[keep:]
    for path in stale:
        path.unlink()
    return stale


def list_backups(db_path=None) -> list[Path]:
    """Everything worth restoring: managed snapshots plus hand-made copies."""
    src = Path(db_path or DB_PATH)
    out: list[Path] = []
    d = backup_dir(src)
    if d.is_dir():
        out += list(d.glob(BACKUP_PATTERN))
    if src.parent.is_dir():
        out += list(src.parent.glob(BACKUP_GLOB))
    return sorted(out, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def restore(backup_path, db_path=None, reason: str = "pre-restore") -> Path:
    """Replace the database with a snapshot, after snapshotting what is live.

    A wrong restore should be undoable, so the current database is copied first.
    The TUI must not be running: it holds the file open and would keep writing
    into the copy you are replacing.
    """
    src = Path(db_path or DB_PATH)
    backup_path = Path(backup_path)
    if not backup_path.is_file():
        raise FileNotFoundError(f"no such backup: {backup_path}")
    if src.exists():
        conn = sqlite3.connect(src)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            snapshot(conn, reason=reason, db_path=src)
        finally:
            conn.close()
    ensure_dir(src)
    source = sqlite3.connect(backup_path)
    target = sqlite3.connect(src)
    try:
        target.execute("PRAGMA busy_timeout = 5000")
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def stored_version(conn: sqlite3.Connection) -> int:
    """The schema version this database was last written at.

    ``0`` when there is no usable value — the right answer: it is as old as it
    can get, so every migration below runs against it.
    """
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _rebuild_models_per_account(conn: sqlite3.Connection) -> bool:
    """v1 keyed ``models`` on the name alone; Trae's catalog is not unique by name.

    Measured on a real footprint: 284 catalog entries collapse into 42 rows when the
    key is the name — 242 advertised models were simply not on disk in our index. v2
    keys on (account, group_name, name). The old rows are disposable: they are
    re-derived from Trae's own store, so this drops and recreates rather than copying
    rows into a key that would collide on the first duplicate name.

    Only the ``state.vscdb`` cursors are reset, so the one source that changed is
    re-read and everything already indexed stays where it is.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(models)")}
    if not cols or "account" in cols:
        return False
    conn.execute("DROP TABLE models")
    conn.executescript(SCHEMA_SQL)
    conn.execute("DELETE FROM sync_state WHERE source LIKE '%state.vscdb'")
    return True


MIGRATIONS: tuple = (
    ("models-per-account", _rebuild_models_per_account),
)


def _has_indexed_state(conn: sqlite3.Connection) -> bool:
    """Whether a snapshot would preserve anything at all.

    ``sync_state`` and ``sessions`` are exactly what an upgrade clears and
    rebuilds. A freshly created database has neither — and its ``meta`` table
    has no version row either, so it otherwise looks like a database from
    version 0. Without this test every first launch (and every test run) would
    write a snapshot of an empty database into ``backups/``.
    """
    for table in ("sync_state", "sessions", "turns", "toolcall_events"):
        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            return True
    return False


def ensure_schema(conn: sqlite3.Connection) -> str:
    """Create or upgrade the schema. Returns a status, never raises on drift.

    ``"newer"`` means the database was written by a future build of this tool and
    was deliberately left alone: ``CREATE TABLE IF NOT EXISTS`` is additive, but
    the migrations above clear ``sync_state`` and ``sessions`` and would destroy
    state this version of the code cannot interpret.
    """
    conn.executescript(SCHEMA_SQL)
    stored = stored_version(conn)
    if stored > SCHEMA_VERSION:
        conn.commit()
        return "newer"
    if stored < SCHEMA_VERSION and _has_indexed_state(conn):
        # One snapshot for the whole upgrade, taken before anything is modified
        # and after a commit. SQLite's backup API cannot read a source that is
        # holding its own uncommitted writes, so a per-step snapshot would
        # deadlock the moment a migration spans two steps.
        conn.commit()
        snapshot(conn, reason="pre-migration")
    changed = [name for name, step in MIGRATIONS if step(conn)]
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return "migrated" if changed else "current"


def migrate(db_path: Path | str = DB_PATH) -> str:
    """Best-effort upgrade of the tracker DB to the current schema.

    Returns a status rather than a boolean: ``"current"``, ``"migrated"``,
    ``"newer"`` (a database from a future build — not touched), or
    ``"failed: <sqlite message>"``.
    """
    try:
        conn = open_db(db_path)
        try:
            return ensure_schema(conn)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"failed: {exc}"


def reset(conn: sqlite3.Connection) -> None:
    """Drop all data (keeps the schema). Used by ``sync --full``."""
    for table in (
        "toolcall_events",
        "turns",
        "credit_events",
        "memory",
        "models",
        "session_models",
        "agents",
        "prompts",
        "workspaces",
        "topics",
        "session_learned",
        "session_actions",
        "sessions",
        "inventory",
        "sync_state",
        "unparsed",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def note_unparsed(conn: sqlite3.Connection, reason: str, n: int) -> None:
    """Add ``n`` to the count of records the indexer could not use.

    Called once per reason per file, not per record: a format change can make
    tens of thousands of records unknown in one run, and one statement each
    would cost more than the parsing it is reporting on.
    """
    conn.execute(
        "INSERT INTO unparsed(reason, count) VALUES(?,?)"
        " ON CONFLICT(reason) DO UPDATE SET count = count + excluded.count",
        (reason, n),
    )


def q_unparsed(conn: sqlite3.Connection):
    """Every reason records were skipped for, most frequent first."""
    return conn.execute(
        "SELECT reason, count FROM unparsed ORDER BY count DESC, reason").fetchall()


# --- shared queries (used by both the CLI and the TUI) ---------------------
#
# NOTE: the aggregate SQL below intentionally duplicates VIEWS_SQL. The views
# remain the export/back-compat path; these ``q_*`` functions aggregate the base
# tables directly so they can take an optional time window (SQLite views cannot
# be parameterized).


def _on_time(conds) -> tuple[str, list]:
    """``(" AND <pred> AND ...", params)`` for the LEFT JOIN's ON clause.

    The window lives in ON (never WHERE) so an out-of-window entity still
    yields a row with a zero count instead of dropping out of the list.
    """
    if not conds:
        return "", []
    return (" AND " + " AND ".join(c for c, _ in conds),
            [p for _, p in conds])


def q_sessions(conn, limit=None, start_ts=None, end_ts=None, project=None,
               agent=None, model_id=None):
    """Sessions in the window, most recent first.

    ``project``/``agent``/``model_id`` narrow the list to one entity — the drill-down
    from the Projects, Agents and Models tabs. They match the same expressions the
    tables render, so a row you clicked on is the row you get.

    The window is applied on ``last_ts`` (best-known activity time). Intent and
    outcome are prose and are returned as stored (NULL when ``store_content``
    is off). ``model_id`` is the session's ``agent`` selection where Trae recorded
    one, else its ``solo_agent`` selection, else NULL — Trae keeps only the current
    choice per session, never a history of switches.
    """
    conds = _time_conds(start_ts, end_ts, col="s.last_ts")
    if project is not None:
        conds.append(("COALESCE(s.project, s.project_key) = ?", project))
    if agent is not None:
        conds.append(("s.agent = ?", agent))
    if model_id is not None:
        conds.append((
            "(SELECT sm.model_id FROM session_models sm"
            "   WHERE sm.session_id = s.session_id"
            "   ORDER BY CASE sm.agent_label WHEN 'agent' THEN 0"
            "            WHEN 'solo_agent' THEN 1 ELSE 2 END, sm.agent_label"
            "   LIMIT 1) = ?", model_id))
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = (
        "SELECT s.session_id, s.project_key, s.project, s.day, s.agent,"
        " s.intent, s.outcome, s.turns, s.toolcalls, s.first_ts, s.last_ts,"
        " (SELECT sm.model_id FROM session_models sm"
        "   WHERE sm.session_id = s.session_id"
        "   ORDER BY CASE sm.agent_label WHEN 'agent' THEN 0"
        "            WHEN 'solo_agent' THEN 1 ELSE 2 END, sm.agent_label"
        "   LIMIT 1) AS model_id,"
        " (SELECT COUNT(*) FROM session_actions a WHERE a.session_id = s.session_id)"
        "   AS actions,"
        " (SELECT COUNT(*) FROM session_learned l WHERE l.session_id = s.session_id)"
        "   AS learned"
        f" FROM sessions s{where}"
        " ORDER BY s.last_ts DESC, s.session_id"
    )
    params = [p for _, p in conds]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def q_session(conn, session_id):
    """One session row (or ``None``)."""
    return conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()


def q_session_actions(conn, session_id):
    return conn.execute(
        "SELECT idx, text FROM session_actions WHERE session_id = ? ORDER BY idx",
        (session_id,)).fetchall()


def q_session_learned(conn, session_id):
    return conn.execute(
        "SELECT idx, text FROM session_learned WHERE session_id = ? ORDER BY idx",
        (session_id,)).fetchall()


def q_session_models(conn, session_id):
    """Every model selection recorded for one session, by agent label.

    A session can hold more than one (``agent`` and ``solo_agent`` are separate
    selections of the same session), so the list view collapses them and the detail
    view shows all of them. ``model_id`` is NULL only when Trae wrote no selection.
    """
    return conn.execute(
        "SELECT agent_label, model_id, mode, account FROM session_models"
        " WHERE session_id = ? ORDER BY agent_label", (session_id,)).fetchall()


def q_topics(conn, session_id):
    return conn.execute(
        "SELECT ts, summary FROM topics WHERE session_id = ? ORDER BY ts",
        (session_id,)).fetchall()


def q_projects(conn, limit=None, start_ts=None, end_ts=None):
    """Projects keyed by their on-disk directory name, with windowed counts.

    Sessions with no project key (snapshot-only or listed in the client's session
    list but never summarized) are excluded — they are not projects. The window
    lives in the aggregate so an out-of-window project still lists with a zero
    session count.
    """
    conds = _time_conds(start_ts, end_ts, col="last_ts")
    inner = (" CASE WHEN " + " AND ".join(c for c, _ in conds) + " THEN 1 ELSE 0 END"
             if conds else " 1")
    sql = (
        "SELECT project_key,"
        " MAX(project) AS project,"
        f" SUM({inner}) AS sessions,"
        " MAX(last_ts) AS last_seen,"
        " MIN(first_ts) AS first_seen"
        " FROM sessions WHERE project_key IS NOT NULL GROUP BY project_key"
        " ORDER BY sessions DESC, project_key"
    )
    params = [p for _, p in conds]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def q_prompts(conn, limit=None, workspace=None):
    """User prompts, grouped by workspace then position (all-time; no ts).

    ``workspace`` filters by workspace id; the ``folder`` column carries the
    real project path when ``workspace.json`` was available.
    """
    conds = []
    if workspace:
        conds.append(("p.workspace = ?", workspace))
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = ("SELECT p.workspace, w.folder, p.idx, p.text"
           " FROM prompts p LEFT JOIN workspaces w ON w.workspace = p.workspace"
           f"{where} ORDER BY w.folder, p.workspace, p.idx")
    params = [p for _, p in conds]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def q_agents(conn, limit=None, start_ts=None, end_ts=None):
    """Agents, most-sessions first, including installed-but-unused ones.

    ``sessions`` is windowed on the session's ``last_ts``. The window lives in
    the correlated subquery (never a WHERE on the outer query) so an agent with
    no sessions in the window still lists with a zero count rather than dropping
    out of the list.
    """
    conds = _time_conds(start_ts, end_ts, col="s.last_ts")
    and_clause, params = _on_time(conds)
    sql = (
        "SELECT a.name AS agent, a.kind,"
        f" (SELECT COUNT(*) FROM sessions s WHERE s.agent = a.name{and_clause})"
        "   AS sessions"
        " FROM agents a ORDER BY sessions DESC, a.name"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, params).fetchall()


def q_models(conn, limit=None):
    sql = ("SELECT account, group_name, name, display_name, provider, model_type,"
           " fee_level, consumption_rate, context_window, prompt_max"
           " FROM models ORDER BY account, group_name, name")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def q_credits(conn, limit=None, start_ts=None, end_ts=None):
    """Balance observations, newest first, with a bound on the spend between them.

    ``spent_at_least`` is ``previous - this`` when the balance fell, else 0. Credit
    grants push the balance *up* between observations, so a fall is only part of what
    was consumed — this is a lower bound, derived here rather than stored, so it can
    never be read as a number Trae wrote. Rows with no number (`kind='skipped'`) are
    not part of the series; ``q_credit_events`` returns them.
    """
    conds = _time_conds(start_ts, end_ts, col="ts")
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = (
        "SELECT ts, remaining, generation, source,"
        "   CASE WHEN prev IS NULL OR prev <= remaining THEN 0"
        "        ELSE prev - remaining END AS spent_at_least"
        "  FROM (SELECT ts, remaining, generation, source,"
        "               LAG(remaining) OVER (ORDER BY ts, source) AS prev"
        "          FROM credit_events WHERE kind = 'balance')"
        f" {where}"
        " ORDER BY ts DESC, source"
    )
    params = [p for _, p in conds]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def q_credit_events(conn, kind=None):
    """Every stored credit-log event, newest first, including the numberless ones."""
    sql = "SELECT ts, kind, remaining, generation, source FROM credit_events"
    params: tuple = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    sql += " ORDER BY ts DESC, source"
    return conn.execute(sql, params).fetchall()


def q_top_models(conn, limit=5, start_ts=None, end_ts=None):
    """Models ranked by how many sessions in the window had them selected.

    This is the honest shape of "top models" here: a session counts once for the
    model it was set to, because Trae records no per-request model and no tokens.
    """
    conds = _time_conds(start_ts, end_ts, col="s.last_ts")
    where = (" AND " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = (
        "SELECT sm.model_id, COUNT(DISTINCT sm.session_id) AS sessions"
        "  FROM session_models sm JOIN sessions s ON s.session_id = sm.session_id"
        f" WHERE 1=1{where}"
        " GROUP BY sm.model_id ORDER BY sessions DESC, sm.model_id LIMIT ?"
    )
    params = [p for _, p in conds] + [int(limit)]
    return conn.execute(sql, params).fetchall()


def q_inventory(conn, kind=None):
    sql = "SELECT * FROM inventory"
    params: tuple = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    sql += " ORDER BY owner_plugin, name"
    return conn.execute(sql, params).fetchall()


def q_memory(conn, limit=None):
    sql = "SELECT scope, idx, text FROM memory ORDER BY scope, idx"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql).fetchall()


def q_recent(conn, limit=30):
    """Recent sessions, newest first."""
    return conn.execute(
        "SELECT last_ts, session_id, project_key, agent, turns, toolcalls"
        " FROM sessions ORDER BY last_ts DESC, session_id LIMIT ?",
        (int(limit),),
    ).fetchall()


# --- usage statistics (calendar-day windows) -------------------------------

# Window sizes in CALENDAR days; None = All time (no lower bound). A window is
# whole local days ending *now*: "1d" starts at today's local 00:00, "2d" at
# yesterday's 00:00, and so on — never "now minus N hours".
USAGE_RANGES = {"1d": 1, "2d": 2, "3d": 3, "7d": 7, "14d": 14, "30d": 30,
                "all": None}
USAGE_RANGE_LABELS = {
    "1d": "Today", "2d": "2 days", "3d": "3 days",
    "7d": "7 days", "14d": "14 days", "30d": "30 days", "all": "All time",
}


class CustomWindow(NamedTuple):
    """An absolute window chosen in the date picker (as opposed to a preset).

    ``start_ms`` of ``None`` means no lower bound (all time). ``follow_now``
    keeps the end pinned to the current time on every refresh; otherwise the
    window is the fixed ``[start_ms, end_ms]`` span. Times are epoch
    milliseconds, the same unit as every other bound in this module.
    """

    start_ms: int | None
    end_ms: int | None
    follow_now: bool = False


def credit_num(value) -> str:
    """A credit number without float noise (`1645.9756`, not `1645.9756000000001`).

    Shared because the CLI and the TUI render the same series; two copies of a
    formatting rule is how they start disagreeing about what a balance looks like.
    """
    if value is None:
        return "-"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def credit_log_label(source: str, keep: int = 3) -> str:
    """The session directory and file a balance came from, not its absolute path."""
    parts = Path(source).parts[-keep:]
    return "/".join(str(p) for p in parts)


def count_n(value, singular, plural=None):
    """``1 tool call`` / ``12 tool calls`` — every count that reads as prose.

    D-005 in the sibling tracker fixed the plural in one place and left the rest, so
    "1 skills" and "Synced 1 files" shipped. One function is the only version of this
    rule that cannot drift; irregular plurals are passed explicitly (`fetch`/`fetches`)
    because appending "s" is a guess about English, not a measurement.
    """
    word = singular if value == 1 else (plural or singular + "s")
    return f"{value:,} {word}"


def _short_time(ms) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


def window_label(value) -> str:
    """A short label for a window value: a preset's name, or a custom span.

    A ``follow_now`` end reads as ``now`` rather than a timestamp, so the label
    does not go stale between refreshes. Kept free of a clock argument on
    purpose: the label depends only on what was chosen, never on the time it is
    read.
    """
    if not isinstance(value, CustomWindow):
        return USAGE_RANGE_LABELS.get(value, str(value))
    if value.start_ms is None:
        return "all → now" if value.follow_now else f"all → {_short_time(value.end_ms)}"
    start = _short_time(value.start_ms)
    if value.follow_now:
        return f"{start} → now"
    return f"{start} → {_short_time(value.end_ms)}"


# --- typed date / time entry (the date picker) ------------------------------
# The picker lets a date and a time be *typed* as well as clicked, so the two
# strings a person types are normalised before anything compares them: "10-01"
# and "10-1" are the same day, "9:5 AM" and "09:05 AM" the same minute.
DATE_DISPLAY_FMT = "%m/%d/%Y"
TIME_DISPLAY_FMT = "%H:%M"
# The date is split by hand rather than through a table of strptime formats:
# a yearless "%m-%d" parse is deprecated in 3.14 (the default year is ambiguous
# and leap day cannot resolve), so the missing year is filled in explicitly.
_DATE_SPLIT = re.compile(r"[-/.]")
_TIME_FORMATS = ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M", "%H:%M:%S")


def parse_date(text: str, default_year: int) -> datetime:
    """A typed date -> ``datetime`` at local midnight. Raises ``ValueError``.

    ``10-01``, ``10/1`` and ``10.01`` all mean the same day once ``default_year``
    fills in the missing year; a four-digit leading field is the year
    (``2026-10-01``). The month comes first in the ambiguous two-field form, and
    a two-digit trailing year uses the same 69/70 pivot as ``%y``.
    """
    s = (text or "").strip()
    fields = _DATE_SPLIT.split(s)
    if len(fields) == 2:
        year, (month, day) = str(default_year), fields
    elif len(fields) == 3:
        first, second, third = fields
        if len(first) == 4:                       # YYYY-MM-DD
            year, month, day = first, second, third
        else:                                     # MM-DD-YYYY / MM-DD-YY
            month, day, year = first, second, third
            if len(year) == 2:
                year = ("19" if int(year) >= 69 else "20") + year
    else:
        raise ValueError(f"unrecognised date: {text!r}")
    try:
        return datetime(int(year), int(month), int(day))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unrecognised date: {text!r}") from exc


def parse_time(text: str):
    """A typed time -> ``(hour, minute)`` in 24-hour form. Raises ``ValueError``.

    An am/pm marker makes it 12-hour ("9:5 PM" == "09:05 PM"); without one it is
    24-hour ("21:05"). ``12:00 AM`` is midnight, ``12:00 PM`` noon.
    """
    s = (text or "").strip()
    if not s:
        raise ValueError("empty time")
    for fmt in _TIME_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return dt.hour, dt.minute
    raise ValueError(f"unrecognised time: {text!r}")


def format_date(value: datetime) -> str:
    """A datetime's date as the picker displays it (``MM/DD/YYYY``)."""
    return value.strftime(DATE_DISPLAY_FMT)


def format_time(hour: int, minute: int) -> str:
    """``(hour, minute)`` as the picker shows it (24-hour, e.g. ``00:00``)."""
    return datetime(2000, 1, 1, hour, minute).strftime(TIME_DISPLAY_FMT)


def parse_datetime(date_text: str, time_text: str, default_year: int):
    """A typed ``(date, time)`` pair -> epoch ms, or ``None`` for a blank date.

    A blank time means midnight. Raises ``ValueError`` on a bad date or time, so
    the caller can tell "all time" (``None``) apart from "I mistyped" (an error).
    """
    if not (date_text or "").strip():
        return None
    day = parse_date(date_text, default_year)
    hour, minute = parse_time(time_text) if (time_text or "").strip() else (0, 0)
    return int(day.replace(hour=hour, minute=minute).timestamp() * 1000)


def window_bounds(range_key: str, now_ms: int):
    """``(start_ms, end_ms)`` for a whole-calendar-day window ending at ``now_ms``.

    The window is a whole number of **local** calendar days: ``"1d"`` runs from
    today's local 00:00 to ``now_ms``, ``"2d"`` from yesterday's 00:00, and so
    on. It never uses "now minus N hours", so the bounds are stable through the
    day and match what a person means by "today" / "the last 2 days".

    ``start_ms`` is ``None`` for ``"all"`` (no lower bound).
    """
    days = USAGE_RANGES[range_key]
    end = int(now_ms)
    if days is None:
        return None, end
    midnight = datetime.fromtimestamp(end / 1000).replace(
        hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=days - 1)
    return int(start.timestamp() * 1000), end


def _ts_where(start_ts, end_ts):
    if start_ts is None:
        return "ts < ?", [end_ts]
    return "ts >= ? AND ts < ?", [start_ts, end_ts]


def _time_conds(start_ts, end_ts, col="ts"):
    """时间谓词列表 ``(sql, param)``；两者皆 None 时为空（= 全部时间）。"""
    conds = []
    if start_ts is not None:
        conds.append((f"{col} >= ?", start_ts))
    if end_ts is not None:
        conds.append((f"{col} < ?", end_ts))
    return conds


def _time_filter(start_ts, end_ts, col="ts"):
    """返回 ``(where_prefix, params)``；无过滤时为 ``("", [])``。"""
    conds = _time_conds(start_ts, end_ts, col)
    if not conds:
        return "", []
    return " WHERE " + " AND ".join(c for c, _ in conds), [p for _, p in conds]


def q_kpi(conn, start_ts=None, end_ts=None) -> dict:
    """Windowed counts for the Dashboard (the status-bar numbers, windowed).

    ``sessions``/``projects`` are windowed on ``sessions.last_ts``; ``prompts``
    and the inventory counts have no timestamp of their own, so they are
    all-time. Both bounds ``None`` is all-time.
    """
    where, params = _time_filter(start_ts, end_ts, col="last_ts")

    # ``p`` is passed explicitly: the windowed queries take the window params,
    # the all-time ones take none. Defaulting to ``params`` handed the window's
    # bindings to a statement with no placeholders ("0 used, 2 supplied").
    def one(sql, p=()):
        return conn.execute(sql, p).fetchone()[0]

    return {
        "sessions": one(f"SELECT COUNT(*) FROM sessions{where}", params),
        "projects": one(
            f"SELECT COUNT(DISTINCT project_key) FROM sessions{where}", params),
        "turns": one(f"SELECT COALESCE(SUM(turns),0) FROM sessions{where}", params),
        "toolcalls": one(
            f"SELECT COALESCE(SUM(toolcalls),0) FROM sessions{where}", params),
        "prompts": one("SELECT COUNT(*) FROM prompts"),
        "agents": one("SELECT COUNT(DISTINCT name) FROM agents"),
        "skills": one("SELECT COUNT(*) FROM inventory WHERE kind='skill'"),
        "plugins": one("SELECT COUNT(*) FROM inventory WHERE kind='plugin'"),
        "mcp": one("SELECT COUNT(*) FROM inventory WHERE kind='mcp'"),
    }


def q_activity_daily(conn, start_ts=None, end_ts=None):
    """Session counts per LOCAL calendar day in the window, oldest first.

    Rows are ``{"day": "YYYY-MM-DD", "sessions": n}`` for days that have
    activity. The day is bucketed in local time (``localtime``) so it lines up
    with the local-day windows; the Dashboard draws the series as a sparkline.
    Days with no activity are simply absent — the caller fills the gaps.
    """
    where, params = _time_filter(start_ts, end_ts, col="last_ts")
    return conn.execute(
        "SELECT strftime('%Y-%m-%d', last_ts / 1000, 'unixepoch', 'localtime')"
        "   AS day,"
        " COUNT(*) AS sessions"
        f" FROM sessions{where}"
        " GROUP BY day ORDER BY day",
        params,
    ).fetchall()


def q_top_projects(conn, limit=5, start_ts=None, end_ts=None):
    """The Dashboard's Top projects list: windowed session counts."""
    return q_projects(conn, limit=limit, start_ts=start_ts, end_ts=end_ts)


def q_top_agents(conn, limit=5, start_ts=None, end_ts=None):
    return q_agents(conn, limit=limit, start_ts=start_ts, end_ts=end_ts)


def overview(conn) -> dict:
    def one(sql, *p):
        return conn.execute(sql, p).fetchone()[0]

    return {
        "sessions": one("SELECT COUNT(*) FROM sessions"),
        "projects": one("SELECT COUNT(DISTINCT project_key) FROM sessions"),
        "turns": one("SELECT COALESCE(SUM(turns),0) FROM sessions"),
        "toolcalls": one("SELECT COALESCE(SUM(toolcalls),0) FROM sessions"),
        "prompts": one("SELECT COUNT(*) FROM prompts"),
        "agents": one("SELECT COUNT(*) FROM agents"),
        "models": one("SELECT COUNT(*) FROM models"),
        "credits": one("SELECT COUNT(*) FROM credit_events WHERE kind='balance'"),
        "skills": one("SELECT COUNT(*) FROM inventory WHERE kind='skill'"),
        "plugins": one("SELECT COUNT(*) FROM inventory WHERE kind='plugin'"),
        "mcp": one("SELECT COUNT(*) FROM inventory WHERE kind='mcp'"),
        "memory_docs": one("SELECT COUNT(DISTINCT scope) FROM memory"),
        "first_ts": one("SELECT MIN(last_ts) FROM sessions"),
        "last_ts": one("SELECT MAX(last_ts) FROM sessions"),
        "inventory": one("SELECT COUNT(*) FROM inventory"),
        # Records no handler claimed. Non-zero after a Trae update means the
        # format moved under us, not that you stopped using it.
        "unparsed_records": one("SELECT COALESCE(SUM(count),0) FROM unparsed"),
        "unparsed_kinds": one("SELECT COUNT(*) FROM unparsed"),
    }
