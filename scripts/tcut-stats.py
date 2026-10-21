"""tcut-stats — headless reports for the Trae CN usage tracker.

Every command prints plain text (or JSON for ``export``) and needs only the
standard library, so it works without the TUI's venv. This is the ``tcut``
default when the first argument is not ``tui`` or ``sync``.

    tcut stats | sessions | projects | prompts | agents | skills | plugins
         | mcp | memory | models | show | recent | inventory | export | health
         | backup | restore | format

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tcut_db as db  # noqa: E402


# --- rendering -------------------------------------------------------------


def _cell(value, cap=None) -> str:
    if value is None:
        return "-"
    text = str(value).replace("\n", " ")
    if cap and len(text) > cap:
        return text[: cap - 1] + "…"
    return text


def table(headers, rows, cap=None) -> str:
    """A fixed-width text table. Rows may be sqlite3.Row or tuples."""
    cap = cap or db.load_config()["name_cap"]
    body = [[_cell(v, cap) for v in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in body:
        for i, v in enumerate(row):
            widths[i] = max(widths[i], len(v))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    out.append("  ".join("-" * w for w in widths))
    for row in body:
        out.append("  ".join(v.ljust(widths[i]) for i, v in enumerate(row)).rstrip())
    return "\n".join(out)


def table_or(headers, rows, empty="(nothing indexed — run `tcut sync`)") -> str:
    rows = list(rows)
    if not rows:
        return empty
    return table(headers, rows)


def _ms(value, mark="") -> str:
    """A timestamp as text, with ``~`` in front when its position was derived.

    Only per-session times can carry the mark: an aggregate like a project's
    ``last_seen`` mixes measured and derived rows, and no prefix would describe it.
    """
    if not value:
        return "-"
    from datetime import datetime
    return mark + datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M")


# --- commands --------------------------------------------------------------


def cmd_stats(conn, args):
    o = db.overview(conn)
    print("Trae CN usage tracker")
    print(f"  sessions   {o['sessions']}   projects {o['projects']}   "
          f"turns {o['turns']}   toolcalls {o['toolcalls']}")
    print(f"  prompts    {o['prompts']}   agents {o['agents']}   models {o['models']}")
    print(f"  installed  skills {o['skills']}   plugins {o['plugins']}   mcp {o['mcp']}")
    print(f"  models     {o['models']}   credit balance observations {o['credits']}")
    if o["first_ts"] or o["last_ts"]:
        print(f"  span       {_ms(o['first_ts'])} → {_ms(o['last_ts'])}")
    if o["unparsed_records"]:
        print(f"  unparsed   {o['unparsed_records']} records "
              f"({o['unparsed_kinds']} kinds) — see `tcut health`")
    return 0


def cmd_sessions(conn, args):
    rows = db.q_sessions(conn, limit=args.limit or 30)
    print(table_or(
        ("when", "session", "project", "agent", "model", "turns", "tools", "intent"),
        [(_ms(r["shown_ts"], db.derived_mark(r["derived_ts"])), r["session_id"][:12],
          r["project_key"] or "-",
          r["agent"] or "-", r["model_id"] or "-", r["turns"], r["toolcalls"],
          r["intent"])
         for r in rows]))


def cmd_recent(conn, args):
    rows = db.q_recent(conn, limit=args.limit or 30)
    print(table_or(
        ("when", "session", "project", "agent", "turns", "tools"),
        [(_ms(r["last_ts"], db.derived_mark(r["derived_ts"])), r["session_id"][:12],
          r["project_key"] or "-",
          r["agent"] or "-", r["turns"], r["toolcalls"]) for r in rows]))


def cmd_projects(conn, args):
    rows = db.q_projects(conn, limit=args.limit)
    print(table_or(
        ("project", "sessions", "first seen", "last seen"),
        [(_cell(r["project"] or r["project_key"]), r["sessions"],
          _ms(r["first_seen"]), _ms(r["last_seen"])) for r in rows]))


def cmd_prompts(conn, args):
    rows = db.q_prompts(conn, limit=args.limit or db.load_config()["log_limit"])
    print(table_or(
        ("project", "#", "prompt"),
        [(_cell(r["folder"] or r["workspace"]), r["idx"], r["text"])
         for r in rows]))


def cmd_agents(conn, args):
    rows = db.q_agents(conn, limit=args.limit)
    print(table_or(
        ("agent", "kind", "sessions"),
        [(r["agent"], r["kind"] or "-", r["sessions"]) for r in rows]))


def cmd_models(conn, args):
    rows = db.q_models(conn, limit=args.limit)
    # One row per (account, group, name): the same model name is offered under
    # several groups and accounts, and collapsing it by name is what lost 242 of
    # 284 catalog entries in the first release.
    print(table_or(
        ("model", "group", "account", "provider", "rate", "ctx"),
        [(r["name"], r["group_name"] or "-", r["account"] or "-",
          r["provider"] or "-",
          "-" if r["consumption_rate"] is None else f"{r['consumption_rate']:g}",
          "-" if r["context_window"] is None else f"{r['context_window']:,}")
         for r in rows],
        empty="(no models indexed — run `tcut sync`)"))


def cmd_credits(conn, args):
    rows = db.q_credits(conn, limit=args.limit)
    skipped = len(db.q_credit_events(conn, "skipped"))
    print(table_or(
        ("when", "balance", "spent >=", "generation", "log"),
        [(_ms(r["ts"]), db.credit_num(r["remaining"]), db.credit_num(r["spent_at_least"]),
          r["generation"], db.credit_log_label(r["source"]))
         for r in rows],
        empty="(no credit balance observations — Trae writes one at app start)"))
    if not rows:
        return 0
    total = sum(r["spent_at_least"] or 0 for r in rows)

    line = (f"\n{db.count_n(len(rows), 'observation')} -"
            f" latest {db.credit_num(rows[0]['remaining'])} -"
            f" at least {db.credit_num(total)} credits spent")
    if skipped:
        line += f" - {db.count_n(skipped, 'fetch', 'fetches')} skipped"
    print(line)
    print("Balance is a level sampled at app start, and grants raise it between samples:")
    print("'spent >=' is a lower bound, never a measurement. Trae CN writes no token counts")
    print("on this machine (see `tcut format`).")
    return 0


def _inventory_cmd(kind):
    def run(conn, args):
        rows = db.q_inventory(conn, kind)
        print(table_or(
            ("name", "source", "owner", "version", "path"),
            [(r["name"], r["source"], r["owner_plugin"] or "-", r["version"] or "-",
              r["path"]) for r in rows],
            empty=f"(no {kind} indexed — run `tcut sync`)"))
        return 0
    return run


def cmd_memory(conn, args):
    rows = db.q_memory(conn, limit=args.limit)
    print(table_or(
        ("scope", "#", "paragraph"),
        [(r["scope"], r["idx"], r["text"]) for r in rows],
        empty="(no memory indexed — run `tcut sync`)"))


def cmd_show(conn, args):
    row = db.q_session(conn, args.session_id)
    if row is None:
        print(f"no such session: {args.session_id}", file=sys.stderr)
        return 1
    print(f"session {row['session_id']}")
    print(f"  project   {row['project'] or row['project_key'] or '-'}")
    print(f"  agent     {row['agent'] or '-'}")
    # One line per agent label: a session can carry an `agent` and a `solo_agent`
    # selection at the same time.
    selections = db.q_session_models(conn, args.session_id)
    credits = {(c["agent_label"], c["model_id"]): c["credits"]
               for c in db.q_session_credits(conn, args.session_id)}
    for m in selections:
        name = m["model"] or m["model_id"] or "-"
        route = db.route_label(m["provider"], m["third_party"])
        print(f"  model     {m['agent_label']}: {name} · {route}")
        # The raw id is kept: it is what Trae wrote, and a decode can be wrong in a
        # way the reader can only see by comparing the two lines.
        print(f"  raw id    {m['agent_label']}: {m['model_id']}")
        share = credits.get((m["agent_label"], m["model_id"]))
        print("  credits   "
              f"{m['agent_label']}: "
              f"{db.credit_num(share) if share is not None else '-'} est.")
    if not selections:
        print("  model     -")
    # One line that says the absence out loud, so `tcut show` never looks like it
    # merely forgot to print token counts.
    print("  tokens    not recorded (Trae writes none, 3P included)")
    print(f"  day       {row['day'] or '-'}")
    print(f"  turns     {row['turns']}   toolcalls {row['toolcalls']}")
    print(f"  span      {_ms(row['first_ts'])} → {_ms(row['last_ts'])}")
    if row["intent"]:
        print(f"  intent    {row['intent']}")
    if row["outcome"]:
        print(f"  outcome   {row['outcome']}")
    actions = db.q_session_actions(conn, args.session_id)
    if actions:
        print("  actions:")
        for a in actions:
            print(f"    - {_cell(a['text'], 100)}")
    learned = db.q_session_learned(conn, args.session_id)
    if learned:
        print("  learned:")
        for a in learned:
            print(f"    - {_cell(a['text'], 100)}")
    topics = db.q_topics(conn, args.session_id)
    if topics:
        print("  topics:")
        for t in topics:
            print(f"    {_ms(t['ts'])}  {_cell(t['summary'], 100)}")
    return 0


def cmd_inventory(conn, args):
    rows = db.q_inventory(conn, args.kind)
    print(table_or(
        ("kind", "name", "source", "owner", "version"),
        [(r["kind"], r["name"], r["source"], r["owner_plugin"] or "-",
          r["version"] or "-") for r in rows]))


def cmd_export(conn, args):
    """The whole index as JSON: the derived overview, then **every** table verbatim.

    No window, no rollup, no derived column. `spent >=`, the windowed counts and the `~`
    marker are query-time readings over these rows, and a machine-readable contract that
    ships a derivation next to the stored value is how the derivation gets read as data.
    The table list comes from the schema itself (`db.table_names`), so a table added by a
    future migration is exported by the next run without anyone remembering to edit a list.
    """
    out = {"overview": db.overview(conn)}
    for table in db.table_names(conn):
        out[table] = [dict(r) for r in
                      conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_health(conn, args):
    o = db.overview(conn)
    path = db.db_file(conn)
    print(f"database   {path}")
    print(f"schema     {db.stored_version(conn)} (expected {db.SCHEMA_VERSION})")
    # The settings surface, named so it can be found without reading the README.
    # A broken file is reported as one, in place, rather than being quietly skipped.
    # Every key the loader knows, spelled the way the settings file spells it — a
    # hand-listed line here goes stale one key at a time.
    try:
        cfg = db.load_config()
        state = "" if db.CONFIG_PATH.is_file() else " (absent — defaults)"
        values = " ".join(f"{k}={v}{'s' if k.endswith('_secs') else ''}"
                          for k, v in sorted(cfg.items()))
        print(f"settings   {db.CONFIG_PATH}{state} — {values}")
    except db.ConfigError as exc:
        print(f"settings   NOT READ — {exc}")
    print(f"sessions   {o['sessions']}   projects {o['projects']}")
    print(f"prompts    {o['prompts']}   agents {o['agents']}   models {o['models']}")
    print(f"installed  skills {o['skills']}   plugins {o['plugins']}   mcp {o['mcp']}")
    print(f"credits    {o['credits']} balance observations from "
          f"{db.TRAE_CN_DATA / 'logs'} ({'ok' if (db.TRAE_CN_DATA / 'logs').is_dir() else 'missing'})")
    unparsed = db.q_unparsed(conn)
    if unparsed:
        print("unparsed records (the source format may have moved):")
        for r in unparsed:
            print(f"  {r['count']:>8}  {r['reason']}")
    else:
        print("unparsed   none")
    print(f"sources    trae home {db.TRAE_CN_HOME} ({'ok' if db.TRAE_CN_HOME.is_dir() else 'missing'})")
    print(f"           trae data {db.TRAE_CN_DATA} ({'ok' if db.TRAE_CN_DATA.is_dir() else 'missing'})")
    return 0


def cmd_backup(conn, args):
    dest = db.snapshot(conn, reason=args.reason or "manual", db_path=db.db_file(conn))
    print(f"snapshot written: {dest}")
    return 0


def cmd_restore(conn, args):
    backups = db.list_backups(db.db_file(conn))
    if not args.name:
        if not backups:
            print("no snapshots to restore")
            return 0
        print("snapshots (newest first):")
        for b in backups:
            print(f"  {b.name}")
        print("\nrestore one with: tcut restore NAME")
        return 0
    match = next((b for b in backups if b.name == args.name), None)
    if match is None:
        print(f"no such snapshot: {args.name}", file=sys.stderr)
        return 1
    db.restore(match, db_path=db.db_file(conn))
    print(f"restored from {match}")
    return 0


FORMAT_BEGIN = "<!-- BEGIN generated: tcut format -->"
FORMAT_END = "<!-- END generated -->"


def _replace_generated_block(doc: Path, body: str) -> bool:
    """Rewrite the marked block in ``doc``; False when the markers are gone.

    Refusing beats appending: a generated section dropped into hand-written prose
    is how a document ends up stating two things at once.
    """
    text = doc.read_text(encoding="utf-8") if doc.is_file() else ""
    if FORMAT_BEGIN not in text or FORMAT_END not in text:
        return False
    head, _, rest = text.partition(FORMAT_BEGIN + "\n")
    _, tail = rest.split(FORMAT_END, 1)
    doc.write_text(f"{head}{FORMAT_BEGIN}\n{body}{FORMAT_END}{tail}",
                   encoding="utf-8")
    return True


def cmd_format(conn, args):
    """Print or refresh the Trae CN format-dependency surface.

    Generated from the parser's registry instead of written by hand, because a
    hand-copied list is how ``schema_version`` became a value nothing read: a
    description that stopped matching the code and stayed checked in anyway.
    """
    body = db.load_sync().format_doc()
    if not getattr(args, "write", False):
        print(body, end="")
        return 0
    doc = (Path(__file__).resolve().parent.parent
           / "docs" / "maintenance" / "trae-cn-format.md")
    if not _replace_generated_block(doc, body):
        print(f"{doc} has no generated block markers — refusing to rewrite it",
              file=sys.stderr)
        return 1
    print(f"updated   {doc}")
    return 0


COMMANDS = {
    "stats": cmd_stats,
    "sessions": cmd_sessions,
    "recent": cmd_recent,
    "projects": cmd_projects,
    "prompts": cmd_prompts,
    "agents": cmd_agents,
    "models": cmd_models,
    "credits": cmd_credits,
    "skills": _inventory_cmd("skill"),
    "plugins": _inventory_cmd("plugin"),
    "mcp": _inventory_cmd("mcp"),
    "memory": cmd_memory,
    "show": cmd_show,
    "inventory": cmd_inventory,
    "export": cmd_export,
    "health": cmd_health,
    "backup": cmd_backup,
    "restore": cmd_restore,
    "format": cmd_format,
}

# Commands that only read: they open the DB read-only, so they work while the
# TUI (or another process) holds it, and can never mutate it by accident.
READONLY = set(COMMANDS) - {"backup", "restore"}

# Commands that print repository content rather than index content. They must not
# require a database: `format` used to fail before the first `tcut sync`, which is
# exactly when someone reaches for it to find out why sync has nothing to say.
NO_DB = {"format"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="tcut", description="Trae CN usage tracker — headless reports.")
    ap.add_argument("--db", help="database path (default: TCUT_DB or ~/.local/share/...)")
    sub = ap.add_subparsers(dest="command")
    for name in COMMANDS:
        p = sub.add_parser(name, help=COMMANDS[name].__doc__ or "")
        # SUPPRESS, not a None default: ``--db`` is accepted both before and after the
        # subcommand, and a plain default here would overwrite the top-level value with
        # None whenever the flag came first (``tcut --db X health``).
        p.add_argument("--db", default=argparse.SUPPRESS)
        if name in ("sessions", "recent", "projects", "prompts", "agents",
                    "models", "credits", "memory"):
            p.add_argument("--limit", type=int, default=None)
        if name == "show":
            p.add_argument("session_id")
        if name == "inventory":
            p.add_argument("--kind", default=None)
        if name == "backup":
            p.add_argument("--reason", default=None)
        if name == "restore":
            p.add_argument("name", nargs="?", default=None)
        if name == "format":
            p.add_argument("--write", action="store_true",
                           help="refresh the generated block in docs/maintenance/")
    args = ap.parse_args(argv)

    command = args.command or "stats"
    if args.command is None:
        args = argparse.Namespace(command="stats", db=args.db)

    fn = COMMANDS[command]
    if command in NO_DB:
        return fn(None, args) or 0
    path = Path(getattr(args, "db", None) or db.DB_PATH)
    readonly = command in READONLY
    if readonly and not path.exists():
        print(f"no database at {path} — run `tcut sync` first", file=sys.stderr)
        return 1
    conn = db.open_db(path, readonly=readonly)
    try:
        return fn(conn, args) or 0
    except sqlite3.Error as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
