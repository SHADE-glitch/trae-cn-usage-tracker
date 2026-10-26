"""test_stats.py — the headless CLI, driven as a child process.

``tcut-stats.py`` is the part of this tool that runs without the TUI's venv, and it is also
the ``tcut`` default, so a break here is the first thing a user meets. It has a hyphen in its
name and its own ``argparse`` surface, so these cases run it the way a person does — as a
subprocess with a ``--db`` pointing at a throwaway database — rather than importing it.

Four properties:

1. **Every command runs and prints its shape.** A command that raises, or that prints an empty
   table instead of its headers, is worse than one that is missing.
2. **``--db`` works in both positions.** ``tcut --db X stats`` and ``tcut stats --db X`` are the
   same request; the second form used to silently fall back to the default database, so both
   are pinned.
3. **A read-only command never touches a database that is not there**, and says so instead of
   creating an empty one — creating it would make the next ``sync`` believe it had already run.
4. **``export`` is parseable JSON of the whole index**, since that is the machine-readable
   contract the human output is only a view of.
"""

import json
import importlib.util
import os
import re
import subprocess
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

STATS_PY = str(SCRIPTS / "tcut-stats.py")


def load_stats():
    """Import ``tcut-stats.py`` by path — a hyphenated name has no module name."""
    spec = importlib.util.spec_from_file_location("tcut_stats_for_tests", STATS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stats = load_stats()


def clean_env(**extra):
    """The ambient environment minus every TCUT_* switch, so output is input-determined.

    The host dirs are pinned to a path that does not exist, for the same reason: a CLI
    child left to its defaults would read the real ``~/.trae-cn`` / ``~/.config/Trae CN``,
    and the tripwire in ``_hermetic`` refuses that.
    """
    hidden = set(db.ENV_NAMES.values()) | {
        "TCUT_CONFIG", "TCUT_TRAE_CN_HOME", "TCUT_TRAE_CN_DATA"}
    base = {k: v for k, v in os.environ.items() if k not in hidden}
    absent = Path(tempfile.gettempdir()) / "tcut-no-such-host"
    base["TCUT_TRAE_CN_HOME"] = str(absent / "home")
    base["TCUT_TRAE_CN_DATA"] = str(absent / "data")
    base.update(extra)
    return base


class RenderingTest(unittest.TestCase):
    """The two pure functions behind every table — no subprocess, no database."""

    def test_none_renders_as_a_dash_not_the_word_none(self):
        self.assertEqual(stats._cell(None), "-")

    def test_a_newline_becomes_a_space_so_a_row_stays_one_line(self):
        self.assertEqual(stats._cell("a\nb"), "a b")

    def test_the_cap_truncates_with_an_ellipsis_and_keeps_the_width(self):
        out = stats._cell("abcdefghij", cap=5)
        self.assertEqual(len(out), 5, "the cap is a width, not a suggestion")
        self.assertTrue(out.endswith("…"), "a silently shortened value reads as the whole value")
        self.assertEqual(stats._cell("abc", cap=5), "abc", "a short value is untouched")

    def test_an_empty_result_says_what_to_do(self):
        self.assertIn("tcut sync", stats.table_or(("a",), []))

    def test_a_non_empty_result_is_a_header_rule_and_rows(self):
        out = stats.table_or(("a", "b"), [("1", "2")], )
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), ["a", "b"])
        self.assertRegex(lines[1], r"^-+(\s+-+)*$")
        self.assertEqual(lines[2].split(), ["1", "2"])

    def test_the_all_range_has_neither_bound_so_undated_rows_are_visible(self):
        """An upper bound of `now` silently drops every row with a NULL timestamp.

        25 of this machine's 49 sessions are exactly that, so "All time" was a range
        that showed them nowhere — the one view meant to be the escape hatch. Nothing
        tested `window_bounds` before, which is how it stayed a day-window helper
        with a half-written contract.
        """
        now = 1700000000000
        self.assertEqual(db.window_bounds("all", now), (None, None))
        start, end = db.window_bounds("7d", now)
        self.assertIsNotNone(start, "a bounded range must still bound both ends")
        self.assertEqual(end, now)

    def test_readonly_excludes_exactly_backup_and_restore(self):
        """The set drives whether a command opens the file writable; a mistake is a
        command that can change the database it was only asked to report on."""
        self.assertEqual(set(stats.COMMANDS) - stats.READONLY, {"backup", "restore"})


class LeaderboardQueryTest(unittest.TestCase):
    """The columns the Dashboard's leaderboards read, straight from the database.

    The panels drop zero-count rows, which is only honest while a zero is a measurement.
    `undated` is what separates "idle in this range" from "no time anywhere", and these
    cases hold the query side of that contract: the column, the ranking it buys, the
    fallback that places a derived row at all, and the prose form the dash renders in.
    """

    NOW = 1700002000000

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.conn = db.open_db(Path(self._tmp.name) / "usage.db")
        self.addCleanup(self.conn.close)
        db.ensure_schema(self.conn)
        # `-z` is the blind spot and sorts last by key; `-b` is a measured zero and sorts
        # before it. That ordering is deliberate: a fixture where the hidden row already
        # wins the tie by alphabet proves nothing about the tie-break.
        self.conn.executescript(
            "INSERT INTO sessions(session_id, project_key, project, agent, last_ts)"
            " VALUES('inwin000000000','-p--p2-a','/home/user/A','busy',1700001000000),"
            # No tag, no stampable id: the row every bounded range loses.
            "        ('ghost0000000000','-p--p2-z','/home/user/Z','hidden',NULL),"
            # Measured, and measured 400 days ago — a real zero for a 7d window.
            "        ('far0000000000000','-p--p2-b','/home/user/B','idle',"
            "         1700002000000 - 400 * 86400000);"
            " INSERT INTO agents(name, kind, description)"
            " VALUES('busy',NULL,NULL),('hidden',NULL,NULL),('idle',NULL,NULL)"
        )
        self.conn.commit()

    def bounds(self):
        return db.window_bounds("7d", self.NOW)

    def by_key(self, rows):
        return {r["project_key"]: r for r in rows}

    def test_a_project_reports_the_sessions_no_window_can_place(self):
        start, end = self.bounds()
        rows = self.by_key(db.q_projects(self.conn, start_ts=start, end_ts=end))
        self.assertEqual((rows["-p--p2-z"]["sessions"], rows["-p--p2-z"]["undated"]),
                         (0, 1), "an invisible project and an idle one came back identical")
        self.assertEqual(rows["-p--p2-b"]["undated"], 0,
                         "a dated-but-outside session was counted as having no time")
        self.assertEqual(rows["-p--p2-a"]["undated"], 0)

    def test_the_hidden_project_outranks_the_provably_idle_one(self):
        # Both are zeros in this window; only one of them is a blind spot, and a capped
        # leaderboard has to spend its last slot on the row it cannot explain.
        start, end = self.bounds()
        keys = [r["project_key"] for r in
                db.q_projects(self.conn, limit=2, start_ts=start, end_ts=end)]
        self.assertEqual(keys, ["-p--p2-a", "-p--p2-z"],
                         "the tie-break ignored `undated`, so the hidden row lost its slot")

    def test_a_row_placed_only_by_its_id_reaches_the_windowed_views(self):
        """`COALESCE(last_ts, created_ts)` is the only reason these rows are visible.

        Degrading it back to `last_ts` hides the session from the leaderboard, the KPI
        and the per-day series at once — while `tcut sessions` still lists it, because
        that query reads the pair itself. Three panels quietly losing a row nobody was
        told about is the failure this pins.
        """
        derived = ("%08x" % 1700001000) + "0000000000000000"
        self.conn.execute("INSERT INTO sessions(session_id, project_key, project, agent,"
                          " last_ts) VALUES(?, '-p--p2-d', '/home/user/D', 'derived', NULL)",
                          (derived,))
        self.conn.commit()
        # The other three ids are not hex, so this stamps exactly the new row.
        self.assertEqual(db.stamp_created_ts(self.conn), 1)
        self.conn.commit()

        start, end = self.bounds()
        rows = self.by_key(db.q_projects(self.conn, start_ts=start, end_ts=end))
        self.assertEqual((rows["-p--p2-d"]["sessions"], rows["-p--p2-d"]["undated"]),
                         (1, 0), "the derived session was neither counted nor admitted as"
                                 " unknown — it just was not there")
        kpi = db.q_kpi(self.conn, start, end)
        self.assertEqual(kpi["sessions"], 2, "the KPI lost the row the fallback placed")
        self.assertEqual(kpi["unmeasured"], 2,
                         "a derived row is still unmeasured, window or no window")
        self.assertEqual(sum(r["sessions"] for r in
                             db.q_activity_daily(self.conn, start, end)), 2,
                         "the per-day series dropped the row the KPI counted")

    def test_the_kpi_separates_an_unmeasured_row_from_an_uncharted_one(self):
        # `unmeasured` is the population the `~` marker belongs to: a session with no
        # measured time, whether or not its id places it. It is all-time by definition —
        # changing the range cannot turn a derivation into a measurement.
        start, end = self.bounds()
        self.assertEqual(db.q_kpi(self.conn, start, end)["unmeasured"], 1)
        self.assertEqual(db.q_kpi(self.conn)["unmeasured"], 1,
                         "the count moved with the window")

    def test_window_count_keeps_the_word_only_for_a_real_count(self):
        self.assertEqual(db.window_count(1, 0, "session"), "1 session")
        self.assertEqual(db.window_count(12, 0, "session"), "12 sessions")
        self.assertEqual(db.window_count(0, 0, "session"), "0 sessions")
        self.assertEqual(db.window_count(0, 3, "session"), "-",
                         "a dash is not a count, so it takes no unit")


class CliBase(unittest.TestCase):
    """A throwaway database with one of everything, and a child to run commands against it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db_path = self.dir / "usage.db"
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        conn.executescript(
            "INSERT INTO sessions(session_id, project_key, project, day, agent, intent,"
            " outcome, turns, toolcalls, first_ts, last_ts)"
            " VALUES('abc123def456','-p--p2-a','/home/user/P','20260304','builder',"
            " 'wire the timer','done',3,7,1700000000000,1700000600000);"
            " INSERT INTO session_actions(session_id, idx, text) VALUES('abc123def456',0,'did a thing');"
            " INSERT INTO session_learned(session_id, idx, text) VALUES('abc123def456',0,'learnt a thing');"
            " INSERT INTO topics(session_id, ts, project_key, summary)"
            " VALUES('abc123def456',1700000100000,'-p--p2-a','a topic');"
            " INSERT INTO prompts(workspace, idx, text) VALUES('ws1',0,'a prompt');"
            " INSERT INTO workspaces(workspace, folder) VALUES('ws1','/home/user/P');"
            " INSERT INTO agents(name, kind, description) VALUES('builder','custom','builds');"
            " INSERT INTO models(account, group_name, name, provider,"
            " consumption_rate, context_window) VALUES"
            " ('acct-A','builder','Model X','acme',0.39,184000),"
            " ('acct-A','solo_agent','Model X','acme',0.39,184000);"
            " INSERT INTO session_models(session_id, account, agent_label, model_id, mode)"
            " VALUES('abc123def456','acct-A','agent','agent_1__Model X_null',0);"
            " INSERT INTO credit_events(source, ts, kind, remaining, generation) VALUES"
            "  ('/x/logs/20261001T100000/window1/renderer.log',1700000000000,'balance',154.0244,0),"
            "  ('/x/logs/20261001T100000/window1/renderer.log',1700000100000,'balance',100,0),"
            "  ('/x/logs/20261002T100000/window1/renderer.log',1700000200000,'skipped',NULL,NULL);"
            " INSERT INTO inventory(kind, name, owner_plugin, version, path, source)"
            " VALUES('skill','my-skill','',NULL,'/x/my-skill','user');"
            " INSERT INTO memory(scope, idx, text) VALUES('user_profile',0,'likes tabs');"
        )
        conn.commit()
        # The real sync decodes and allocates at the end; `show` reads those
        # columns, so the fixture must reach the same state.
        db.decode_session_models(conn)
        db.allocate_credits(conn)
        conn.commit()
        conn.close()

    def run_cli(self, *args, env=None, expect_db=True):
        argv = [sys.executable, STATS_PY]
        if expect_db:
            argv += ["--db", str(self.db_path)]
        argv += [str(a) for a in args]
        proc = subprocess.run(argv, capture_output=True, text=True,
                              env=env if env is not None else clean_env())
        return proc.returncode, proc.stdout + proc.stderr


class CommandTest(CliBase):
    def test_stats_prints_the_overview(self):
        rc, out = self.run_cli("stats")
        self.assertEqual(rc, 0, out)
        self.assertIn("sessions   1", out)
        self.assertIn("projects 1", out)

    def test_sessions_lists_the_session(self):
        rc, out = self.run_cli("sessions")
        self.assertEqual(rc, 0, out)
        self.assertIn("abc123def456"[:12], out)
        self.assertIn("wire the timer", out)

    def test_projects_lists_the_real_folder(self):
        rc, out = self.run_cli("projects")
        self.assertEqual(rc, 0, out)
        self.assertIn("/home/user/P", out)

    def test_prompts_are_grouped_by_the_real_folder(self):
        rc, out = self.run_cli("prompts")
        self.assertEqual(rc, 0, out)
        self.assertIn("a prompt", out)
        self.assertIn("/home/user/P", out,
                      "the prompt was labelled with the workspace id, not its folder")

    def test_log_limit_caps_the_cli_now_that_the_prompts_tab_is_gone(self):
        """``log_limit`` still reaches the one CLI report that reads it.

        The Prompts tab was removed to keep the TUI on cbut's tab set, and with it
        went the four settings assertions that used to prove the value reached the
        app. The key is not dead — ``tcut prompts`` caps its rows with it — so this
        holds the CLI half, and shows ``--limit`` winning, which is the other half of
        ``args.limit or config["log_limit"]``. The TUI half is
        ``test_config.py::test_the_app_reads_its_limits_from_the_config`` (the Usage
        page's session log).
        """
        conn = db.open_db(self.db_path)
        conn.executemany(
            "INSERT INTO prompts(workspace, idx, text) VALUES('ws1',?,?)",
            [(i, f"prompt {i}") for i in range(1, 6)])
        conn.commit()
        conn.close()

        rc, out = self.run_cli("prompts", env=clean_env(TCUT_LOG_LIMIT="3"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(out.splitlines()), 5, out)   # header + rule + 3 rows
        for want in ("a prompt", "prompt 1", "prompt 2"):
            self.assertIn(want, out)
        self.assertNotIn("prompt 3", out, "TCUT_LOG_LIMIT did not cap the rows")

        rc, out = self.run_cli("prompts", "--limit", "5",
                               env=clean_env(TCUT_LOG_LIMIT="3"))
        self.assertEqual(rc, 0, out)
        self.assertIn("prompt 4", out, "--limit must override the configured cap")
        self.assertNotIn("prompt 5", out)

    def test_sessions_marks_a_time_that_came_from_the_id(self):
        """A derived position prints with `~`; a measured one prints bare.

        Without the mark, `tcut sessions` would show a creation second guessed from
        the id exactly like the activity time Trae wrote, and nobody downstream could
        tell which rows were measured.
        """
        sid = ("%08x" % 1700000500) + "0000000000000000"
        conn = db.open_db(self.db_path)
        conn.execute("INSERT INTO sessions(session_id, project_key, project, agent,"
                     " last_ts) VALUES(?,?,?,?,NULL)",
                     (sid[:24], "-p--p2-a", "/home/user/P", "olddot"))
        conn.commit()
        db.stamp_created_ts(conn)          # also dates the fixture's other unstamped row
        conn.commit()
        self.assertEqual(conn.execute(
            "SELECT created_ts FROM sessions WHERE session_id = ?",
            (sid[:24],)).fetchone()[0], 1700000500 * 1000)
        conn.close()

        rc, out = self.run_cli("sessions")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("~"), 1,
                         f"expected one derived time, marked, and one measured one, bare:\n{out}")
        self.assertIn("olddot", out)

    def test_agents_and_models(self):
        rc, out = self.run_cli("agents")
        self.assertEqual(rc, 0, out)
        self.assertIn("builder", out)
        rc, out = self.run_cli("models")
        self.assertEqual(rc, 0, out)
        self.assertIn("Model X", out)
        # Two catalog rows share the name and differ only by group. A listing that
        # keys on the name shows one of them and still looks like a full sync.
        self.assertEqual(out.count("Model X"), 2, "a catalog row was collapsed away")
        self.assertIn("acct-A", out)
        self.assertIn("0.39", out)

    def test_every_command_runs_and_prints_its_shape(self):
        """The sweep that `format`'s pre-sync failure should have been caught by.

        A command that exits non-zero, or prints an empty table instead of its
        headers, is worse than one that is missing — and per-command tests are the
        ones that forget to exist when a command is added. `backup`/`restore` are
        excluded: they write, and their own cases cover them.
        """
        for cmd in sorted(set(stats.COMMANDS) - {"backup", "restore", "show"}):
            with self.subTest(cmd=cmd):
                rc, out = self.run_cli(cmd)
                self.assertEqual(rc, 0, out)
                self.assertTrue(out.strip(), f"`tcut {cmd}` printed nothing")
        rc, out = self.run_cli("show", "abc123def456")
        self.assertEqual(rc, 0, out)
        self.assertIn("session abc123def456", out)

    def test_skills_plugins_mcp_and_inventory(self):
        for cmd in ("skills", "plugins", "mcp", "inventory"):
            with self.subTest(cmd=cmd):
                rc, out = self.run_cli(cmd)
                self.assertEqual(rc, 0, out)
        rc, out = self.run_cli("skills")
        self.assertIn("my-skill", out)

    def test_memory_lists_paragraphs(self):
        rc, out = self.run_cli("memory")
        self.assertEqual(rc, 0, out)
        self.assertIn("likes tabs", out)

    def test_show_prints_one_session_and_its_lists(self):
        rc, out = self.run_cli("show", "abc123def456")
        self.assertEqual(rc, 0, out)
        self.assertIn("did a thing", out)
        self.assertIn("learnt a thing", out)
        self.assertIn("a topic", out)

    def test_the_model_rides_the_session_row_and_the_detail(self):
        rc, out = self.run_cli("sessions")
        self.assertEqual(rc, 0, out)
        self.assertIn("agent_1__Model X_null", out)
        rc, out = self.run_cli("show", "abc123def456")
        self.assertEqual(rc, 0, out)
        self.assertIn("model     agent: Model X · Built-in", out)
        self.assertIn("raw id    agent: agent_1__Model X_null", out)
        self.assertIn("tokens    not recorded", out)

    def test_credits_lists_the_series_and_names_the_bound(self):
        rc, out = self.run_cli("credits")
        self.assertEqual(rc, 0, out)
        self.assertIn("spent >=", out)
        self.assertIn("154.0244", out, "the older balance is the one that fell")
        self.assertIn("54.0244", out, "the fall between two balances is not derived")
        self.assertIn("lower bound", out)
        self.assertIn("no token counts", out)
        self.assertIn("2 observations", out)
        self.assertIn("1 fetch skipped", out, "a count of one must not read as plural")
        rows = [line for line in out.splitlines() if re.match(r"\d{4}-\d{2}-\d{2}", line)]
        self.assertEqual(len(rows), 2,
                         "the numberless skipped event joined the balance series")

    def test_credits_says_so_when_there_are_no_observations(self):
        empty = self.dir / "no-credits.db"
        conn = db.open_db(empty)
        db.ensure_schema(conn)
        conn.close()
        rc, out = self.run_cli("--db", str(empty), "credits", expect_db=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("no credit balance observations", out)

    def test_show_unknown_session_fails_with_a_message(self):
        rc, out = self.run_cli("show", "nope")
        self.assertEqual(rc, 1)
        self.assertIn("no such session", out)

    def test_recent_and_export(self):
        rc, out = self.run_cli("recent")
        self.assertEqual(rc, 0, out)
        rc, out = self.run_cli("export")
        self.assertEqual(rc, 0, out)
        data = json.loads(out)
        self.assertEqual(data["overview"]["sessions"], 1)
        self.assertEqual(len(data["sessions"]), 1)
        self.assertIn("inventory", data)

    def test_format_prints_the_format_surface(self):
        rc, out = self.run_cli("format")
        # A guard that accepts rc 0 or 1 cannot fail, so it cannot catch a `format`
        # that stopped printing the surface. Name the markers it must contain.
        self.assertEqual(rc, 0, out)
        self.assertIn("state.vscdb", out)
        self.assertIn("unparsed", out)

    def test_format_needs_no_database(self):
        """`format` explains the sources; requiring an index made it unusable pre-sync."""
        missing = self.dir / "never-synced.db"
        self.assertFalse(missing.exists())
        rc, out = self.run_cli("--db", str(missing), "format", expect_db=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("state.vscdb", out)
        self.assertFalse(missing.exists(), "`format` created the database it should not need")


    def test_export_carries_every_table_the_schema_has(self):
        """``export`` is the machine-readable contract for the whole index, so the check
        counts tables instead of sampling them.

        Eight hand-picked query sections used to be all of it: `turns`, `toolcall_events`,
        `topics`, `session_actions`, `session_learned`, `session_models`, `workspaces`,
        `sync_state`, `unparsed` and `meta` were indexed and exported by nobody, so reading
        coverage meant opening the database by hand. Enumerating `sqlite_master` also fails
        the day a migration adds a table the export never heard of — a hand-kept list is
        incapable of failing that way, which is exactly how the claim went unexamined.
        """
        rc, out = self.run_cli("export")
        self.assertEqual(rc, 0, out)
        data = json.loads(out)
        conn = db.open_db(self.db_path, readonly=True)
        try:
            tables = db.table_names(conn)
        finally:
            conn.close()
        self.assertGreater(len(tables), 10,
                           f"the enumerator returned {tables} — that is not the schema")
        self.assertEqual(set(data) - {"overview"}, set(tables),
                         "export is not the index: a table is missing, or a section names "
                         "something the schema does not have")

    def test_export_dumps_rows_verbatim_and_no_query_time_derivation(self):
        """Keys are not the promise — the rows are, and neither may be a derivation.

        `spent_at_least`, the windowed counts and the `~` marker are readings over these
        rows; a JSON section that ships one beside the stored columns teaches every
        future consumer to read it as measured data.
        """
        rc, out = self.run_cli("export")
        self.assertEqual(rc, 0, out)
        data = json.loads(out)
        self.assertEqual([s["session_id"] for s in data["sessions"]], ["abc123def456"])
        self.assertEqual(len(data["credit_events"]), 3, "a table exported as an empty list")
        self.assertEqual(len(data["models"]), 2)
        self.assertEqual(data["unparsed"], [],
                         "the coverage table was skipped, not empty")
        self.assertNotIn("spent_at_least", data["credit_events"][0])
        self.assertNotIn("undated", data["agents"][0])
        self.assertEqual(data["meta"] and all("key" in m for m in data["meta"]), True,
                         "the schema version is the one thing a consumer must be able to see")


class NoDefaultSubcommandTest(CliBase):
    def test_bare_invocation_is_stats(self):
        """No subcommand must not be a usage error: it is the common case."""
        proc = subprocess.run(
            [sys.executable, STATS_PY, "--db", str(self.db_path)],
            capture_output=True, text=True, env=clean_env())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("sessions", proc.stdout + proc.stderr)


class DbFlagPlacementTest(CliBase):
    def test_db_before_the_subcommand(self):
        proc = subprocess.run(
            [sys.executable, STATS_PY, "--db", str(self.db_path), "health"],
            capture_output=True, text=True, env=clean_env())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(str(self.db_path), proc.stdout,
                      "a --db before the subcommand was dropped")

    def test_db_after_the_subcommand(self):
        proc = subprocess.run(
            [sys.executable, STATS_PY, "health", "--db", str(self.db_path)],
            capture_output=True, text=True, env=clean_env())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(str(self.db_path), proc.stdout)


class ReadonlyMissingDbTest(CliBase):
    def test_a_read_command_refuses_to_run_without_a_database(self):
        """It must not create an empty one — that would mask a missing sync."""
        missing = self.dir / "absent" / "usage.db"
        proc = subprocess.run(
            [sys.executable, STATS_PY, "--db", str(missing), "stats"],
            capture_output=True, text=True, env=clean_env())
        self.assertEqual(proc.returncode, 1)
        self.assertIn("tcut sync", proc.stdout + proc.stderr)
        self.assertFalse(missing.exists(), "a read-only command created the database")


class HealthTest(CliBase):
    def test_health_names_the_sources_and_the_database(self):
        rc, out = self.run_cli("health")
        self.assertEqual(rc, 0, out)
        self.assertIn(str(self.db_path), out)
        self.assertIn("sources", out)
        self.assertIn("unparsed   none", out)

    def test_health_says_the_index_was_written_by_an_older_parser(self):
        """A green report over rows the old reader wrote is the failure mode.

        ``unparsed`` is empty in exactly that case — the rows were read, just
        wrongly — so the parser generation is the only thing that can say the
        index predates a repair. The next ``sync` re-reads and clears it.
        """
        conn = db.open_db(self.db_path)
        db.meta_set(conn, "parser_version", "1")
        conn.commit()
        conn.close()
        rc, out = self.run_cli("health")
        self.assertEqual(rc, 0, out)
        self.assertIn("stale index", out)
        self.assertIn("tcut sync", out)

    def test_health_does_not_call_a_current_index_stale(self):
        conn = db.open_db(self.db_path)
        db.meta_set(conn, "parser_version", str(db.load_sync().PARSER_VERSION))
        conn.commit()
        conn.close()
        rc, out = self.run_cli("health")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("stale index", out)

    def test_health_counts_unparsed_records_when_there_are_any(self):
        conn = db.open_db(self.db_path)
        db.note_unparsed(conn, "session_memory:not_json", 4)
        conn.commit()
        conn.close()
        rc, out = self.run_cli("health")
        self.assertEqual(rc, 0, out)
        self.assertIn("session_memory:not_json", out)
        self.assertIn("4", out)


if __name__ == "__main__":
    unittest.main()
