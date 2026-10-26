"""tcut-sync — indexer for the Trae CN usage tracker.

Reads Trae CN's on-disk data (read-only) into the tracker's SQLite index. It
never writes into Trae's own directories.

Sources, all under ``TCUT_TRAE_CN_HOME`` (``~/.trae-cn``) and ``TCUT_TRAE_CN_DATA``
(``~/.config/Trae CN``):

  memory/projects/<proj>/<day>/session_memory_<sid>.jsonl   per-session summary
  memory/projects/<proj>/<day>/topics.md                    topic lines
  memory/user_profile.md                                    agent memory prose
  memory/projects/<proj>/project_memory.md                  per-project memory prose
  <data>/ModularData/ai-agent/snapshot/<sid>/v2/.git        turn/toolcall tags
  <data>/User/{workspaceStorage/*,globalStorage}/state.vscdb  prompts, agents, models
  skills/ builtin_skills/ plugins/ mcps/                    installed inventory
  <data>/logs/<session>/window*/renderer.log                credit balance lines

Incremental: streamed JSONL by byte offset; whole-file sources by (size, mtime).
``--full`` rebuilds from scratch after a snapshot.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tcut_db as db  # noqa: E402

# --- source roots ----------------------------------------------------------


def memory_root(cfg=None) -> Path:
    return db.TRAE_CN_HOME / "memory"


def snapshot_root() -> Path:
    return db.TRAE_CN_DATA / "ModularData" / "ai-agent" / "snapshot"


def user_root() -> Path:
    return db.TRAE_CN_DATA / "User"


# --- format registry -------------------------------------------------------
# The one place that states what this parser depends on. ``format_doc()`` renders
# it into ``docs/maintenance/trae-cn-format.md`` between the generated markers, and
# ``scripts/tests/test_format_registry.py`` holds the registry to the parser in both
# directions — nothing read unregistered, nothing registered unread.

# state.vscdb keys this indexer reads, by role. The value is the literal ``LIKE``
# pattern ``_ingest_vscdb`` passes to ``_vscdb_value`` / ``_keys_like``, so a rename
# is one edit here and the guard names any call site that still inlines the old one.
VSCDB_KEYS = {
    "prompt_history": "icube-ai-agent-storage-input-history",
    "session_agent_map": "icube_session_agent_map",
    "agent_definitions": "currentAgentData%",
    "model_catalog": "%_AI.agent.model.model_list_map",
    "session_selected_model": "%:AI.agent.model.session_selected_model",
    "session_list": "memento/icube-ai-agent-storage",
}

# Literal JSON keys read out of a ``state.vscdb`` blob. A model-catalog entry also
# carries ``ak``, ``sk``, ``base_url`` and ``custom_config``; those are deliberately
# absent — for a custom endpoint they can hold credentials and are never touched.
VSCDB_FIELDS = frozenset({
    "inputText", "sessionId", "agent_id", "name", "type", "description",
    "display_name", "provider", "model_type", "fee_model_level",
    "prompt_max_tokens", "modelId", "mode", "list",
    "features", "consumption_rate", "data", "rate",
    "context_window_size", "default", "max",
})

# Reasons an input is counted in ``unparsed`` instead of indexed. The vocabulary is
# here so a new source cannot invent a reason nobody can look up, and so a reason
# that stops being emitted is visible rather than merely quiet.
UNPARSED_REASONS = (
    "session_memory:bad_name", "session_memory:not_json", "session_memory:not_object",
    "topic:no_match", "topic:bad_time",
    "snapshot:time_unreadable",
    "vscdb:open_failed", "vscdb:read_failed",
    "model_map:not_json", "model_map:shape", "model_map:group_shape",
    "model_map:entry_shape", "model_map:no_name",
    "session_model:not_json", "session_model:shape", "session_model:no_model_id",
    "mcp:bad_metadata",
    "credit_log:read_failed", "credit_log:bad_timestamp", "credit_log:event_shape",
)


def format_doc() -> str:
    """Render the format registry as markdown (``tcut format``).

    Every value is read back out of the constants rather than retyped, so the
    checked-in document cannot describe a surface the code no longer reads.
    ``scripts/tests/test_maintenance_docs.py`` holds the file to this output.
    """
    def bullets(values):
        return ", ".join(f"`{v}`" for v in values)

    keys = "\n".join(f"  - `{role}` → `{pattern}`" for role, pattern in VSCDB_KEYS.items())
    return "".join([
        "- **`state.vscdb` keys read** (the literal `LIKE` pattern each is reached "
        "through):\n" + keys + "\n",
        f"- **JSON fields read out of a `state.vscdb` blob**: "
        f"{bullets(sorted(VSCDB_FIELDS))}\n",
        "- **Credential fields never read** (a custom-provider entry carries them "
        "beside the fields above): `ak`, `sk`, `base_url`, `custom_config`\n",
        f"- **Credit-balance log tag**: `{USAGE_TAG}`\n",
        f"- **`unparsed` reasons**: {bullets(UNPARSED_REASONS)}\n",
    ])


# --- small helpers ---------------------------------------------------------

_SESSION_MEMORY_RE = re.compile(r"^session_memory_([0-9a-f]+)\.jsonl$")
_TOPIC_RE = re.compile(
    r"^\[session_id:\s*([^|\]]+?)\s*\|\s*topic_summary_time:\s*([^\]]+?)\s*\]\s*(.*)$")
_TURNTAG_RE = re.compile(r"^(?:before|after)-chat-turn-(.+)$")
_TOOLCALLTAG_RE = re.compile(r"^toolcall-([^-]+)-(.+)$")


def decode_project(key: str) -> str:
    """Best-effort project path from Trae's memory directory name.

    ``-home-user-Public--p2-ccbcb99c...`` decodes to ``/home/user/Public``.
    The ``--p2-<hash>`` suffix is a stable per-project id, not a path. A real
    hyphen in a directory name cannot be told from the separator, so this is a
    display convenience, not a guaranteed path.
    """
    base = key.split("--p2-")[0] if "--p2-" in key else key
    if base.startswith("-"):
        base = base.replace("-", "/")
    return re.sub(r"/{2,}", "/", base)


def parse_day(text: str):
    """``YYYYMMDD`` -> epoch ms at local midnight, or ``None``."""
    try:
        return int(datetime.strptime(text, "%Y%m%d").timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def parse_topic_time(text: str):
    """``YYYY-MM-DD HH:MM:SS`` (local) -> epoch ms, or ``None``."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text.strip(), fmt).timestamp() * 1000)
        except ValueError:
            continue
    return None


def _stat(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime


def _cursor(conn, source: str):
    row = conn.execute(
        "SELECT size, mtime, offset FROM sync_state WHERE source = ?",
        (source,)).fetchone()
    return (row["size"], row["mtime"], row["offset"]) if row else (None, None, 0)


def _set_cursor(conn, source: str, size, mtime, offset) -> None:
    conn.execute(
        "INSERT INTO sync_state(source, size, mtime, offset) VALUES(?,?,?,?)"
        " ON CONFLICT(source) DO UPDATE SET"
        " size=excluded.size, mtime=excluded.mtime, offset=excluded.offset",
        (source, size, mtime, offset))


def _changed(conn, path: Path):
    """``(size, mtime, offset)`` when a whole-file source changed, else ``None``."""
    st = _stat(path)
    if st is None:
        return None
    size, mtime = st
    old_size, old_mtime, old_offset = _cursor(conn, str(path))
    if old_size == size and old_mtime == mtime:
        return None
    return size, mtime, old_offset


# --- 1. session_memory_*.jsonl (streamed, byte-offset) ---------------------


def scan_session_memory(conn, cfg, root=None) -> int:
    """Index per-session summaries. Returns rows touched."""
    root = root or (memory_root() / "projects")
    if not root.is_dir():
        return 0
    touched = 0
    for proj_dir in sorted(root.iterdir()):
        if not proj_dir.is_dir():
            continue
        project_key = proj_dir.name
        project = decode_project(project_key)
        for day_dir in sorted(proj_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            day_ms = parse_day(day_dir.name)
            for path in sorted(day_dir.glob("session_memory_*.jsonl")):
                m = _SESSION_MEMORY_RE.match(path.name)
                if not m:
                    db.note_unparsed(conn, "session_memory:bad_name", 1)
                    continue
                session_id = m.group(1)
                touched += _ingest_session_memory(
                    conn, cfg, path, session_id, project_key, project, day_ms)
    return touched


def _ingest_session_memory(conn, cfg, path, session_id, project_key, project,
                           day_ms) -> int:
    st = _stat(path)
    if st is None:
        return 0
    size, mtime = st
    _, _, offset = _cursor(conn, str(path))
    if offset > size:                      # file shrank/rotated: re-read
        offset = 0
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            blob = fh.read()
    except OSError:
        return 0
    store = cfg["store_content"]
    rows = 0
    # Consume only complete, parseable lines. Every segment before the final
    # newline is one. The trailing segment (no newline yet) counts as consumed
    # *only* if it already parses: these files are appended to a line at a time,
    # so a run that caught a write mid-flight must leave that tail at the
    # cursor, or the next run reads only the bytes appended after it and the
    # record is lost for good. A tail that parses is a complete record that just
    # happens to lack its newline (Trae writes whole lines).
    parts = blob.split(b"\n")
    tail = parts.pop()
    segments = [s for s in parts if s.strip()]
    consumed = len(blob) - len(tail)
    if tail.strip():
        try:
            json.loads(tail)
        except (ValueError, UnicodeDecodeError):
            pass                       # partial write: not consumed
        else:
            segments.append(tail)
            consumed += len(tail)
    for raw in segments:
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            db.note_unparsed(conn, "session_memory:not_json", 1)
            continue
        if not isinstance(obj, dict):
            db.note_unparsed(conn, "session_memory:not_object", 1)
            continue
        intent = obj.get("intent") if store else None
        outcome = obj.get("outcome") if store else None
        conn.execute(
            "INSERT INTO sessions(session_id, project_key, project, day,"
            " intent, outcome, first_ts, last_ts) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            " project_key=COALESCE(excluded.project_key, project_key),"
            " project=COALESCE(excluded.project, project),"
            " day=COALESCE(excluded.day, day),"
            " intent=COALESCE(excluded.intent, intent),"
            " outcome=COALESCE(excluded.outcome, outcome),"
            " first_ts=COALESCE(first_ts, excluded.first_ts),"
            " last_ts=COALESCE(last_ts, excluded.last_ts)",
            (session_id, project_key, project, day_dir_name(day_ms), intent,
             outcome, day_ms, day_ms),
        )
        rows += 1
        # actions[] / learned[]: replace wholesale (the file is a snapshot).
        if store:
            _replace_list(conn, "session_actions", session_id, obj.get("actions"))
            _replace_list(conn, "session_learned", session_id, obj.get("learned"))
    _set_cursor(conn, str(path), size, mtime,
                min(offset + consumed, size))
    return rows


def day_dir_name(day_ms):
    if day_ms is None:
        return None
    return datetime.fromtimestamp(day_ms / 1000).strftime("%Y%m%d")


def _replace_list(conn, table, session_id, values) -> None:
    conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
    if not isinstance(values, list):
        return
    for idx, text in enumerate(values):
        if isinstance(text, str) and text:
            conn.execute(
                f"INSERT OR REPLACE INTO {table}(session_id, idx, text)"
                " VALUES(?,?,?)", (session_id, idx, text))


# --- 2. topics.md ----------------------------------------------------------


def scan_topics(conn, cfg, root=None) -> int:
    root = root or (memory_root() / "projects")
    if not root.is_dir():
        return 0
    touched = 0
    for proj_dir in sorted(root.iterdir()):
        if not proj_dir.is_dir():
            continue
        for day_dir in sorted(proj_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            path = day_dir / "topics.md"
            if not path.is_file():
                continue
            changed = _changed(conn, path)
            if changed is None:
                continue
            touched += _ingest_topics(conn, cfg, path, proj_dir.name)
            size, mtime, _ = changed
            _set_cursor(conn, str(path), size, mtime, 0)
    return touched


def _ingest_topics(conn, cfg, path, project_key) -> int:
    store = cfg["store_content"]
    rows = 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _TOPIC_RE.match(line.strip())
        if not m:
            db.note_unparsed(conn, "topic:no_match", 1)
            continue
        session_id, when, summary = m.group(1), m.group(2), m.group(3)
        ts = parse_topic_time(when)
        if ts is None:
            db.note_unparsed(conn, "topic:bad_time", 1)
            continue
        conn.execute(
            "INSERT OR REPLACE INTO topics(session_id, ts, project_key, summary)"
            " VALUES(?,?,?,?)",
            (session_id, ts, project_key, summary if store else None))
        rows += 1
    return rows


# --- 3. memory documents (prose, split into paragraphs) --------------------


def scan_memory_docs(conn, cfg, root=None) -> int:
    """Index ``user_profile.md`` and every ``project_memory.md`` as paragraphs.

    Replaced **per document**, never by clearing the table first: the scan only
    re-reads a document whose size or mtime changed, so a clear-all would wipe
    every unchanged document on every run — and a 30-second sync timer would
    leave the table empty for good after the first pass.
    """
    root = root or memory_root()
    if not root.is_dir():
        return 0
    store = cfg["store_content"]
    if not store:
        conn.execute("DELETE FROM memory")
        return 0
    docs = []
    if (root / "user_profile.md").is_file():
        docs.append(("user_profile", root / "user_profile.md"))
    proj_root = root / "projects"
    if proj_root.is_dir():
        for path in sorted(proj_root.glob("*/project_memory.md")):
            docs.append((f"project:{path.parent.name}", path))
    rows = 0
    for scope, path in docs:
        changed = _changed(conn, path)
        if changed is None:
            continue
        # A document is one source: drop its own rows, then write the current ones.
        conn.execute("DELETE FROM memory WHERE scope = ?", (scope,))
        for idx, para in enumerate(_paragraphs(path)):
            conn.execute(
                "INSERT OR REPLACE INTO memory(scope, idx, text) VALUES(?,?,?)",
                (scope, idx, para))
            rows += 1
        size, mtime, _ = changed
        _set_cursor(conn, str(path), size, mtime, 0)
    # The scan enumerates every document that exists, so a scope it did not see
    # is a document that was deleted — and its rows have to go with it.
    scopes = [scope for scope, _ in docs]
    if scopes:
        conn.execute(
            "DELETE FROM memory WHERE scope NOT IN (%s)"
            % ",".join("?" * len(scopes)), scopes)
    else:
        conn.execute("DELETE FROM memory")
    return rows


def _paragraphs(path: Path):
    """Split a markdown doc into non-empty paragraph blocks (blank-line separated)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out, buf = [], []
    for line in text.splitlines():
        if line.strip():
            buf.append(line.rstrip())
        elif buf:
            out.append("\n".join(buf))
            buf = []
    if buf:
        out.append("\n".join(buf))
    return out


# --- 4. snapshot git tags (turns + toolcall ids) ---------------------------

GIT_HASH_RE = re.compile(r"^[0-9a-f]{40}$")


def scan_snapshots(conn, cfg, root=None) -> int:
    """Index per-session turn and toolcall ids from the snapshot repos.

    Only ids and timestamps: Trae stores no tool *name* anywhere readable, so a
    toolcall row is a count, not a name.
    """
    root = root or snapshot_root()
    if not root.is_dir():
        return 0
    rows = 0
    for session_dir in sorted(root.iterdir()):
        if not session_dir.is_dir():
            continue
        git_dir = session_dir / "v2" / ".git"
        if not git_dir.is_dir():
            continue
        if not _git_dir_changed(conn, git_dir):
            continue
        session_id = session_dir.name
        conn.execute(
            "INSERT OR IGNORE INTO sessions(session_id) VALUES(?)", (session_id,))
        for tag, sha in _iter_tags(git_dir):
            tm = _TURNTAG_RE.match(tag)
            cm = None if tm else _TOOLCALLTAG_RE.match(tag)
            if not (tm or cm):
                continue
            ts = _commit_time(git_dir, sha)
            if ts is None:
                # A row with no time is dropped by every windowed view, so a gap here
                # is a fact about the store. It used to be silent, and silent is how
                # "all timestamps NULL" passed for a year of green tests.
                db.note_unparsed(conn, "snapshot:time_unreadable", 1)
            if tm:
                conn.execute(
                    "INSERT OR REPLACE INTO turns(session_id, turn_id, ts)"
                    " VALUES(?,?,?)", (session_id, tm.group(1), ts))
                rows += 1
                continue
            conn.execute(
                "INSERT OR REPLACE INTO toolcall_events"
                "(session_id, message_id, toolcall_id, ts) VALUES(?,?,?,?)",
                (session_id, cm.group(1), cm.group(2), ts))
            rows += 1
        _set_cursor(conn, str(git_dir), 0, _git_fingerprint(git_dir), 0)
    return rows


def _git_fingerprint(git_dir: Path) -> float:
    """Newest mtime among the tag stores — a cheap "did refs change?" marker."""
    stamps = [0.0]
    tags_dir = git_dir / "refs" / "tags"
    if tags_dir.is_dir():
        stamps.append(tags_dir.stat().st_mtime)
    packed = git_dir / "packed-refs"
    if packed.is_file():
        stamps.append(packed.stat().st_mtime)
    return max(stamps)


def _git_dir_changed(conn, git_dir: Path) -> bool:
    _, old_mtime, _ = _cursor(conn, str(git_dir))
    return old_mtime != _git_fingerprint(git_dir)


def _iter_tags(git_dir: Path):
    """Yield ``(tag_name, commit_sha)`` from loose refs and packed-refs."""
    tags_dir = git_dir / "refs" / "tags"
    if tags_dir.is_dir():
        for path in sorted(tags_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                sha = path.read_text(encoding="ascii").strip()
            except OSError:
                continue
            if GIT_HASH_RE.match(sha):
                yield path.relative_to(tags_dir).as_posix(), sha
    packed = git_dir / "packed-refs"
    if packed.is_file():
        try:
            text = packed.read_text(encoding="ascii", errors="replace")
        except OSError:
            text = ""
        for line in text.splitlines():
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].startswith("refs/tags/"):
                sha, name = parts[0], parts[1][len("refs/tags/"):]
                if GIT_HASH_RE.match(sha):
                    yield name, sha


def _loose_object(git_dir: Path, sha: str):
    """Return ``(type, body)`` for a loose object, or ``(None, None)``.

    Loose only. A packed object needs the pack index, and reading one means either
    shipping a pack parser or shelling out to git — both worse than the gap. The gap
    is not left silent: ``scan_snapshots`` reports every tag whose time it could not
    get, because an unreadable object used to NULL out all 89 turn timestamps and 139
    toolcall timestamps without saying so.
    """
    obj_path = git_dir / "objects" / sha[:2] / sha[2:]
    if not obj_path.is_file():
        return None, None
    try:
        raw = zlib.decompress(obj_path.read_bytes())
    except (OSError, zlib.error):
        return None, None
    header, _, body = raw.partition(b"\x00")        # "<type> <size>" NUL content
    obj_type = header.partition(b" ")[0].decode(errors="replace")
    return obj_type, body


def _first_epoch(body: bytes, prefixes):
    """First ``> <epoch> <tz>`` among the given header lines, as epoch ms."""
    for line in body.split(b"\n"):
        for prefix in prefixes:
            if line.startswith(prefix):
                m = re.search(rb">\s+(\d+)\s+[+-]\d{4}", line)
                if m:
                    return int(m.group(1)) * 1000
    return None


def _commit_time(git_dir: Path, sha: str):
    """The timestamp a ref points at, as epoch ms, or ``None``.

    Trae's snapshot tags are *annotated*: the ref names a ``tag`` object whose
    ``object`` line points at the commit. Measured on one session repo's 87 tags —
    every object the refs named was type ``tag``, and inside those commits
    ``author`` and ``committer`` agreed on 87/87. So peel the tag, then read the
    commit; a reader that only recognised a ``commit `` header returned ``None`` for
    every one of them.

    When only the tag object is readable, its ``tagger`` line is used: measured to
    sit roughly ten seconds after the commit it tags, which is honest for a turn and
    better than reporting no time at all.
    """
    tagger_ms = None
    for _ in range(4):                    # tag -> commit, with room for a tag chain
        obj_type, body = _loose_object(git_dir, sha)
        if obj_type is None:
            break
        if obj_type == "commit":
            return _first_epoch(body, (b"committer ", b"author ")) or tagger_ms
        if obj_type == "tag":
            tagger_ms = tagger_ms or _first_epoch(body, (b"tagger ",))
            m = re.search(rb"^object ([0-9a-f]{40})$", body, re.M)
            if not m:
                break
            sha = m.group(1).decode()
            continue
        break                             # a tree or blob is not something to time
    return tagger_ms


# --- 5. state.vscdb (prompts, agents, models) ------------------------------


def _iter_vscdb():
    """Every state.vscdb under workspaceStorage and globalStorage.

    Yields ``(workspace, vscdb_path, workspace_json_or_None)``.
    """
    user = user_root()
    ws = user / "workspaceStorage"
    if ws.is_dir():
        for path in sorted(ws.glob("*/state.vscdb")):
            wj = path.parent / "workspace.json"
            yield path.parent.name, path, (wj if wj.is_file() else None)
    gs = user / "globalStorage" / "state.vscdb"
    if gs.is_file():
        yield "global", gs, None


def scan_state_vscdb(conn, cfg) -> int:
    rows = 0
    for workspace, path, workspace_json in _iter_vscdb():
        if workspace_json is not None:
            _ingest_workspace_json(conn, workspace, workspace_json)
        changed = _changed(conn, path)
        if changed is None:
            continue
        try:
            conn2 = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            db.note_unparsed(conn, "vscdb:open_failed", 1)
            continue
        conn2.row_factory = sqlite3.Row
        try:
            rows += _ingest_vscdb(conn, conn2, workspace, cfg["store_content"])
        except sqlite3.Error:
            db.note_unparsed(conn, "vscdb:read_failed", 1)
        finally:
            conn2.close()
        size, mtime, _ = changed
        _set_cursor(conn, str(path), size, mtime, 0)
    return rows


def _vscdb_value(conn2, key):
    row = conn2.execute(
        "SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
    if row is None or row["value"] is None:
        return None
    value = row["value"]
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


_PCT_RE = re.compile(r"%([0-9A-Fa-f]{2})")


def _unquote_uri_path(text: str) -> str:
    """Percent-decode a ``file://`` path without importing urllib.

    Kept local so the module's import surface stays free of the ``urllib``
    root (the privacy guard forbids it). Decodes percent triplets to bytes and
    then UTF-8, so a non-ASCII path round-trips.
    """
    if "%" not in text:
        return text
    out = bytearray()
    i = 0
    while i < len(text):
        m = _PCT_RE.match(text, i)
        if m:
            out.append(int(m.group(1), 16))
            i = m.end()
        else:
            out.extend(text[i].encode("utf-8"))
            i += 1
    return out.decode("utf-8", "replace")


def _folder_from_uri(uri):
    if not isinstance(uri, str) or not uri.startswith("file://"):
        return None
    path = uri[len("file://"):]
    return _unquote_uri_path(path) or None


def _ingest_workspace_json(conn, workspace, path) -> None:
    """Record workspace id -> real folder from workspace.json."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    folder = _folder_from_uri(data.get("folder")) if isinstance(data, dict) else None
    if folder:
        conn.execute(
            "INSERT OR REPLACE INTO workspaces(workspace, folder) VALUES(?,?)",
            (workspace, folder))


def _normalize_path(text: str) -> str:
    """Trae's project-key encoding: every non-alphanumeric becomes ``-``."""
    return re.sub(r"[^A-Za-z0-9]", "-", text)


def _resolve_projects(conn) -> None:
    """Replace decoded project paths with the real folder when we know it.

    ``workspace.json`` gives the true path for each workspace; the memory
    project-key encodes the same path lossily, so we match them by the shared
    normalisation instead of trusting the guess.
    """
    by_norm = {_normalize_path(r["folder"]): r["folder"]
               for r in conn.execute(
                   "SELECT folder FROM workspaces WHERE folder IS NOT NULL")}
    if not by_norm:
        return
    for row in conn.execute(
            "SELECT session_id, project_key FROM sessions"
            " WHERE project_key IS NOT NULL").fetchall():
        key = row["project_key"]
        base = key.split("--p2-")[0] if "--p2-" in key else key
        folder = by_norm.get(_normalize_path(base))
        if folder:
            conn.execute("UPDATE sessions SET project = ? WHERE session_id = ?",
                         (folder, row["session_id"]))


def _text(value):
    """A string field, or NULL — never a coerced number or ``"None"``."""
    return value if isinstance(value, str) and value else None


def _int(value):
    """An integer field, or NULL. ``bool`` is excluded: it is an int subclass, and a
    ``true`` in a numeric column would be stored as a real-looking 1."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _context_window(entry):
    """``context_window_size`` is ``{"max": [n], "default": n}``; take the default."""
    cw = entry.get("context_window_size")
    if not isinstance(cw, dict):
        return None
    default = _int(cw.get("default"))
    if default is not None:
        return default
    high = cw.get("max")
    if isinstance(high, list) and high:
        return _int(high[0])
    return None


def _consumption_rate(entry):
    """Trae's own credits-per-call multiplier, nested three levels down.

    Read at this depth on purpose: the same shape has been observed under two
    spellings elsewhere in Trae's catalog, so a missing level means NULL rather
    than a 0 that would look like "free".
    """
    features = entry.get("features")
    if not isinstance(features, dict):
        return None
    rate = features.get("consumption_rate")
    if not isinstance(rate, dict):
        return None
    data = rate.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get("rate")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _ingest_vscdb(conn, conn2, workspace, store_content=True) -> int:
    rows = 0
    history = _vscdb_value(conn2, VSCDB_KEYS["prompt_history"])
    if isinstance(history, list):
        conn.execute("DELETE FROM prompts WHERE workspace = ?", (workspace,))
        for idx, item in enumerate(history):
            # Prompt history is the user's own text: it is stored only under the
            # documented ``store_content`` deviation, never by default-off.
            text = item.get("inputText") if (store_content and isinstance(item, dict)) else None
            if isinstance(text, str) and text.strip():
                conn.execute(
                    "INSERT OR REPLACE INTO prompts(workspace, idx, text)"
                    " VALUES(?,?,?)", (workspace, idx, text))
                rows += 1
    # session -> agent map
    mapping = _vscdb_value(conn2, VSCDB_KEYS["session_agent_map"])
    if isinstance(mapping, dict):
        for sid, agent in mapping.items():
            if not isinstance(agent, str):
                continue
            conn.execute(
                "INSERT INTO sessions(session_id, agent) VALUES(?,?)"
                " ON CONFLICT(session_id) DO UPDATE SET agent = excluded.agent",
                (sid, agent))
            conn.execute(
                "INSERT OR IGNORE INTO agents(name) VALUES(?)", (agent,))
            rows += 1
    # agent definitions
    for key in _keys_like(conn2, VSCDB_KEYS["agent_definitions"]):
        data = _vscdb_value(conn2, key)
        if isinstance(data, dict):
            name = data.get("name") or data.get("agent_id")
            if isinstance(name, str) and name:
                conn.execute(
                    "INSERT OR REPLACE INTO agents(name, kind, description)"
                    " VALUES(?,?,?)",
                    (name, data.get("type"), data.get("description")))
                rows += 1
    # models: the catalog Trae was handed, one key per account
    # (``<uid>_AI.agent.model.model_list_map``; ``undefined`` is a real prefix).
    # Only pricing/shape fields are read. An entry also carries `ak`, `sk`,
    # `base_url` and `custom_config`, which for a custom endpoint can hold
    # credentials — those keys are never touched, so they cannot reach the index.
    for key in _keys_like(conn2, VSCDB_KEYS["model_catalog"]):
        account = key.rsplit("_AI.agent.model.model_list_map", 1)[0] or "undefined"
        data = _vscdb_value(conn2, key)
        if data is None:
            db.note_unparsed(conn, "model_map:not_json", 1)
            continue
        if not isinstance(data, dict):
            db.note_unparsed(conn, "model_map:shape", 1)
            continue
        for group, entries in data.items():
            if not isinstance(entries, list):
                db.note_unparsed(conn, "model_map:group_shape", 1)
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    db.note_unparsed(conn, "model_map:entry_shape", 1)
                    continue
                name = entry.get("name") or entry.get("display_name")
                if not isinstance(name, str) or not name:
                    db.note_unparsed(conn, "model_map:no_name", 1)
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO models(account, group_name, name,"
                    " display_name, provider, model_type, fee_level,"
                    " consumption_rate, context_window, prompt_max)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (account, group, name,
                     _text(entry.get("display_name")),
                     _text(entry.get("provider")),
                     _text(entry.get("model_type")),
                     _int(entry.get("fee_model_level")),
                     _consumption_rate(entry),
                     _context_window(entry),
                     _int(entry.get("prompt_max_tokens"))))
                rows += 1
    # which model each session was set to (`<uid>:AI.agent.model...`)
    for key in _keys_like(conn2, VSCDB_KEYS["session_selected_model"]):
        account = key.rsplit(":AI.agent.model.session_selected_model", 1)[0]
        data = _vscdb_value(conn2, key)
        if data is None:
            db.note_unparsed(conn, "session_model:not_json", 1)
            continue
        if not isinstance(data, dict):
            db.note_unparsed(conn, "session_model:shape", 1)
            continue
        for sid, labels in data.items():
            if not isinstance(sid, str) or not isinstance(labels, dict):
                db.note_unparsed(conn, "session_model:shape", 1)
                continue
            for label, sel in labels.items():
                model_id = sel.get("modelId") if isinstance(sel, dict) else None
                if not isinstance(model_id, str) or not model_id:
                    db.note_unparsed(conn, "session_model:no_model_id", 1)
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO session_models(session_id, account,"
                    " agent_label, model_id, mode) VALUES(?,?,?,?,?)",
                    (sid, account, label, model_id,
                     _int(sel.get("mode")) if isinstance(sel, dict) else None))
                rows += 1
    # session list
    sessions = _vscdb_value(conn2, VSCDB_KEYS["session_list"])
    if isinstance(sessions, dict):
        for item in sessions.get("list", []):
            sid = item.get("sessionId") if isinstance(item, dict) else None
            if isinstance(sid, str):
                conn.execute(
                    "INSERT OR IGNORE INTO sessions(session_id) VALUES(?)", (sid,))
    return rows


def _keys_like(conn2, pattern):
    return [r[0] for r in conn2.execute(
        "SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))]


# --- 6. inventory (skills / plugins / mcps) --------------------------------


def scan_inventory(conn, cfg) -> int:
    conn.execute("DELETE FROM inventory")
    rows = 0
    rows += _scan_skills(conn)
    rows += _scan_plugins(conn)
    rows += _scan_mcps(conn)
    return rows


def _inv(conn, kind, name, source, path=None, owner="", version=None):
    conn.execute(
        "INSERT OR REPLACE INTO inventory(kind, name, owner_plugin, version,"
        " path, source) VALUES(?,?,?,?,?,?)",
        (kind, name, owner, version, str(path) if path else None, source))


def _scan_skills(conn) -> int:
    rows = 0
    for name, source, base in (
        (None, "user", db.TRAE_CN_HOME / "skills"),
        (None, "builtin", db.TRAE_CN_HOME / "builtin_skills"),
    ):
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            _inv(conn, "skill", entry.name, source, path=entry)
            rows += 1
    # plugin-owned skills: plugins/<marketplace>/<plugin>/<version>/skills/<name>
    plugins_root = db.TRAE_CN_HOME / "plugins"
    if plugins_root.is_dir():
        for sk in sorted(plugins_root.glob("*/*/*/skills/*")):
            if sk.is_dir():
                owner = sk.parents[2].name
                _inv(conn, "skill", sk.name, "plugin", path=sk, owner=owner)
                rows += 1
    return rows


def _scan_plugins(conn) -> int:
    root = db.TRAE_CN_HOME / "plugins"
    if not root.is_dir():
        return 0
    rows = 0
    for marketplace_dir in sorted(root.iterdir()):
        if not marketplace_dir.is_dir():
            continue
        for plugin_dir in sorted(marketplace_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            versions = sorted(v for v in plugin_dir.iterdir() if v.is_dir())
            if not versions:
                _inv(conn, "plugin", plugin_dir.name, "plugin",
                     path=plugin_dir, owner=marketplace_dir.name)
                rows += 1
                continue
            latest = versions[-1]
            meta = _plugin_meta(latest)
            _inv(conn, "plugin", plugin_dir.name, "plugin", path=latest,
                 owner=marketplace_dir.name, version=meta.get("version") or latest.name)
            rows += 1
    return rows


def _plugin_meta(version_dir: Path) -> dict:
    for rel in (".trae-plugin/plugin.json", "package.json"):
        path = version_dir / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return {}


def _scan_mcps(conn) -> int:
    root = db.TRAE_CN_HOME / "mcps"
    if not root.is_dir():
        return 0
    rows = 0
    for meta_path in sorted(root.rglob("SERVER_METADATA.json")):
        server_dir = meta_path.parent
        name = server_dir.name
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("server_name"):
                name = data["server_name"]
        except (OSError, ValueError):
            db.note_unparsed(conn, "mcp:bad_metadata", 1)
        scope = server_dir.parent.name
        _inv(conn, "mcp", name, "plugin", path=server_dir, owner=scope)
        rows += 1
    return rows


# --- 7. credit balance observations (Trae's own renderer log) ---------------
#
# Trae writes its credit balance to the log roughly once per app start. It is the
# only consumption-derived number on this machine, so it is worth indexing — but it
# is a *level*, sampled sparsely, and grants raise it between samples. Only the
# number, its timestamp and its generation are stored; the log line around it is
# Trae's prose and is dropped.

USAGE_TAG = "[ICubeUsageService]"

_LOG_HEAD_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(?:(Z)|([+-])(\d{2}):(\d{2}))?")

_BALANCE_RE = re.compile(
    r'"generation"\s*:\s*(-?\d+)\s*,\s*"remaining"\s*:\s*(-?\d+(?:\.\d+)?)')


def logs_root() -> Path:
    return db.TRAE_CN_DATA / "logs"


def _iter_credit_logs(root):
    """The window renderer logs and the main log, oldest session dir first.

    The balance line was observed in `logs/<session>/window*/renderer.log`;
    `main.log` is included because it is where Trae logs the same service's other
    events. Nothing else is walked: the rest of the log tree is unrelated prose at
    megabyte scale.
    """
    if not root.is_dir():
        return []
    found = []
    for session_dir in sorted(root.iterdir()):
        if not session_dir.is_dir():
            continue
        found.extend(sorted(session_dir.glob("window*/renderer.log")))
        main = session_dir / "main.log"
        if main.is_file():
            found.append(main)
    return [p for p in found if p.is_file()]


def _log_ts_ms(text) -> int | None:
    """Epoch ms for a leading `2026-10-07T08:55:51.467+08:00` stamp.

    `Z` means UTC and an explicit offset is honoured exactly. A stamp with neither
    is read as *local* time, because that is how Trae writes the ones we have
    measured; there is no way to recover an intent that was never written.
    """
    m = _LOG_HEAD_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute, second, frac, zulu, sign, off_h, off_m = m.groups()
    try:
        naive = datetime(int(year), int(month), int(day),
                         int(hour), int(minute), int(second),
                         int((frac + "000000")[:6]) if frac else 0)
    except ValueError:
        return None
    if zulu:
        naive = naive.replace(tzinfo=timezone.utc)
    elif sign and off_h is not None:
        delta = timedelta(hours=int(off_h), minutes=int(off_m))
        naive = naive.replace(tzinfo=timezone(-delta if sign == "-" else delta))
    return int(naive.timestamp() * 1000)


def scan_credit_logs(conn, cfg, root=None) -> int:
    root = root or logs_root()
    rows = 0
    for path in _iter_credit_logs(root):
        changed = _changed(conn, path)
        if changed is None:
            continue
        size, mtime, offset = changed
        if offset > size:                     # rotated or truncated: re-read
            offset = 0
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                blob = fh.read()
        except OSError:
            db.note_unparsed(conn, "credit_log:read_failed", 1)
            continue
        parts = blob.split(b"\n")
        tail = parts.pop()                    # keep an unfinished line for next run
        consumed = len(blob) - len(tail)
        for raw in parts:
            if not raw.strip():
                continue
            rows += _ingest_credit_line(conn, str(path),
                                        raw.decode("utf-8", "replace"))
        _set_cursor(conn, str(path), size, mtime, offset + consumed)
    return rows


def _ingest_credit_line(conn, source, text) -> int:
    if USAGE_TAG not in text:
        return 0
    ts = _log_ts_ms(text)
    if ts is None:
        db.note_unparsed(conn, "credit_log:bad_timestamp", 1)
        return 0
    m = _BALANCE_RE.search(text)
    if m:
        conn.execute(
            "INSERT OR REPLACE INTO credit_events(source, ts, kind, remaining,"
            " generation) VALUES(?,?,'balance',?,?)",
            (source, ts, float(m.group(2)), int(m.group(1))))
        return 1
    if "skipped" in text:
        conn.execute(
            "INSERT OR REPLACE INTO credit_events(source, ts, kind, remaining,"
            " generation) VALUES(?,?,'skipped',NULL,NULL)",
            (source, ts))
        return 1
    # A tagged line we cannot classify: the service changed what it writes, which
    # is exactly the kind of change that must not pass silently.
    db.note_unparsed(conn, "credit_log:event_shape", 1)
    return 0


# --- finalize --------------------------------------------------------------


def finalize(conn) -> None:
    """Resolve real project paths, then recompute per-session counts and
    best-known timestamps from the tags, and stamp the *derived* creation second
    into its own column for whatever the tags left undated."""
    _resolve_projects(conn)
    conn.execute(
        "UPDATE sessions SET"
        " turns = (SELECT COUNT(*) FROM turns t WHERE t.session_id = sessions.session_id),"
        " toolcalls = (SELECT COUNT(*) FROM toolcall_events e"
        "              WHERE e.session_id = sessions.session_id),"
        " first_ts = COALESCE("
        "   (SELECT MIN(ts) FROM ("
        "      SELECT ts FROM turns WHERE session_id = sessions.session_id"
        "      UNION ALL"
        "      SELECT ts FROM toolcall_events WHERE session_id = sessions.session_id)),"
        "   first_ts),"
        " last_ts = COALESCE("
        "   (SELECT MAX(ts) FROM ("
        "      SELECT ts FROM turns WHERE session_id = sessions.session_id"
        "      UNION ALL"
        "      SELECT ts FROM toolcall_events WHERE session_id = sessions.session_id)),"
        "   last_ts)")
    db.stamp_created_ts(conn)
    # A model selection carries its id and nothing else on disk; decoding it needs
    # the catalog *and* the sessions, so it belongs here rather than in one scanner.
    # Both steps are idempotent and cheap, and both must run after every source has
    # landed — a selection indexed today can refer to a model added to the catalog
    # in the same pass.
    db.decode_session_models(conn)
    db.allocate_credits(conn)
    conn.commit()


# --- driver ----------------------------------------------------------------

def _purge_content(conn) -> None:
    """Drop every prose column and table when ``store_content`` is off.

    The handlers already skip storing *new* prose, but a database written while
    the switch was on would keep it — and a settings switch that only affects
    future indexing reads as "my content is still there". Turning it off has to
    mean the content is gone.
    """
    conn.execute("UPDATE sessions SET intent = NULL, outcome = NULL")
    conn.execute("UPDATE topics SET summary = NULL")
    conn.execute("DELETE FROM session_actions")
    conn.execute("DELETE FROM session_learned")
    conn.execute("DELETE FROM prompts")
    conn.execute("DELETE FROM memory")


HANDLERS = (
    ("session memory", scan_session_memory),
    ("topics", scan_topics),
    ("memory docs", scan_memory_docs),
    ("snapshots", scan_snapshots),
    ("state.vscdb", scan_state_vscdb),
    ("inventory", scan_inventory),
    ("credit logs", scan_credit_logs),
)


def run(db_path=None, full=False, quiet=False, roots=None) -> dict:
    """Index everything. Returns a small summary dict.

    ``roots`` overrides the source roots (used by tests): a dict with any of
    ``memory``, ``snapshot``, ``user``, ``home``.
    """
    cfg = db.load_config()
    path = Path(db_path or db.DB_PATH)
    conn = db.open_db(path)
    try:
        status = db.ensure_schema(conn)
        if status == "newer":
            raise SystemExit(
                f"tcut: {path} was written by a newer build; refusing to touch it")
        if full:
            # A snapshot of an empty database is clutter, and every test builds one;
            # only state that exists is worth a way back.
            if db._has_indexed_state(conn):
                db.snapshot(conn, reason="pre-full-rebuild", db_path=path)
            db.reset(conn)
        results = {}
        if roots:
            results["session memory"] = _run_root(
                scan_session_memory, conn, cfg, roots.get("memory_projects"))
            results["topics"] = _run_root(
                scan_topics, conn, cfg, roots.get("memory_projects"))
            results["memory docs"] = _run_root(
                scan_memory_docs, conn, cfg, roots.get("memory"))
            results["snapshots"] = _run_root(
                scan_snapshots, conn, cfg, roots.get("snapshot"))
            results["credit logs"] = _run_root(
                scan_credit_logs, conn, cfg, roots.get("logs"))
        else:
            for label, fn in HANDLERS:
                results[label] = fn(conn, cfg)
        if not cfg["store_content"]:
            _purge_content(conn)
        finalize(conn)
        summary = {"path": str(path), "schema": status, "results": results,
                   "overview": db.overview(conn)}
        if not quiet:
            _print_summary(summary)
        return summary
    finally:
        conn.close()


def _run_root(fn, conn, cfg, root):
    if root is None:
        return 0
    return fn(conn, cfg, Path(root))


def _print_summary(summary) -> None:
    print(f"tcut sync → {summary['path']}")
    for label, n in summary["results"].items():
        print(f"  {label:<14} {n}")
    o = summary["overview"]
    print(f"  sessions={o['sessions']} projects={o['projects']} "
          f"turns={o['turns']} toolcalls={o['toolcalls']} prompts={o['prompts']} "
          f"agents={o['agents']} skills={o['skills']} plugins={o['plugins']} "
          f"mcp={o['mcp']}")
    if o["unparsed_records"]:
        print(f"  unparsed={o['unparsed_records']} "
              f"({o['unparsed_kinds']} kinds) — see `tcut health`")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Index Trae CN data into the tracker DB.")
    ap.add_argument("--db", help="database path (default: TCUT_DB or ~/.local/share/...)")
    ap.add_argument("--full", action="store_true",
                    help="snapshot then rebuild the index from scratch")
    ap.add_argument("--quiet", action="store_true", help="no progress output")
    args = ap.parse_args(argv)
    run(db_path=args.db, full=args.full, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
