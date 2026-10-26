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

SCHEMA_VERSION = 6

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
    "log_limit": 100,      # rows on the Usage page's session log and on `tcut prompts`
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
    first_ts   INTEGER,          -- epoch ms, measured: snapshot tag times only
    last_ts    INTEGER,          -- the memory folder's day is `day`, not this
    created_ts INTEGER           -- epoch ms *derived* from the session id, never
                                 -- written into first_ts/last_ts; see time_text
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
    source     TEXT,             -- the topics.md the line was read from
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
--
-- `model_id` is kept verbatim — it is what Trae wrote, and the decode below is a
-- reading of it, not a replacement. `model`/`provider` are that reading: the
-- catalog name the id embeds and the catalog's provider for it (empty = Trae's own
-- route, otherwise a third-party channel such as `volcengine-plan`).
CREATE TABLE IF NOT EXISTS session_models (
    session_id  TEXT,
    account     TEXT,
    agent_label TEXT,
    model_id    TEXT,
    mode        INTEGER,
    model       TEXT,            -- decoded catalog name; NULL when the id names none
    provider    TEXT,            -- catalog provider; '' for a built-in route
    third_party INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, agent_label)
);
-- The index on `model` is created by the v5 migration, not here: on a database from
-- v4 the column does not exist yet, and `executescript` runs before the migration
-- gets its turn.

-- Every interval between two balance observations, and what the measured drop in
-- that interval was spent on. `drop_amount` is the *only* measured quantity here:
-- `remaining` fell by this much between the two samples, and nothing in Trae's
-- plaintext says which call spent it. A negative `drop_amount` is a grant (the balance
-- rose), recorded as such and never allocated.
CREATE TABLE IF NOT EXISTS credit_intervals (
    start_ts   INTEGER PRIMARY KEY,   -- the earlier balance observation
    end_ts     INTEGER,               -- the later one
    drop_amount REAL,                 -- remaining(start) - remaining(end)
    weight     REAL,                  -- total turns available to split the drop over
    sessions   INTEGER,               -- sessions created inside the interval
    allocated  REAL                   -- sum of the shares below; equals drop_amount when > 0
);

-- One row per (session, model selection) inside an interval: that selection's share
-- of the interval's measured drop, split by its sessions' turn counts. This is an
-- **estimate** and every surface that prints it says so — the parts always add up
-- to `credit_intervals.allocated`, so no credit is invented, but which model spent
-- a given credit is Trae's silence, not our measurement.
CREATE TABLE IF NOT EXISTS credit_alloc (
    session_id  TEXT,
    agent_label TEXT,
    model_id    TEXT,
    start_ts    INTEGER,              -- the interval this share belongs to
    credits     REAL,
    PRIMARY KEY (session_id, agent_label, start_ts)
);
CREATE INDEX IF NOT EXISTS idx_credit_alloc_ts ON credit_alloc(start_ts);

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
--
-- Keyed by (reason, source) because the count is replaced per source, not added
-- per run: a whole-file source is re-read whenever it changes, and a bare
-- running total reported one bad line three times after three edits.
CREATE TABLE IF NOT EXISTS unparsed (
    reason TEXT NOT NULL,          -- "session_memory:not_json" | "topic:no_match" | ...
    source TEXT NOT NULL DEFAULT '',  -- the file it came from; '' when it has none
    count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (reason, source)
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


def meta_get(conn: sqlite3.Connection, key: str, default=None):
    """One ``meta`` value, or ``default`` when the key was never written."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Write one ``meta`` value. Values are text; a caller compares strings."""
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?,?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value))


def stored_version(conn: sqlite3.Connection) -> int:
    """The schema version this database was last written at.

    ``0`` when there is no usable value — the right answer: it is as old as it
    can get, so every migration below runs against it.
    """
    try:
        return int(meta_get(conn, "schema_version"))
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


def stamp_created_ts(conn) -> int:
    """Fill ``sessions.created_ts`` from the session id's leading 4 hex bytes.

    Measured here: that prefix is the creation second — against every session that
    also has a tagged snapshot commit, the delta was 0.0 s in the median and 144 s at
    worst. It lands in its **own** column because it is a creation time, not a
    last-activity measurement; 25 of this machine's 49 sessions have no timestamp
    anywhere in Trae's plaintext, and a range that cannot place them simply hides them.

    An id whose prefix is not a plausible unix second is left unstamped rather than
    guessed at.
    """
    created = 0
    for (sid,) in conn.execute(
            "SELECT session_id FROM sessions WHERE created_ts IS NULL").fetchall():
        try:
            secs = int(sid[:8], 16)
        except ValueError:
            continue
        if not _CREATED_SEC_MIN < secs < _CREATED_SEC_MAX:
            continue
        conn.execute("UPDATE sessions SET created_ts = ? WHERE session_id = ?",
                     (secs * 1000, sid))
        created += 1
    return created


# A plausible unix second: 2020-09 through 2096. Outside it the id is not a timestamp.
_CREATED_SEC_MIN = 1_600_000_000
_CREATED_SEC_MAX = 4_000_000_000


def _add_created_ts(conn) -> bool:
    """v3 had nowhere to put a derived time, so undated sessions were invisible to
    every range including All time. Adds the column and backfills it in place; no row
    is rewritten and nothing is dropped, so an old database keeps its measured values.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    if not cols or "created_ts" in cols:
        return False
    conn.execute("ALTER TABLE sessions ADD COLUMN created_ts INTEGER")
    stamp_created_ts(conn)
    return True


def _add_session_model_decode(conn) -> bool:
    """v5: a selection carries what its id *means*, not just the id.

    The two new columns are additive and the two estimate tables are created by
    ``SCHEMA_SQL``; nothing is dropped, so an old database keeps every row and the
    decode backfills from the catalog it already holds. A rebuild is not needed
    because ``decode_session_models`` is idempotent and runs at the end of every sync
    — this step only has to make room.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(session_models)")}
    if not cols or "third_party" in cols:
        return False
    conn.execute("ALTER TABLE session_models ADD COLUMN model TEXT")
    conn.execute("ALTER TABLE session_models ADD COLUMN provider TEXT")
    conn.execute(
        "ALTER TABLE session_models ADD COLUMN third_party INTEGER DEFAULT 0")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_models_model"
        " ON session_models(model)")
    return True


def _add_unparsed_source(conn: sqlite3.Connection) -> bool:
    """v6: ``unparsed`` counts per (reason, source).

    A count keyed by the reason alone could only be added to, so re-reading a
    file that had not changed reported its bad lines again and the number grew
    with the number of syncs. The table is rebuilt rather than altered: the key
    is the change, and SQLite cannot add a column to a primary key. Existing
    counts are kept under an empty source, which is what a row written before
    this version honestly is — "this file was not recorded".
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(unparsed)")}
    if not cols or "source" in cols:
        return False
    conn.execute("ALTER TABLE unparsed RENAME TO unparsed_old")
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO unparsed(reason, source, count)"
                 " SELECT reason, '', count FROM unparsed_old")
    conn.execute("DROP TABLE unparsed_old")
    return True


def _add_topic_source(conn: sqlite3.Connection) -> bool:
    """v6: ``topics`` remembers which ``topics.md`` a line came from.

    The table is a snapshot of a file that is re-read whole when it changes, so
    re-reading has to replace that file's rows. Without the provenance the only
    key available is (session, time), and a line deleted from the file could not
    be told from one that was never there.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(topics)")}
    if not cols or "source" in cols:
        return False
    conn.execute("ALTER TABLE topics ADD COLUMN source TEXT")
    return True


MIGRATIONS: tuple = (
    ("models-per-account", _rebuild_models_per_account),
    ("sessions-created-ts", _add_created_ts),
    ("session-model-decode", _add_session_model_decode),
    ("unparsed-per-source", _add_unparsed_source),
    ("topic-source", _add_topic_source),
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
        "credit_alloc",
        "credit_intervals",
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


def note_unparsed(conn: sqlite3.Connection, reason: str, n: int,
                  source: str = "") -> None:
    """Add ``n`` to the count of records the indexer could not use.

    ``source`` is the file the records came from. A whole-file source is re-read
    whenever it changes, so its handler calls :func:`forget_unparsed` first and
    the count describes the file as it is now — otherwise one bad line was
    reported once per edit and the number grew without the file changing.
    """
    conn.execute(
        "INSERT INTO unparsed(reason, source, count) VALUES(?,?,?)"
        " ON CONFLICT(reason, source) DO UPDATE SET count = count + excluded.count",
        (reason, source, n),
    )


def forget_unparsed(conn: sqlite3.Connection, source: str, *prefixes: str) -> None:
    """Drop one source's previous counts, before that source is re-read."""
    for prefix in prefixes:
        conn.execute(
            "DELETE FROM unparsed WHERE source = ? AND reason LIKE ?",
            (source, prefix + "%"),
        )


def q_unparsed(conn: sqlite3.Connection):
    """Every reason records were skipped for, most frequent first.

    Summed over sources: the caller asks what the index cannot read, not which
    file each record came from.
    """
    return conn.execute(
        "SELECT reason, SUM(count) AS count FROM unparsed"
        " GROUP BY reason ORDER BY count DESC, reason").fetchall()


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


# The instant a session is placed at: Trae's measured activity time when there is
# one, else the creation second derived from the id. Those are the only two sources:
# `last_ts` is written from a snapshot tag's commit time and nothing else — the
# memory folder's day is a date, not a clock, and lives in `sessions.day`. Reads are
# paired with `derived_ts` so a derived position can never be printed as if it were
# measured.
SESSION_TIME = "COALESCE(last_ts, created_ts)"
SESSION_TIME_S = "COALESCE(s.last_ts, s.created_ts)"
# Rows no window can place at all: neither a measured time nor a derivable id. Every
# count that can be windowed carries one of these alongside it, because "0 in this
# range" and "nothing here has a time" print identically and mean opposite things.
UNDATED = "last_ts IS NULL AND created_ts IS NULL"
UNDATED_S = "s.last_ts IS NULL AND s.created_ts IS NULL"
# Rows that carry no *measured* time, whether or not the id places them. This is the
# population the `~` marker belongs to, so the disclosure and the marker count the same
# set — an all-time number, since a measurement does not become one by changing range.
UNMEASURED = "last_ts IS NULL"


def _cond_params(conds):
    """Flatten a predicate list's parameters.

    Most predicates carry one scalar, but the decoded-model EXISTS carries the
    model and (optionally) the provider. Returning one flat list keeps every
    caller on the same `?` order the SQL was built in, instead of a nested tuple
    that sqlite refuses to bind.
    """
    out = []
    for _, value in conds:
        if isinstance(value, (tuple, list)):
            out.extend(value)
        else:
            out.append(value)
    return out


def _entity_conds(start_ts, end_ts, project, agent, model_id,
                  model=None, provider=None):
    """The one predicate list the session list and its header totals are built from.

    Both `q_sessions` and `q_entity_totals` read this, so a header cannot count a
    different set of rows than the table underneath it lists — the failure this repo
    has already met twice with two numbers on one screen.

    ``model``/``provider`` narrow on the *decoded* selection (the Tokens tab's key),
    while ``model_id`` keeps the raw-id behaviour the older screens use. A session
    can hold several selections, so the decoded filter is an EXISTS: a session that
    used this route through any agent label belongs in the list, and the totals count
    it once.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
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
    if model is not None:
        sql = ("EXISTS (SELECT 1 FROM session_models sm"
               " WHERE sm.session_id = s.session_id AND sm.model = ?")
        params = [model]
        if provider is not None:
            sql += " AND COALESCE(sm.provider, '') = ?"
            params.append(provider)
        conds.append((sql + ")", tuple(params)))
    return conds


def q_entity_totals(conn, start_ts=None, end_ts=None, project=None, agent=None,
                    model_id=None, model=None, provider=None):
    """Windowed totals for one entity — the line its drill-down header prints.

    ``sessions``/``turns``/``toolcalls``/``projects`` aggregate exactly the rows
    ``q_sessions`` would list for the same arguments. ``first_ts``/``last_ts`` are that
    set's span on ``COALESCE(last_ts, created_ts)`` and stay NULL over an empty set — an
    empty span is neither the epoch nor a zero.

    ``projects_missing`` counts the rows with neither a decoded project nor a raw key — on
    this footprint that is 28 of 49 sessions, so an entity can genuinely have a session set
    with no project to count, and a 0 there would claim a measurement. Read the pair with
    ``window_count``. ``turns``/``toolcalls`` need no such pair because the writer never
    leaves them NULL (measured: 0 NULL in 49 rows); they are stored counts, including the
    stored zeros.

    ``first_measured``/``last_measured`` aggregate only the rows with a *measured* time,
    which is what lets the caller tell whether an endpoint is the derived one: if the
    span's edge differs from its measured edge, the position came from a session id and
    the header has to mark it.
    """
    conds = _entity_conds(start_ts, end_ts, project, agent, model_id,
                          model=model, provider=provider)
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    return conn.execute(
        "SELECT COUNT(*) AS sessions,"
        " COALESCE(SUM(s.turns), 0) AS turns,"
        " COALESCE(SUM(s.toolcalls), 0) AS toolcalls,"
        " COUNT(DISTINCT COALESCE(s.project, s.project_key)) AS projects,"
        " SUM(CASE WHEN COALESCE(s.project, s.project_key) IS NULL"
        "          THEN 1 ELSE 0 END) AS projects_missing,"
        f" MIN({SESSION_TIME_S}) AS first_ts,"
        f" MAX({SESSION_TIME_S}) AS last_ts,"
        " MIN(CASE WHEN s.last_ts IS NOT NULL THEN " + SESSION_TIME_S + " END)"
        "   AS first_measured,"
        " MAX(CASE WHEN s.last_ts IS NOT NULL THEN " + SESSION_TIME_S + " END)"
        "   AS last_measured"
        f" FROM sessions s{where}",
        _cond_params(conds)).fetchone()


def q_sessions(conn, limit=None, start_ts=None, end_ts=None, project=None,
               agent=None, model_id=None, model=None, provider=None):
    """Sessions in the window, most recent first.

    ``project``/``agent``/``model_id`` narrow the list to one entity — the drill-down
    from the Projects, Agents and Models tabs. They match the same expressions the
    tables render, so a row you clicked on is the row you get.

    The window is applied on ``COALESCE(last_ts, created_ts)`` — measured activity when
    Trae recorded one, else the creation second derived from the id — and every row
    carries ``derived_ts`` so a caller can mark the second kind instead of passing it
    off as a measurement. Intent and
    outcome are prose and are returned as stored (NULL when ``store_content``
    is off). ``model_id`` is the session's ``agent`` selection where Trae recorded
    one, else its ``solo_agent`` selection, else NULL — Trae keeps only the current
    choice per session, never a history of switches.
    """
    conds = _entity_conds(start_ts, end_ts, project, agent, model_id,
                          model=model, provider=provider)
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = (
        "SELECT s.session_id, s.project_key, s.project, s.day, s.agent,"
        " s.intent, s.outcome, s.turns, s.toolcalls, s.first_ts, s.last_ts,"
        " s.created_ts,"
        f" {SESSION_TIME_S} AS shown_ts,"
        " CASE WHEN s.last_ts IS NULL THEN 1 ELSE 0 END AS derived_ts,"
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
        f" ORDER BY {SESSION_TIME_S} DESC, s.session_id"
    )
    params = _cond_params(conds)
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


def q_session_credits(conn, session_id):
    """The credit estimate attributed to each of a session's selections.

    A session can receive a share in several balance intervals; they are summed
    per (agent label, raw model id), which is the key ``q_session_models`` uses.
    A selection with no share has no row — callers read that as ``-``.
    """
    return conn.execute(
        "SELECT agent_label, model_id, SUM(credits) AS credits"
        "  FROM credit_alloc WHERE session_id = ?"
        " GROUP BY agent_label, model_id", (session_id,)).fetchall()


def q_session_models(conn, session_id):
    """Every model selection recorded for one session, by agent label.

    A session can hold more than one (``agent`` and ``solo_agent`` are separate
    selections of the same session), so the list view collapses them and the detail
    view shows all of them. ``model_id`` is NULL only when Trae wrote no selection.
    """
    return conn.execute(
        "SELECT agent_label, model_id, model, provider, third_party, mode, account"
        "  FROM session_models"
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

    ``undated`` is that project's share of the rows no window can place at all. It is
    deliberately not windowed — it is what tells a real zero apart from this range's
    blind spot, so read the pair with ``window_count``. It breaks the count tie in the
    ordering: on a capped leaderboard a hidden project outranks a provably idle one.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME)
    inner = (" CASE WHEN " + " AND ".join(c for c, _ in conds) + " THEN 1 ELSE 0 END"
             if conds else " 1")
    sql = (
        "SELECT project_key,"
        " MAX(project) AS project,"
        f" SUM({inner}) AS sessions,"
        f" SUM(CASE WHEN {UNDATED} THEN 1 ELSE 0 END) AS undated,"
        f" MAX({SESSION_TIME}) AS last_seen,"
        f" MIN({SESSION_TIME}) AS first_seen"
        " FROM sessions WHERE project_key IS NOT NULL GROUP BY project_key"
        " ORDER BY sessions DESC, undated DESC, project_key"
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

    ``undated`` counts that agent's sessions with **neither** a measured ``last_ts``
    nor a derived ``created_ts`` — the rows no window can place at all. Render the pair
    with ``window_count``: with no window the two can never disagree (every undated row
    is counted), so a ``-`` only ever means "this range cannot tell". It breaks the
    count tie in the ordering, so a capped list shows a hidden agent before an
    agent whose dated sessions are simply elsewhere.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    and_clause, params = _on_time(conds)
    sql = (
        "SELECT a.name AS agent, a.kind,"
        f" (SELECT COUNT(*) FROM sessions s WHERE s.agent = a.name{and_clause})"
        "   AS sessions,"
        f" (SELECT COUNT(*) FROM sessions s"
        f"   WHERE s.agent = a.name AND {UNDATED_S}) AS undated"
        " FROM agents a ORDER BY sessions DESC, undated DESC, a.name"
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


def _credit_by_model(conn, start_ts=None, end_ts=None) -> dict:
    """``{(model, provider): credits}`` from the estimate, windowed on the interval.

    Keyed by the interval's own start, because a credit was spent when the balance
    fell -- not when the session that spent it was created. A session can span an
    interval boundary, and attributing the drop to the session's creation day would
    move spend into a window it did not happen in.
    """
    conds = _time_conds(start_ts, end_ts, col="ca.start_ts")
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    out = {}
    for r in conn.execute(
            "SELECT sm.model AS model, sm.provider AS provider,"
            "       SUM(ca.credits) AS credits"
            "  FROM credit_alloc ca"
            "  JOIN session_models sm ON sm.session_id = ca.session_id"
            "       AND sm.agent_label = ca.agent_label"
            "       AND sm.model_id = ca.model_id"
            + where +
            " GROUP BY sm.model, sm.provider",
            [p for _, p in conds]):
        out[(r["model"], r["provider"])] = r["credits"] or 0.0
    return out


def q_model_credits(conn, start_ts=None, end_ts=None):
    """Per-model rows for the Tokens tab: sessions, estimated credits, share.

    The union of two populations, keyed by (decoded model, provider) and never
    windowed away -- the same rule every other entity tab follows:

    * every model a session **selected** inside the window (``sessions``), the only
      per-model usage fact Trae records;
    * every model the credit estimate put spend on inside the window (``credits``).

    ``credits`` is an estimate by construction: a share of a measured balance drop,
    split by session turns (see ``allocate_credits``). Every surface prints the
    header as ``est.`` and none shows it as a measured per-call cost.

    ``coverage`` is the row's share of the window's allocated estimate -- the column
    answers "where does the estimate think the credits went", and ``None`` (``-``)
    when nothing was allocated, never a fabricated 0%.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    and_clause, params = _on_time(conds)
    used = conn.execute(
        "SELECT sm.model AS model, sm.provider AS provider,"
        "       MAX(sm.third_party) AS third_party,"
        "       COUNT(DISTINCT sm.session_id) AS sessions,"
        "       MAX(" + SESSION_TIME_S + ") AS last_used,"
        "       MAX(CASE WHEN s.last_ts IS NULL THEN 1 ELSE 0 END) AS derived_ts"
        "  FROM session_models sm JOIN sessions s ON s.session_id = sm.session_id"
        " WHERE 1=1" + and_clause +
        " GROUP BY sm.model, sm.provider", params).fetchall()
    credits = _credit_by_model(conn, start_ts, end_ts)
    rows = {}
    for r in used:
        rows[(r["model"], r["provider"])] = {
            "model": r["model"], "provider": r["provider"],
            "third_party": r["third_party"] or 0,
            "sessions": r["sessions"] or 0,
            "last_used": r["last_used"],
            "derived_ts": r["derived_ts"] or 0,
            "credits": credits.pop((r["model"], r["provider"]), None),
        }
    # A model the estimate charged but no selection in this window names: the spend
    # happened here while the selection was recorded in an earlier window. It gets a
    # row with 0 sessions rather than being dropped -- dropping it would make the
    # estimate's own total disagree with the sum of the rows below it.
    for (model, provider), value in credits.items():
        rows[(model, provider)] = {
            "model": model, "provider": provider,
            "third_party": 1 if provider else 0,
            "sessions": 0, "last_used": None, "derived_ts": 0,
            "credits": value,
        }
    total = sum((r["credits"] or 0) for r in rows.values())
    out = []
    for r in rows.values():
        r["coverage"] = (r["credits"] / total) if total and r["credits"] else None
        out.append(r)
    # Where the estimate thinks the credits went comes first: this is the Tokens
    # page, not a session leaderboard. Sessions and the name break ties, so the
    # order is stable across refreshes.
    out.sort(key=lambda r: (-(r["credits"] or 0), -(r["sessions"] or 0),
                            r["model"] or ""))
    return out


def q_usage_rows(conn, limit=None, start_ts=None, end_ts=None):
    """The Usage page: one row per (session, model selection) in the window.

    cbut's Usage page is a per-request ledger; Trae records no per-request line, so
    the finest subject available is a session *and* the model it was set to. A
    session that switched models yields one row per model, which is what puts a
    third-party route in the log as a visible row instead of hiding it in a merged
    cell. A session with no recorded selection still gets one row, model cells empty:
    the session happened either way.

    ``credits`` is this selection's share of the estimate; it is NULL for a session no
    interval covers, which is a different fact from a measured zero and prints ``-``.

    ``turns``/``toolcalls`` belong to the session and are therefore repeated across its
    rows rather than divided: a per-model number would be a second estimate stacked
    on the first.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = (
        "SELECT s.session_id, s.project_key, s.project, s.agent AS session_agent,"
        "       s.turns, s.toolcalls,"
        "       " + SESSION_TIME_S + " AS shown_ts,"
        "       CASE WHEN s.last_ts IS NULL THEN 1 ELSE 0 END AS derived_ts,"
        "       sm.agent_label, sm.model, sm.provider, sm.model_id,"
        "       COALESCE(sm.third_party, 0) AS third_party,"
        "       ca.credits AS credits"
        "  FROM sessions s"
        "  LEFT JOIN session_models sm ON sm.session_id = s.session_id"
        # One session can receive a share in several balance intervals. The
        # estimate is per (session, selection) in total, so sum those shares here;
        # joining the table directly repeated the row once per interval and made
        # the Usage page list the same selection twice.
        "  LEFT JOIN (SELECT session_id, agent_label, model_id, SUM(credits) AS credits"
        "               FROM credit_alloc GROUP BY session_id, agent_label, model_id)"
        "       ca ON ca.session_id = sm.session_id"
        "       AND ca.agent_label = sm.agent_label"
        "       AND ca.model_id = sm.model_id"
        + where +
        " ORDER BY " + SESSION_TIME_S + " DESC, s.session_id, sm.agent_label"
    )
    params = [p for _, p in conds]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def q_model_sessions(conn, model, provider=None, start_ts=None, end_ts=None,
                     limit=None):
    """Sessions that used one decoded model route, with that route's estimate.

    One row per session. A session can hold two selections of the same route
    (``agent`` and ``solo_agent``), so the credits are summed here instead of
    repeating the session once per slot. The route is matched with ``EXISTS`` on
    the decoded pair, the same predicate ``q_entity_totals`` uses; ``provider``
    of ``None`` means "any provider for this model", never a wildcard for NULL.

    ``credits`` is NULL when no balance interval covers the session — an absence
    of estimate, not a measured zero.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    where = (" WHERE " + " AND ".join(c for c, _ in conds)) if conds else ""
    params = [model]
    sql = ("SELECT s.session_id, s.project_key, s.project, s.agent,"
           "       s.turns, s.toolcalls, s.intent, s.outcome,"
           f"       {SESSION_TIME_S} AS shown_ts,"
           "       CASE WHEN s.last_ts IS NULL THEN 1 ELSE 0 END AS derived_ts,"
           "       SUM(ca.credits) AS credits"
           "  FROM sessions s"
           "  JOIN session_models sm ON sm.session_id = s.session_id"
           "       AND sm.model = ?")
    if provider is not None:
        sql += " AND COALESCE(sm.provider, '') = ?"
        params.append(provider)
    sql += ("  LEFT JOIN credit_alloc ca ON ca.session_id = sm.session_id"
            "       AND ca.agent_label = sm.agent_label"
            "       AND ca.model_id = sm.model_id")
    sql += where + " GROUP BY s.session_id"
    sql += f" ORDER BY {SESSION_TIME_S} DESC, s.session_id"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    params += [p for _, p in conds]
    return conn.execute(sql, params).fetchall()


def q_third_party_sessions(conn, start_ts=None, end_ts=None):
    """Sessions that selected a third-party route, in the window.

    Trae records no per-request traffic, so this counts sessions, not calls. It is the
    honest size of "how much of my work went through a non-built-in channel", and the
    model list behind it is the Tokens tab.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    and_clause, params = _on_time(conds)
    return conn.execute(
        "SELECT COUNT(DISTINCT sm.session_id) AS sessions,"
        "       COUNT(DISTINCT sm.model) AS models"
        "  FROM session_models sm JOIN sessions s ON s.session_id = sm.session_id"
        " WHERE sm.third_party = 1" + and_clause, params).fetchone()


def q_credit_summary(conn, start_ts=None, end_ts=None) -> dict:
    """The window's credit picture: measured balance, estimated spend, coverage.

    ``balance`` is the newest measured balance *inside* the window -- a level Trae
    wrote, not a sum -- and ``None`` when the window holds no sample (a real absence,
    not zero credits). ``spent`` is the measured drop inside the window and
    ``allocated`` the part of it the estimate could place on a model;
    ``unallocated`` is the remainder: sessions with no recorded selection, which no
    honest split can charge to a model.

    ``grants`` counts intervals where the balance rose. A grant is not negative spend
    and is never netted into one, or a top-up would read as a refund of usage.
    """
    # Two different tables, two different time columns: an event has `ts`, an
    # interval has `start_ts` (the moment its drop was measured from). Sharing one
    # clause between them addressed a column that does not exist on the other side.
    conds = _time_conds(start_ts, end_ts, col="ts")
    params = [p for _, p in conds]
    and_clause = (" AND " + " AND ".join(c for c, _ in conds)) if conds else ""
    ival_conds = _time_conds(start_ts, end_ts, col="start_ts")
    ival_clause = " WHERE 1=1" + "".join(" AND " + c for c, _ in ival_conds)
    bal = conn.execute(
        "SELECT ts, remaining FROM credit_events"
        " WHERE kind = 'balance' AND remaining IS NOT NULL" + and_clause +
        " ORDER BY ts DESC, source LIMIT 1", params).fetchone()
    ivals = conn.execute(
        "SELECT COUNT(*) AS n,"
        "       COALESCE(SUM(CASE WHEN drop_amount > 0 THEN drop_amount END), 0) AS spent,"
        "       COALESCE(SUM(CASE WHEN drop_amount > 0 THEN allocated END), 0) AS allocated,"
        "       COALESCE(SUM(CASE WHEN drop_amount < 0 THEN 1 ELSE 0 END), 0) AS grants,"
        "       COALESCE(SUM(CASE WHEN drop_amount > 0 THEN drop_amount END), 0)"
        "         - COALESCE(SUM(CASE WHEN drop_amount > 0 THEN allocated END), 0)"
        "           AS unallocated"
        "  FROM credit_intervals" + ival_clause, params).fetchone()
    third = q_third_party_sessions(conn, start_ts, end_ts)
    return {
        "balance": bal["remaining"] if bal else None,
        "balance_ts": bal["ts"] if bal else None,
        "samples": ivals["n"] or 0,
        "spent": ivals["spent"] or 0.0,
        "allocated": ivals["allocated"] or 0.0,
        "unallocated": ivals["unallocated"] or 0.0,
        "grants": ivals["grants"] or 0,
        "third_sessions": third["sessions"] or 0,
        "third_models": third["models"] or 0,
    }

def q_top_models(conn, limit=5, start_ts=None, end_ts=None):
    """Model routes ranked by how many sessions in the window used them.

    Keyed by the decoded ``(model, provider)`` pair, the same key the Tokens tab
    groups on. A session counts once per route, because Trae records no per-request
    model and no tokens. ``model`` is NULL when the id named no catalog entry; those
    rows still count, under the raw id, so the ranking never silently drops a real
    selection just because its name cannot be decoded.
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    where = (" AND " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = (
        "SELECT COALESCE(sm.model, sm.model_id) AS model,"
        "       sm.provider AS provider,"
        "       MAX(COALESCE(sm.third_party, 0)) AS third_party,"
        "       COUNT(DISTINCT sm.session_id) AS sessions"
        "  FROM session_models sm JOIN sessions s ON s.session_id = sm.session_id"
        f" WHERE 1=1{where}"
        " GROUP BY COALESCE(sm.model, sm.model_id), sm.provider"
        " ORDER BY sessions DESC, model LIMIT ?"
    )
    params = [p for _, p in conds] + [int(limit)]
    return conn.execute(sql, params).fetchall()


def q_toolcall_sessions(conn, limit=None, start_ts=None, end_ts=None):
    """Sessions that made tool calls in the window, busiest and newest first.

    Trae CN records a tool call as a snapshot git tag
    (``toolcall-<messageId>-<toolcallId>``) and nowhere else readable, so a call
    has an id but no name, no status and no duration. This is therefore a
    **count per session**, not a per-tool ranking: ``calls`` is the number of
    distinct tool-call tags and ``messages`` the number of distinct message ids
    they hang off. A caller must not present the row as a tool.

    The window rides on the session's ``SESSION_TIME_S``, the same rule every
    other session-keyed query uses, and the ordering is by the session's own
    activity so the list reads as "recent work", not "busiest ever".
    """
    conds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    where = (" AND " + " AND ".join(c for c, _ in conds)) if conds else ""
    sql = (
        "SELECT e.session_id,"
        " s.project_key, s.project,"
        " COUNT(*) AS calls,"
        " COUNT(DISTINCT e.message_id) AS messages,"
        f" {SESSION_TIME_S} AS shown_ts,"
        " CASE WHEN s.last_ts IS NULL THEN 1 ELSE 0 END AS derived_ts,"
        " MIN(e.ts) AS first_ts, MAX(e.ts) AS last_ts"
        "  FROM toolcall_events e JOIN sessions s ON s.session_id = e.session_id"
        f" WHERE 1=1{where}"
        f" GROUP BY e.session_id"
        f" ORDER BY MAX(e.ts) DESC, calls DESC, e.session_id"
    )
    params = [p for _, p in conds]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
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
    """Recent sessions, newest first, with the same time rule as ``q_sessions``."""
    return conn.execute(
        f"SELECT {SESSION_TIME} AS last_ts, session_id, project_key, agent,"
        " turns, toolcalls,"
        " CASE WHEN last_ts IS NULL THEN 1 ELSE 0 END AS derived_ts"
        " FROM sessions"
        f" ORDER BY {SESSION_TIME} DESC, session_id LIMIT ?",
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


# --- model ids, providers, and the credit estimate -------------------------
#
# Trae stores a model selection as one opaque id, e.g.
#   solo_agent_1__DeepSeek-V4-Flash-Official_null
#   solo_agent_3_volcengine-plan_volcengine-plan//ark-code-latest_2837387906
# The catalog name and the channel are *embedded* in it, and the second shape is a
# third-party route. Decoding is a longest-match against the catalog this indexer
# already stores, not a hand-written pattern: the ids carry no separator that is
# reliable across shapes, and a name like `volcengine-plan//ark-code-latest` itself
# contains both separators. The catalog is the authority for what a name means.

# The label and its index: `<label>_<n>_`. Labels are lowercase words joined by
# underscores (`solo_agent`, `solo_coder`, `agent`), so the prefix is unambiguous
# up to the first digit group.
MODEL_ID_PREFIX_RE = re.compile(r"^([a-z][a-z_]*?)_(\d+)_(.*)$", re.S)
# A built-in selection ends in `_null` where the third-party shape carries an id.
MODEL_ID_BUILTIN_SUFFIX = "_null"


def decode_model_id(model_id, catalog):
    """``(model, provider)`` for one Trae model id.

    ``catalog`` maps a catalog name to its provider (``""`` for Trae's own route).
    A name is matched when it appears in the id delimited by underscores, and the
    **longest** match wins -- `DeepSeek-V4-Flash-Official` must beat
    `DeepSeek-V4-Flash`, or an official route gets credited to the wrong model.

    The **id's shape** decides the route: a built-in selection ends in `_null`,
    while a third-party one carries a channel and an id after the model name. A
    catalog entry can carry a provider for a model that is also selected through
    Trae's own route, so the catalog alone must not turn a `_null` selection into
    3P. For a third-party id the catalog's provider is the channel.

    When no catalog name matches, the id is stripped of its label prefix and its
    `_null` tail and returned as-is: it is still what Trae wrote, and inventing a
    prettier name for it would be a guess. The provider is then unknown (``None``,
    rendered `-`), not built-in.
    """
    if not model_id:
        return None, None
    best = None
    probe = f"_{model_id}_"
    for name in catalog:
        if f"_{name}_" in probe and (best is None or len(name) > len(best)):
            best = name
    if best is not None:
        if model_id.endswith(MODEL_ID_BUILTIN_SUFFIX):
            return best, ""
        return best, catalog[best]
    m = MODEL_ID_PREFIX_RE.match(model_id)
    rest = m.group(3) if m else model_id
    if rest.startswith("_"):
        rest = rest[1:]
    if rest.endswith(MODEL_ID_BUILTIN_SUFFIX):
        rest = rest[: -len(MODEL_ID_BUILTIN_SUFFIX)]
    return (rest or None), None


def catalog_providers(conn) -> dict:
    """``{name: provider}`` over the whole catalog, built-in route as ``""``.

    A name can appear under several accounts and groups with the same provider, so
    the mapping is by name -- the same key the Tokens tab groups on. A name that is
    somehow both built-in and third-party keeps the third-party label, because that
    is the fact worth surfacing and the built-in reading is the default.
    """
    out = {}
    for name, provider in conn.execute(
            "SELECT name, COALESCE(NULLIF(MAX(provider), ''), '') AS provider"
            "  FROM models WHERE name IS NOT NULL GROUP BY name"):
        out[name] = provider or ""
    return out


def decode_session_models(conn) -> int:
    """Fill ``session_models.model``/``provider``/``third_party``.

    Returns the number of rows whose reading changed. Idempotent by construction: it
    recomputes from the catalog every run, so a model Trae adds to the catalog -- or a
    decode improved here -- reaches rows indexed weeks ago without a rebuild.
    """
    catalog = catalog_providers(conn)
    changed = 0
    for row in conn.execute(
            "SELECT session_id, agent_label, model_id, model, provider"
            "  FROM session_models").fetchall():
        model, provider = decode_model_id(row["model_id"], catalog)
        if (row["model"], row["provider"]) == (model, provider):
            continue
        conn.execute(
            "UPDATE session_models SET model = ?, provider = ?, third_party = ?"
            " WHERE session_id = ? AND agent_label = ?",
            (model, provider, 1 if provider else 0,
             row["session_id"], row["agent_label"]))
        changed += 1
    return changed


def provider_label(value) -> str:
    """The display label for a stored provider.

    ``None`` means the id named no known model -- rendered `-` rather than
    `Built-in`, because absence of evidence is not evidence of a built-in route.
    ``""`` is Trae's own route, and any other value is the channel name as stored.
    """
    if value is None:
        return "-"
    return "Built-in" if value == "" else value


def route_label(provider, third_party=None) -> str:
    """``Built-in`` / ``3P`` / ``-`` for one selection.

    The short form exists so a table can say which side of the line a model sits on
    without repeating the whole channel name next to ``provider``. ``None`` stays
    ``-``: a selection whose id named no catalog model is not evidence of either
    route, and calling it built-in would be a guess.
    """
    if provider is None and third_party is None:
        return "-"
    if third_party:
        return "3P"
    if provider is None:
        return "-"
    return "Built-in" if provider == "" else "3P"


def allocate_credits(conn) -> int:
    """Split each measured balance drop across the models in its interval.

    The only consumption-derived number in Trae's plaintext is the balance itself,
    sampled roughly once per app start. Between two consecutive samples the balance
    fell by a known amount and Trae does not say which call spent it. So:

    * the interval's **drop** is measured and stored as-is (a rise is a grant: it is
      stored with a negative drop and allocated to nothing);
    * it is split over the sessions *created* inside the interval, by turn count --
      a session with more turns did more work, so it plausibly spent more;
    * a session that selected two models splits its share evenly between them,
      because Trae records no per-model turn count.

    The parts add up to the drop exactly, so the estimate never invents a credit --
    but attribution *inside* an interval is inference, and every surface that shows
    it says `est.`. A session whose share covers no recorded selection has its share
    left unattributed rather than smeared over a model it may never have used.

    Idempotent: both tables are rebuilt from scratch each run, which is also what
    keeps them cheap -- a few dozen rows, not a scan of the sessions.
    """
    conn.execute("DELETE FROM credit_alloc")
    conn.execute("DELETE FROM credit_intervals")
    series = conn.execute(
        "SELECT ts, remaining FROM credit_events"
        " WHERE kind = 'balance' AND remaining IS NOT NULL"
        " ORDER BY ts, source").fetchall()
    selections = {}
    for row in conn.execute(
            "SELECT session_id, agent_label, model_id FROM session_models"):
        selections.setdefault(row["session_id"], []).append(row)
    # Ordered by creation time, so one forward walk serves every interval.
    sessions = conn.execute(
        "SELECT session_id, created_ts, turns FROM sessions"
        " WHERE created_ts IS NOT NULL ORDER BY created_ts, session_id").fetchall()
    pos = 0
    written = 0
    for a, b in zip(series, series[1:]):
        start_ts, end_ts = a["ts"], b["ts"]
        drop = a["remaining"] - b["remaining"]
        while pos < len(sessions) and sessions[pos]["created_ts"] <= start_ts:
            pos += 1
        inside = []
        scan = pos
        while scan < len(sessions) and sessions[scan]["created_ts"] <= end_ts:
            inside.append(sessions[scan])
            scan += 1
        # A session with no turns still happened, so it weighs 1 and not 0:
        # otherwise a window of turn-less sessions would allocate nothing and leave
        # the drop unexplained when there is a perfectly good place to put it.
        weights = [(s, max(int(s["turns"] or 0), 1)) for s in inside]
        total_weight = sum(w for _, w in weights)
        allocated = 0.0
        if drop > 0 and total_weight:
            for session, weight in weights:
                picks = selections.get(session["session_id"]) or []
                if not picks:
                    # No recorded selection: this share is real but has no model
                    # to sit on, so it stays unattributed. Counted, not hidden.
                    continue
                each = drop * weight / total_weight / len(picks)
                for pick in picks:
                    conn.execute(
                        "INSERT OR REPLACE INTO credit_alloc(session_id,"
                        " agent_label, model_id, start_ts, credits)"
                        " VALUES(?,?,?,?,?)",
                        (session["session_id"], pick["agent_label"],
                         pick["model_id"], start_ts, each))
                    allocated += each
                    written += 1
        conn.execute(
            "INSERT OR REPLACE INTO credit_intervals(start_ts, end_ts, drop_amount,"
            " weight, sessions, allocated) VALUES(?,?,?,?,?,?)",
            (start_ts, end_ts, drop, float(total_weight), len(inside), allocated))
    return written

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


def window_count(value, undated, unit=None):
    """A windowed count as text — or ``-`` when the zero is the window's blind spot.

    A session whose snapshot left no timestamp is invisible to every range except All
    time, so "0 sessions" next to such an agent is not a measurement of none. It is the
    same class of lie as an empty token panel reading as "0 tokens", and the dash is the
    shape that says what is actually known: not zero, just not countable here.

    With no window active, `undated` rows are counted by `value` itself, so the dash
    cannot appear — the rule only ever fires when a range is what hid the rows.

    `unit` asks for the prose form (`1 session` / `12 sessions`) instead of a bare
    number, for the lists that read as sentences. A dash never takes the unit: the word
    belongs to a count, and there is none.
    """
    if not value and undated:
        return "-"
    return count_n(value, unit) if unit else f"{value:,}"


def derived_mark(derived) -> str:
    """``~`` in front of a time that came from the session id rather than from Trae.

    A creation second is not a last-activity measurement, and a table where the two look
    identical would quietly upgrade a derivation into a fact. Both surfaces print it.
    """
    return "~" if derived else ""


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

    ``"all"`` has **neither** bound. An upper bound of ``now`` would look harmless
    and still drop every row whose timestamp is NULL — and on this machine 25 of 49
    sessions are exactly that, so "All time" would show them nowhere.
    """
    days = USAGE_RANGES[range_key]
    end = int(now_ms)
    if days is None:
        return None, None
    midnight = datetime.fromtimestamp(end / 1000).replace(
        hour=0, minute=0, second=0, microsecond=0)
    start = midnight - timedelta(days=days - 1)
    return int(start.timestamp() * 1000), end


def _ts_where(start_ts, end_ts):
    if start_ts is None:
        return "ts < ?", [end_ts]
    return "ts >= ? AND ts < ?", [start_ts, end_ts]


def _time_conds(start_ts, end_ts, col="ts"):
    """Time predicates as ``(sql, param)``; empty (all time) when both bounds are None."""
    conds = []
    if start_ts is not None:
        conds.append((f"{col} >= ?", start_ts))
    if end_ts is not None:
        conds.append((f"{col} < ?", end_ts))
    return conds


def _time_filter(start_ts, end_ts, col="ts"):
    """Returns ``(where_prefix, params)``; no filter is ``("", [])``."""
    conds = _time_conds(start_ts, end_ts, col)
    if not conds:
        return "", []
    return " WHERE " + " AND ".join(c for c, _ in conds), [p for _, p in conds]


def q_kpi(conn, start_ts=None, end_ts=None) -> dict:
    """Windowed counts for the Dashboard (the status-bar numbers, windowed).

    ``sessions``/``projects`` are windowed on the session's ``COALESCE(last_ts,
    created_ts)``; ``prompts`` and the inventory counts have no timestamp of their own,
    so they are all-time. Both bounds ``None`` is all-time.

    ``unmeasured`` is also all-time on purpose: it is the population whose position came
    from the id rather than from Trae, and a range does not turn a derivation into a
    measurement. The Dashboard discloses it because every ``~`` on screen refers to it.
    """
    where, params = _time_filter(start_ts, end_ts, col=SESSION_TIME)

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
        "unmeasured": one(f"SELECT COUNT(*) FROM sessions WHERE {UNMEASURED}"),
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
    where, params = _time_filter(start_ts, end_ts, col=SESSION_TIME)
    return conn.execute(
        f"SELECT strftime('%Y-%m-%d', {SESSION_TIME} / 1000,"
        "                        'unixepoch', 'localtime')"
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


def q_usage_summary(conn, start_ts=None, end_ts=None) -> dict:
    """Headline counts for the Usage page's summary panels, windowed.

    cbut's Usage page is a per-request ledger; Trae CN writes no per-request
    record, so this page is per **session** and these are session totals. Every
    number here is a count of something the writer stored, so a real ``0`` is
    printed as ``0`` — except ``unmeasured``, which is reported separately for
    the same reason ``q_kpi`` reports it: a range does not turn a derivation
    into a measurement, so it stays all-time.

    ``top_model`` is ``{"model", "provider", "third_party", "sessions"}`` or
    ``None``: a session counts once for the route it was set to, exactly as
    ``q_top_models`` ranks. ``third_sessions``/``third_models`` size the part of the
    window that went through a third-party channel.
    """
    where, params = _time_filter(start_ts, end_ts, col=SESSION_TIME)

    def one(sql, p=()):
        return conn.execute(sql, p).fetchone()[0]

    # session_models carries no timestamp of its own, so its window rides on the
    # joined session — the same shape q_top_models already uses.
    mconds = _time_conds(start_ts, end_ts, col=SESSION_TIME_S)
    m_and, m_params = _on_time(mconds)
    top = conn.execute(
        "SELECT COALESCE(sm.model, sm.model_id) AS model, sm.provider AS provider,"
        "       MAX(COALESCE(sm.third_party, 0)) AS third_party,"
        "       COUNT(DISTINCT sm.session_id) AS sessions"
        "  FROM session_models sm JOIN sessions s ON s.session_id = sm.session_id"
        f" WHERE 1=1{m_and}"
        " GROUP BY COALESCE(sm.model, sm.model_id), sm.provider"
        " ORDER BY sessions DESC, model LIMIT 1",
        m_params,
    ).fetchone()
    third = conn.execute(
        "SELECT COUNT(DISTINCT sm.session_id) AS sessions,"
        "       COUNT(DISTINCT COALESCE(sm.model, sm.model_id)) AS models"
        "  FROM session_models sm JOIN sessions s ON s.session_id = sm.session_id"
        f" WHERE sm.third_party = 1{m_and}", m_params,
    ).fetchone()
    return {
        "sessions": one(f"SELECT COUNT(*) FROM sessions{where}", params),
        "projects": one(
            f"SELECT COUNT(DISTINCT project_key) FROM sessions{where}", params),
        "turns": one(f"SELECT COALESCE(SUM(turns),0) FROM sessions{where}", params),
        "toolcalls": one(
            f"SELECT COALESCE(SUM(toolcalls),0) FROM sessions{where}", params),
        "models": one(
            "SELECT COUNT(DISTINCT COALESCE(sm.model, sm.model_id))"
            "  FROM session_models sm"
            " JOIN sessions s ON s.session_id = sm.session_id"
            f" WHERE 1=1{m_and}", m_params),
        "third_sessions": third["sessions"] or 0,
        "third_models": third["models"] or 0,
        "unmeasured": one(f"SELECT COUNT(*) FROM sessions WHERE {UNMEASURED}"),
        "top_model": dict(top) if top else None,
    }


def table_names(conn) -> list:
    """Every user table, name-sorted — the enumerator `tcut export` walks.

    Read from `sqlite_master` instead of copied from a list, because a hand-kept table list
    is how `export` came to claim the whole index while ten indexed tables were never in it:
    nothing could notice a table that a migration added and the export forgot. A schema
    change now reaches the export by itself, or the guard on it says so in that one test.
    """
    return [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name")]


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
        "first_ts": one(f"SELECT MIN({SESSION_TIME}) FROM sessions"),
        "last_ts": one(f"SELECT MAX({SESSION_TIME}) FROM sessions"),
        "inventory": one("SELECT COUNT(*) FROM inventory"),
        # Records no handler claimed. Non-zero after a Trae update means the
        # format moved under us, not that you stopped using it.
        "unparsed_records": one("SELECT COALESCE(SUM(count),0) FROM unparsed"),
        "unparsed_kinds": one("SELECT COUNT(DISTINCT reason) FROM unparsed"),
    }
