"""test_tui.py — the interface, driven headlessly through Textual's own test harness.

``app.run_test()`` runs the real app against a real (throwaway) database in a simulated
terminal, which is the only way to assert the things the interface actually promises: that
the five tabs exist in the order the docs list, that each renders its own columns, that the
range selector is visible on exactly the windowed tabs, and that Enter on a session opens its
detail screen and Escape comes back.

These cases do not assert colours or pixel layout — that is a moving target and a snapshot of
it ages badly. They assert structure and behaviour: which tabs, which columns, which rows,
which keys do what.

The app opens its database through the path it is handed, so every case points it at a
temp file; ``_hermetic`` refuses the real ``usage.db`` if one ever forgets.
"""

import asyncio
import importlib.util
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
sys.path.insert(0, str(TESTS))
import _hermetic  # noqa: E402,F401 -- tripwire: the suite must never open the real database
sys.path.insert(0, str(SCRIPTS))

ROOT = SCRIPTS.parent
TUI_PY = SCRIPTS / "tcut-tui.py"


def load_tui():
    spec = importlib.util.spec_from_file_location("tcut_tui_for_tests", TUI_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tui = load_tui()

# textual is a real dependency of the interface; if it is missing the whole
# deliverable is, so skip loudly rather than error with an ImportError wall.
try:
    from textual.widgets import DataTable, Select, TabbedContent, TabPane, Static
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"textual is not installed: {exc}")


def run(coro):
    return asyncio.run(coro)


class TuiBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db_path = self.dir / "usage.db"
        self._seed()

    def _seed(self):
        """A small but complete index: two sessions, a project, a prompt, inventory."""
        import tcut_db as db
        conn = db.open_db(self.db_path)
        db.ensure_schema(conn)
        conn.executescript(
            "INSERT INTO sessions(session_id, project_key, project, day, agent, intent,"
            " outcome, turns, toolcalls, first_ts, last_ts) VALUES"
            " ('aaaaaaaaaaaa1111','-p--p2-a','/home/user/P','20260304','builder',"
            "  'first intent','done',3,7,1700000000000,1700000600000),"
            " ('bbbbbbbbbbbb2222','-p--p2-a','/home/user/P','20260305','reviewer',"
            "  'second intent','ok',1,2,1700001000000,1700001600000);"
            " INSERT INTO session_actions(session_id, idx, text)"
            "  VALUES('aaaaaaaaaaaa1111',0,'did a thing');"
            " INSERT INTO session_learned(session_id, idx, text)"
            "  VALUES('aaaaaaaaaaaa1111',0,'learnt a thing');"
            " INSERT INTO topics(session_id, ts, project_key, summary)"
            "  VALUES('aaaaaaaaaaaa1111',1700000100000,'-p--p2-a','a topic');"
            " INSERT INTO prompts(workspace, idx, text) VALUES('ws1',0,'a prompt');"
            " INSERT INTO workspaces(workspace, folder) VALUES('ws1','/home/user/P');"
            " INSERT INTO agents(name, kind, description)"
            "  VALUES('builder','custom','builds'),('reviewer','custom','reviews');"
            " INSERT INTO models(account, group_name, name, provider,"
            " consumption_rate, context_window) VALUES"
            " ('acct-A','builder','Model X','acme',0.39,184000),"
            " ('acct-A','solo_agent','Model X','acme',0.39,184000);"
            " INSERT INTO session_models(session_id, account, agent_label, model_id, mode)"
            "  VALUES('aaaaaaaaaaaa1111','acct-A','agent','agent_1__Model X_null',0);"
            " INSERT INTO inventory(kind, name, owner_plugin, version, path, source)"
            "  VALUES('skill','my-skill','',NULL,'/x/my-skill','user'),"
            "        ('plugin','helper','mkt','1.2.3','/x/helper','plugin'),"
            "        ('mcp','server','project',NULL,'/x/server','plugin');"
            " INSERT INTO memory(scope, idx, text) VALUES('user_profile',0,'likes tabs');"
        )
        conn.commit()
        # Same post-sync step the real index runs, so the tables read the decoded
        # route rather than a NULL left by a fixture that only inserted ids.
        db.decode_session_models(conn)
        conn.commit()
        conn.close()

    def app(self, config=None):
        cfg = dict(tui.db.DEFAULTS) if config is None else config
        # A fixed clock keeps the "7d" windows stable no matter when the suite runs;
        # pick a "now" just after the seeded rows so they are inside the window.
        return tui.TrackerApp(db_path=self.db_path, clock=lambda: 1700002000.0,
                              config=cfg)

    def _insert(self, sql, params=()):
        """Write one row through the real connection helper, then close it.

        The app opens its database read-only, so the fixtures have to be the only
        writer — and they have to go through `open_db`, not `sqlite3.connect`, so the
        hermetic tripwire sees every path.
        """
        import tcut_db as db
        conn = db.open_db(self.db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


class StructureTest(TuiBase):
    def test_the_eight_tabs_are_present_and_in_order(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(120, 40)) as pilot:
                tc = app.query_one(TabbedContent)
                panes = list(tc.query(TabPane))
                # TabPane carries no label in this release; the tab bar does.
                return [pane.id for pane in panes], [tc.get_tab(pane.id).label_text
                                                    for pane in panes]
        ids, labels = run(go())
        self.assertEqual(ids, tui.TrackerApp.TAB_IDS)
        self.assertEqual(len(ids), 8)
        # cbut's tab set is the navigation contract: same labels, same order.
        self.assertEqual(labels, ["Dashboard", "Tools", "Skills", "Agents",
                                   "Plugins", "MCP", "Tokens", "Usage"])

    def test_every_wide_table_renders_exactly_its_columns(self):
        async def go():
            out = {}
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                for tid, (cols, _note, _chrome) in app.WIDE_TABLES.items():
                    table = app.query_one(f"#{tid}", DataTable)
                    out[tid] = [str(c.label) for c in table.columns.values()]
            return out
        labels = run(go())
        for tid, (cols, _note, _chrome) in tui.TrackerApp.WIDE_TABLES.items():
            with self.subTest(tid=tid):
                # Compare the labels, not just how many: a registry that names its
                # columns while the row builder supplies eight renders a shifted
                # table, and a count-only check calls that a pass.
                self.assertEqual(labels[tid], list(cols),
                                 f"{tid} renders columns its registry does not declare")

    def test_the_agents_tab_lists_the_seeded_agents(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                table = app.query_one("#t-agents", DataTable)
                return table.row_count
        self.assertEqual(run(go()), 2)

    def test_the_drill_down_reads_the_recorded_model_and_never_a_guess(self):
        """The model column moved to `EntityScreen` with the Sessions tab.

        The guard is the same one: a session Trae recorded no selection for must
        read as unknown, not as the agent's default model. The recorded one is
        shown by its decoded name, as every other model column is; a session with
        no decode falls back to the raw id it was recorded as. Cells are read by
        position, not ``get_cell(index, label)`` — this Textual release keys cells
        by RowKey, and a row index raises instead of reading.
        """
        async def go(agent):
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                tc = host.query_one(TabbedContent)
                tc.active = "tab-agents"
                await pilot.pause()
                table = host.query_one("#t-agents", DataTable)
                for idx in range(table.row_count):
                    if table.get_row_at(idx)[0] == agent:
                        table.move_cursor(row=idx)
                        break
                table.focus()
                await pilot.press("enter")
                await pilot.pause()
                entity = app.screen.query_one("#t-entity", DataTable)
                pos = [str(c.label) for c in entity.columns.values()].index("model")
                return [str(entity.get_row_at(i)[pos])
                        for i in range(entity.row_count)]
        for agent, want in (("builder", ["Model X"]),
                            ("reviewer", ["-"])):
            with self.subTest(agent=agent):
                self.assertEqual(run(go(agent)), want,
                                 "a session with no recorded selection must read as unknown")

    def test_the_range_selector_is_visible_only_on_windowed_tabs(self):
        """Skills, Plugins and MCP have no timestamp of their own."""
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                tc = app.query_one(TabbedContent)
                seen = {}
                for pane_id in app.TAB_IDS:
                    tc.active = pane_id
                    await pilot.pause()
                    seen[pane_id] = app._range_of(pane_id) is not None
                return seen
        seen = run(go())
        windowed = {"tab-dashboard", "tab-tools", "tab-agents", "tab-tokens",
                   "tab-usage"}
        for pane, has in seen.items():
            with self.subTest(pane=pane):
                self.assertEqual(has, pane in windowed,
                                 f"{pane} range visibility is wrong")


class InteractionTest(TuiBase):
    def test_enter_on_a_session_opens_its_detail_and_escape_returns(self):
        """Two hops now: an agent row opens its sessions, a row there opens the detail."""
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                tc = app.query_one(TabbedContent)
                tc.active = "tab-agents"
                await pilot.pause()
                table = app.query_one("#t-agents", DataTable)
                table.focus()
                await pilot.press("enter")
                await pilot.pause()
                mid = type(app.screen).__name__
                entity = app.screen.query_one("#t-entity", DataTable)
                entity.focus()
                await pilot.press("enter")
                await pilot.pause()
                opened = type(app.screen).__name__
                # The pushed screen is app.screen; querying the app resolves against
                # the default screen underneath, which does not have #session-body.
                body_children = len(app.screen.query_one("#session-body").children)
                await pilot.press("escape")
                await pilot.pause()
                after = type(app.screen).__name__
                return mid, opened, body_children, after
        mid, opened, children, after = run(go())
        self.assertEqual(mid, "EntityScreen", "Enter on an agent row went nowhere")
        self.assertEqual(opened, "SessionScreen", "Enter did not open the session detail")
        self.assertGreater(children, 0, "the session detail screen rendered nothing")
        self.assertEqual(after, "EntityScreen", "Escape did not come back to the session list")

    def test_session_detail_shows_the_actions_learned_and_topics(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                tc = app.query_one(TabbedContent)
                tc.active = "tab-agents"
                await pilot.pause()
                table = app.query_one("#t-agents", DataTable)
                # `builder` owns the seeded session with actions/learned/topics;
                # reaching it through the agent filter is now the only route.
                for idx in range(table.row_count):
                    if table.get_row_at(idx)[0] == "builder":
                        table.move_cursor(row=idx)
                        break
                table.focus()
                await pilot.press("enter")
                await pilot.pause()
                entity = app.screen.query_one("#t-entity", DataTable)
                entity.focus()
                await pilot.press("enter")
                await pilot.pause()
                text = "\n".join(
                    str(s.render()) for s in app.screen.query("#session-body Static"))
                return text
        text = run(go())
        self.assertIn("did a thing", text)
        self.assertIn("learnt a thing", text)
        self.assertIn("a topic", text)
        self.assertIn("model · agent", text)
        self.assertIn("Model X", text)
        self.assertIn("Built-in", text)
        self.assertNotIn("agent_1__Model X_null", text,
                         "the detail still prints Trae's raw id")

    def test_tab_binding_cycles_through_all_eight(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(120, 40)) as pilot:
                tc = app.query_one(TabbedContent)
                seen = [tc.active]
                for _ in range(len(tui.TrackerApp.TAB_IDS)):
                    await pilot.press("tab")
                    await pilot.pause()
                    seen.append(tc.active)
                return seen
        seen = run(go())
        # One full cycle forward lands back where we started.
        self.assertEqual(seen[0], seen[-1])
        self.assertEqual(set(seen), set(tui.TrackerApp.TAB_IDS))


class DashboardTest(TuiBase):
    def test_the_dashboard_panels_populate(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                return {
                    "sessions": str(app.query_one("#dash-sessions", Static).render()),
                    "projects": str(app.query_one("#dash-projects", Static).render()),
                    "top": str(app.query_one("#dash-top-projects", Static).render()),
                    "inv": str(app.query_one("#dash-inv-skills", Static).render()),
                }
        out = run(go())
        self.assertIn("2", out["sessions"], "the dashboard session count is wrong")
        self.assertIn("1", out["projects"], "the dashboard project count is wrong")
        self.assertIn("/home/user/P", out["top"], "the top-projects list is empty")
        # #dash-inv-skills is a count panel ("Skills                 1"), not a name list.
        self.assertIn("Skills", out["inv"])
        self.assertIn("1", out["inv"], "the dashboard skill count is wrong")



class DrillDownTest(TuiBase):
    """A row that is keyed must go somewhere, or say why it cannot.

    The regression this inherits: before `EntityScreen` existed, most tables stamped
    a `key_kind` on their rows while the app's handler understood only `session` —
    Enter was a no-op that looked like a frozen terminal. The tab set was later cut
    back to cbut's, which is why every route here starts on Agents or on an
    inventory tab.
    """

    async def _open(self, pilot, pane, table_id, want_cell=None, column=0):
        app = pilot.app
        # Query the *active* screen, not the app: once a screen is pushed,
        # ``app.query_one`` resolves against the base screen and reports the pushed
        # screen's table as missing.
        host = app.screen
        if pane is not None:
            tc = host.query_one(TabbedContent)
            tc.active = pane
            await pilot.pause()
        table = host.query_one(f"#{table_id}", DataTable)
        chosen = 0
        if want_cell is not None:
            for idx in range(table.row_count):
                if table.get_row_at(idx)[column] == want_cell:
                    chosen = idx
                    break
        table.focus()
        table.move_cursor(row=chosen)
        await pilot.press("enter")
        await pilot.pause()
        return app

    def test_an_agent_row_opens_only_its_own_sessions(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="builder")
                table = app.screen.query_one("#t-entity", DataTable)
                return type(app.screen).__name__, [table.get_row_at(i)
                                                   for i in range(table.row_count)]
        name, rows = run(go())
        self.assertEqual(name, "EntityScreen")
        self.assertEqual([r[1] for r in rows], ["aaaaaaaaaaaa"],
                         "the agent filter returned someone else's sessions")

    def test_the_drill_down_prints_the_selection_it_knows_instead_of_a_dash(self):
        """A project or agent drill-down knows the session model and estimate.

        The route and credit cells were the literal "-" on that screen, so a
        session Trae had a selection for — and that the balance split covered —
        read as unknown in the one list that shows it.
        """
        self._insert(
            "INSERT INTO credit_alloc(session_id, agent_label, model_id,"
            " start_ts, credits) VALUES('aaaaaaaaaaaa1111','agent',"
            " 'agent_1__Model X_null',1700000000000,12.5)")

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="builder")
                table = app.screen.query_one("#t-entity", DataTable)
                return [str(c) for c in table.get_row_at(0)]

        row = run(go())
        self.assertEqual(row[5], "Model X", "the drill-down hid a recorded selection")
        self.assertEqual(row[6], "Built-in",
                         "the route column did not follow the selection")
        self.assertEqual(row[7], "12.50", "the credit estimate was not read for the row")

    def test_a_session_inside_the_drill_down_still_opens_its_detail(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="reviewer")
                await self._open(pilot, None, "t-entity", want_cell="bbbbbbbbbbbb", column=1)
                return type(app.screen).__name__, app.screen.session_id
        name, sid = run(go())
        self.assertEqual(name, "SessionScreen",
                         "the entity screen stole a session row's own routing")
        self.assertEqual(sid, "bbbbbbbbbbbb2222")

    def test_the_drill_down_totals_the_rows_it_lists(self):
        """The header line cbut's drill-downs have: what this set of rows adds up to.

        The table lists turns and tool calls per session and nothing totals them, so
        "the sessions behind this agent" had no answer to "how much work". The count in
        the first field is also compared with the row count, because the header and the
        list are only honest if they are the same set of rows.
        """
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="builder")
                screen = app.screen
                return (str(screen.query_one("#entity-summary", Static).render()),
                        screen.query_one("#t-entity", DataTable).row_count)
        line, listed = run(go())
        parts = line.split(" · ")
        self.assertEqual(parts[0], f"{listed} session",
                         "the header counted a different set than the table listed")
        self.assertIn("3 turns", line, "the turns of the listed sessions were not totalled")
        self.assertIn("7 tool calls", line)
        self.assertIn("1 project", line)
        self.assertIn("→", line, "the header shows no span")
        self.assertIn("7 days", line, "the header does not say which window it counted")

    def test_a_session_set_with_no_project_key_reads_as_unknown_not_zero(self):
        """`0 projects` beside a session count claims a measurement the field never gave.

        Found on the real index: 28 of 49 sessions carry neither a decoded project nor a raw
        key, and the agent that owns 22 of them has no key on any — so the header's first
        shape read `22 sessions · 0 projects`, as though they had happened nowhere. `turns`
        and `toolcalls` are not that case and must not be dashed: the writer never leaves
        them NULL (measured: 0 NULL in 49 rows), so a stored 0 there is a reading.
        """
        self._insert("INSERT INTO agents(name, kind, description)"
                     " VALUES('blank',NULL,NULL)")
        self._insert("INSERT INTO sessions(session_id, project_key, project, agent,"
                     " last_ts, turns, toolcalls) VALUES"
                     " ('blank000000000001',NULL,NULL,'blank',1700001500000,0,0),"
                     " ('blank000000000002',NULL,NULL,'blank',1700001600000,3,5)")

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="blank")
                return str(app.screen.query_one("#entity-summary", Static).render())
        fields = run(go()).split(" · ")
        self.assertEqual(fields[:4], ["2 sessions", "3 turns", "5 tool calls", "-"],
                         "an unmeasurable project total printed as a counted zero,"
                         " or a stored count lost its number")

    def test_a_keyed_session_set_prints_its_project_count(self):
        # The other half of the rule: when the key is there, the number is printed, not
        # hidden behind the dash the missing case needs.
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="builder")
                return str(app.screen.query_one("#entity-summary", Static).render())
        self.assertEqual(run(go()).split(" · ")[3], "1 project")


    def test_the_header_and_the_list_agree_when_the_window_cuts_the_set(self):
        # Three sessions for one agent, one of them 400 days back. The tab counts two,
        # the header must count two, and the list must hold two rows — three readings of
        # one window, which is the same disagreement this repo already fixed twice.
        self._insert("INSERT INTO agents(name, kind, description)"
                     " VALUES('spread',NULL,NULL)")
        for n, ts_ms in ((1, 1700001500000), (2, 1700001600000),
                         (3, int(1700002000 - 400 * 86400) * 1000)):
            self._insert("INSERT INTO sessions(session_id, project_key, agent, last_ts)"
                         " VALUES(?, '-p--p2-a', 'spread', ?)",
                         (f"spread00000000000000000{n}", ts_ms))

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="spread")
                screen = app.screen
                return (str(screen.query_one("#entity-summary", Static).render()),
                        screen.query_one("#t-entity", DataTable).row_count)
        line, listed = run(go())
        self.assertEqual(listed, 2, "the windowed list kept the out-of-range session")
        self.assertEqual(line.split(" · ")[0], "2 sessions")

    def test_the_summary_marks_a_span_whose_edge_came_from_the_id(self):
        """A derived session has no measured time, so its span edges are derived too."""
        import tcut_db as db
        sid = ("%08x" % 1700001000) + "0000000000000000"
        self._insert("INSERT INTO agents(name, kind, description)"
                     " VALUES('stamper',NULL,NULL)")
        self._insert("INSERT INTO sessions(session_id, project_key, agent, last_ts,"
                     " turns, toolcalls) VALUES(?, '-p--p2-a', 'stamper', NULL, 2, 5)",
                     (sid[:24],))
        conn = db.open_db(self.db_path)
        db.stamp_created_ts(conn)
        conn.commit()
        conn.close()

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-agents", "t-agents", want_cell="stamper")
                return str(app.screen.query_one("#entity-summary", Static).render())
        line = run(go())
        span = [p for p in line.split(" · ") if "→" in p]
        self.assertEqual(len(span), 1, f"no span in {line!r}")
        self.assertTrue(span[0].startswith("~"),
                        f"{span[0]!r} presents a derived position as a measurement")

    def test_an_unroutable_row_says_why_instead_of_silently_ignoring_enter(self):
        async def go():
            app = self.app()
            seen = []
            app.notify = lambda *a, **k: seen.append((a, k))
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-skills", "t-skills")
                return type(app.screen).__name__, seen
        name, seen = run(go())
        self.assertEqual(name, "Screen", "an inventory row pushed a screen it cannot fill")
        self.assertTrue(seen, "Enter was swallowed with no message at all")
        self.assertIn("no usage per", str(seen[0][0]))


    def test_a_sync_that_indexes_nothing_still_redraws_the_session_sync_line(self):
        # The regression this pins: a sync that finds nothing new takes the light
        # refresh path, and the Dashboard panel used to be redrawn only on the heavy
        # one — so "Session sync not yet" stayed on screen after a completed sync.
        class Stub:
            @staticmethod
            def run(quiet=False, db_path=None):
                return {"results": {"session memory": 0, "credit logs": 0}}

        async def go():
            app = self.app()
            app.sync_mod = Stub          # no real Trae read from inside the suite
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                before = str(host.query_one("#dash-sync-last").render())
                await pilot.press("r")
                for _ in range(80):
                    await pilot.pause(0.05)
                    if app._last_sync is not None:
                        break
                return before, str(host.query_one("#dash-sync-last").render())
        before, after = run(go())
        self.assertIn("not yet", before)
        self.assertNotIn("not yet", after,
                         "a completed sync left the panel claiming none had happened")


class RegistryGuardTest(unittest.TestCase):
    """cbut's two enumeration guards, ported: no unregistered table, no screen
    that ignores the configured cap."""

    def test_every_datatable_in_the_source_is_registered(self):
        source = TUI_PY.read_text(encoding="utf-8")
        # `DataTable(id="x", zebra_stripes=True)` — a pattern that demanded the
        # closing paren right after the quote matched nothing and passed on the
        # empty set it produced.
        found = set(re.findall(r'DataTable\(\s*id="([^"]+)"', source))
        registered = set(tui.TrackerApp.WIDE_TABLES) | set(tui.EntityScreen.WIDE_TABLES)
        self.assertTrue(found, "the pattern matched no table at all")
        self.assertEqual(found - registered, set(),
                         "a table exists that the narrow-terminal plan does not know")
        self.assertEqual(registered - found, set(),
                         "a registry entry names a table the source does not mount")

    def test_every_pushed_wide_screen_resolves_the_cap_from_the_app(self):
        from textual.screen import Screen
        hosts = [c for c in vars(tui).values()
                 if isinstance(c, type) and issubclass(c, tui.WideTableMixin)
                 and issubclass(c, Screen) and c is not tui.WideTableMixin]
        self.assertTrue(hosts, "no pushed wide screen exists to check")
        for host in hosts:
            with self.subTest(host=host.__name__):
                self.assertIn("name_cap", host.__dict__,
                              f"{host.__name__} would render with the shipped default cap")




class DashboardPanelTest(TuiBase):
    """The two Dashboard panels that survived the cut back to cbut's tab set.

    The credit series lost its tab, but the balance is still a number Trae really
    writes, so it stays where a panel can show it. The `skipped` fetches must not
    join the series as a zero and the spend figure is a lower bound — that half of
    the rule is covered headlessly in test_stats.py, where `tcut credits` prints it.
    """

    def test_the_dashboard_shows_top_models_and_the_credit_panels(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                await pilot.pause()
                return {
                    "models": str(host.query_one("#dash-top-models", Static).render()),
                    "latest": str(host.query_one("#dash-credits-latest", Static).render()),
                    "spent": str(host.query_one("#dash-credits-spent", Static).render()),
                    "sync": str(host.query_one("#dash-sync-last", Static).render()),
                }
        out = run(go())
        # The seed gives session aaaa... the `agent` selection; bbbb... has none.
        self.assertIn("Model X", out["models"],
                      "the Dashboard has no decoded model ranking")
        self.assertNotIn("agent_1__Model X_null", out["models"],
                         "the ranking still prints Trae's raw id")
        self.assertIn("1", out["models"], "the ranking shows no session count")
        self.assertIn("Balance", out["latest"])
        self.assertIn("Spent", out["spent"])
        self.assertIn("Session sync", out["sync"])
        self.assertIn("not yet", out["sync"],
                      "a database the CLI indexed must not look like a failed sync")


    def test_a_catalog_count_and_a_used_count_never_share_one_word(self):
        """The status bar counts catalog rows; a panel counts the models used.

        Both used to say "models" — 291 above, 9 below, on one screen, with
        nothing to tell the reader which was which.
        """
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                tc = host.query_one(TabbedContent)
                tc.active = "tab-usage"
                await pilot.pause()
                return (app._status_line(),
                        str(host.query_one("#sum-models", Static).render()))
        status, panel = run(go())
        self.assertIn("catalog models", status)
        self.assertIn("Models used", panel)


class DateRangePickerTest(TuiBase):
    """The picker must produce the same windows the range Select does.

    It is the second way into every windowed tab, and nothing exercised it: the
    All time chip set "end follows now", so the escape-hatch range excluded every
    row with no timestamp — the exact loss ``db.window_bounds("all")`` was
    fixed for on the Select path.
    """

    def _pick(self, current, clicks):
        async def go():
            app = self.app()
            async with app.run_test(size=(120, 40)) as pilot:
                seen = {}
                modal = tui.DateRangeModal(current, 1700002000000)
                app.push_screen(modal, lambda r: seen.setdefault("r", r))
                await pilot.pause()
                for wid in clicks:
                    await pilot.click(wid)
                    await pilot.pause()
                await pilot.click("#dr-ok")
                await pilot.pause()
                return seen.get("r")
        return run(go())

    def test_the_all_time_chip_produces_a_window_with_no_bounds(self):
        got = self._pick("7d", ["#dr-all"])
        self.assertEqual((got.start_ms, got.end_ms, got.follow_now),
                         (None, None, False),
                         "All time kept a 'now' upper bound, which hides every undated row")

    def test_opening_the_picker_on_all_time_and_confirming_keeps_it(self):
        got = self._pick("all", [])
        self.assertEqual((got.start_ms, got.end_ms, got.follow_now),
                         (None, None, False),
                         "the picker prefilled All time with an end of now")

    def test_the_end_of_day_chip_includes_the_last_minute(self):
        """A window's end is exclusive, so a "23:59" end dropped the last minute.

        The chip wrote 23:59 into the end card, and every window here is
        ``[start, end)`` — activity between 23:59:00 and 23:59:59.999 fell
        outside the day it belongs to. The chip writes the next midnight, which
        is the same instant on a clock and exact in this model.
        """
        got = self._pick("7d", ["#dr-end-quick-3"])
        now_day = datetime.fromtimestamp(1700002000).date()
        expected = int(datetime(now_day.year, now_day.month, now_day.day).timestamp()
                       + 24 * 3600) * 1000
        self.assertFalse(got.follow_now, "the chip left the end following the clock")
        self.assertEqual(got.end_ms, expected,
                         "the end-of-day chip did not reach the day's exclusive end")
        late = expected - 30_000                  # 23:59:30 on the day it ends
        self.assertLess(late, got.end_ms, "23:59:30 fell outside the day")

    def test_the_picker_all_time_lands_on_the_preset_the_select_names(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(120, 40)) as pilot:
                app.tab_range["tab-usage"] = "7d"
                app._open_date_range("tab-usage")
                await pilot.pause()
                await pilot.click("#dr-all")
                await pilot.pause()
                await pilot.click("#dr-ok")
                await pilot.pause()
                return app.tab_range["tab-usage"]
        self.assertEqual(run(go()), "all",
                         "the picker's All time is not the window the Select calls all")


class ModelRouteTuiTest(TuiBase):
    """The Tokens tab is a route table, not a raw balance series.

    It must show where the estimated credits went, mark a third-party route as
    `3P`, keep a token column that honestly reads `-`, and open the sessions
    behind that route on Enter. The estimate is the only per-model spend Trae's
    plaintext supports, so the header has to say `est.` too.
    """

    SESSION = "cccccccccccc3333"
    THIRD_ID = "solo_agent_3_volcengine-plan_Route Z_99"

    def _seed_route_and_drop(self):
        import tcut_db as db
        conn = db.open_db(self.db_path)
        conn.executescript(
            "INSERT INTO models(account, group_name, name, provider)"
            " VALUES('acct-A','g','Route Z','volcengine-plan');"
            "INSERT INTO sessions(session_id, project_key, turns, toolcalls,"
            " created_ts) VALUES('cccccccccccc3333','-p--p2-z',4,2,1700001500000);"
            "INSERT INTO session_models(session_id, account, agent_label, model_id)"
            " VALUES('cccccccccccc3333','acct-A','solo_agent',"
            "        'solo_agent_3_volcengine-plan_Route Z_99');"
            "INSERT INTO credit_events(source, ts, kind, remaining, generation)"
            " VALUES('/logs/a.log',1700001200000,'balance',1000.0,1),"
            "       ('/logs/a.log',1700001800000,'balance',940.0,2);")
        db.decode_session_models(conn)
        db.allocate_credits(conn)
        conn.commit()
        conn.close()

    def test_the_tokens_tab_ranks_routes_and_keeps_tokens_honest(self):
        self._seed_route_and_drop()

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                tc = app.query_one(TabbedContent)
                tc.active = "tab-tokens"
                await pilot.pause()
                table = app.screen.query_one("#t-tokens", DataTable)
                labels = [str(c.label) for c in table.columns.values()]
                row = [str(c) for c in table.get_row_at(0)]
                note = str(app.screen.query_one("#tokens-note", Static).render())
                return labels, row, note, table.row_count

        labels, row, note, count = run(go())
        self.assertEqual(labels, list(tui.TOKENS_COLUMNS))
        # The fixture's built-in Model X session is in the same window; the route
        # with the estimate sorts first.
        self.assertEqual(count, 2)
        self.assertEqual(row[labels.index("model")], "Route Z")
        pos = labels.index("route")
        self.assertEqual(row[pos], "3P")
        self.assertEqual(row[labels.index("tokens")], "-")
        self.assertEqual(row[labels.index("credits est.")], "60.00")
        self.assertIn("no token counts", note)
        self.assertIn("estimated", note)

    def test_enter_on_a_route_opens_its_sessions_with_the_estimate(self):
        self._seed_route_and_drop()

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                tc = app.query_one(TabbedContent)
                tc.active = "tab-tokens"
                await pilot.pause()
                table = app.screen.query_one("#t-tokens", DataTable)
                table.focus()
                await pilot.press("enter")
                await pilot.pause()
                entity = app.screen.query_one("#t-entity", DataTable)
                summary = str(app.screen.query_one("#entity-summary", Static).render())
                return entity.row_count, summary, app.screen.query_one(
                    "#entity-title", Static).render()

        count, summary, title = run(go())
        self.assertEqual(count, 1)
        self.assertIn("1 session", summary)
        self.assertIn("60.00 credits est.", summary)
        self.assertIn("3P", str(title))


class WindowRuleTest(TuiBase):
    """A window must never report a zero for rows it simply cannot see.

    25 of this machine's 49 sessions carry no timestamp at all (their snapshot repos
    have no tags), so a range drops them silently. Before this rule the Agents tab
    printed `0 sessions` for an agent that owns 22 of them — and Enter on that row
    opened a list of 22, because the screen read all-time.
    """

    def _seed_ranges(self):
        """One agent whose session no window can date, one with an old dated session.

        The clock is pinned to 1700002000 by ``TuiBase.app()`` and the Agents tab
        defaults to 7d, so `oldbot`'s row (last_ts NULL) is invisible to every bounded
        range and `farbot`'s (400 days back) is invisible only to the 7d one.
        """
        self._insert("INSERT INTO agents(name, kind, description)"
                     " VALUES('oldbot',NULL,NULL),('farbot',NULL,NULL)")
        self._insert("INSERT INTO sessions(session_id, project_key, agent, last_ts)"
                     " VALUES('oldaaaaaaaaaaa','-p--p2-a','oldbot',NULL)")
        self._insert("INSERT INTO sessions(session_id, project_key, agent, last_ts)"
                     " VALUES('farbbbbbbbbbbb','-p--p2-a','farbot',?)",
                     (int(1700002000 - 400 * 86400) * 1000,))

    def _cells(self, range_key=None):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                if range_key is not None:
                    app.tab_range["tab-agents"] = range_key
                    app.refresh_data()
                    await pilot.pause()
                tc = host.query_one(TabbedContent)
                tc.active = "tab-agents"
                await pilot.pause()
                table = host.query_one("#t-agents", DataTable)
                return {table.get_row_at(i)[0]: table.get_row_at(i)[2]
                        for i in range(table.row_count)}
        return run(go())

    def test_undated_rows_read_as_unknown_and_a_true_zero_stays_a_zero(self):
        self._seed_ranges()
        cells = self._cells()
        self.assertEqual(cells["oldbot"], "-",
                         "a window that cannot see a row must not claim there are none")
        self.assertEqual(cells["farbot"], "0",
                         "a dated row outside the range is a real zero, not unknown")
        self.assertEqual(cells["builder"], "1", "the seeded in-window session must still count")

    def test_all_time_shows_the_rows_that_no_bounded_range_can_see(self):
        # The dash is only honest if All time really is the escape hatch. Until
        # `window_bounds("all")` stopped applying an upper bound, an undated session
        # was invisible in every range, and the tab read `-` forever.
        self._seed_ranges()
        cells = self._cells(range_key="all")
        self.assertEqual(cells["oldbot"], "1", "All time must count the undated row")
        self.assertEqual(cells["farbot"], "1", "All time must count the 400-day-old row")
        self.assertEqual(cells["builder"], "1")

    def test_the_drill_down_keeps_the_window_of_the_row_it_came_from(self):
        self._insert("INSERT INTO agents(name, kind, description)"
                     " VALUES('winbot',NULL,NULL)")
        self._insert("INSERT INTO sessions(session_id, project_key, agent, last_ts)"
                     " VALUES('win000000001','-p--p2-a','winbot',?)", (1700001500000,))
        self._insert("INSERT INTO sessions(session_id, project_key, agent, last_ts)"
                     " VALUES('win000000002','-p--p2-a','winbot',?)",
                     (int(1700002000 - 400 * 86400) * 1000,))

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                tc = host.query_one(TabbedContent)
                tc.active = "tab-agents"
                await pilot.pause()
                table = host.query_one("#t-agents", DataTable)
                count = None
                for idx in range(table.row_count):
                    if table.get_row_at(idx)[0] == "winbot":
                        count = table.get_row_at(idx)[2]
                        table.move_cursor(row=idx)
                        break
                table.focus()
                await pilot.press("enter")
                await pilot.pause()
                entity = app.screen.query_one("#t-entity", DataTable)
                ids = [entity.get_row_at(i)[1] for i in range(entity.row_count)]
                title = str(app.screen.query("#entity-body Static")[0].render())
                return count, ids, title
        count, ids, title = run(go())
        self.assertEqual(count, "1", "the row counts one in-window session")
        self.assertEqual(ids, ["win000000001"],
                         f"the screen listed {ids} — it ignored the range the count came from")
        self.assertIn("days", title, "the heading should say which window this list is bound to")


    def test_a_derived_creation_second_counts_in_the_window_and_is_marked(self):
        """The whole point of `created_ts`: these rows used to be invisible to every range.

        The id's prefix is built from the pinned clock so the derived second lands
        inside the 7d window. The tab must then count it as a number — not `-`, which
        now really means "no time anywhere" — and the row it drills to must carry the
        `~` that says the position was derived rather than measured.
        """
        import tcut_db as db
        sid = ("%08x" % 1700001000) + "0000000000000000"
        self._insert("INSERT INTO agents(name, kind, description)"
                     " VALUES('stamped',NULL,NULL)")
        self._insert("INSERT INTO sessions(session_id, project_key, agent, last_ts)"
                     " VALUES(?, '-p--p2-a', 'stamped', NULL)", (sid[:24],))
        conn = db.open_db(self.db_path)
        db.stamp_created_ts(conn)
        conn.commit()
        self.assertEqual(conn.execute(
            "SELECT created_ts FROM sessions WHERE session_id = ?",
            (sid[:24],)).fetchone()[0], 1700001000 * 1000)
        conn.close()

        cells = self._cells()
        self.assertEqual(cells["stamped"], "1",
                         "a session placed by its derived time must count, not read as unknown")

        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                tc = host.query_one(TabbedContent)
                tc.active = "tab-agents"
                await pilot.pause()
                table = host.query_one("#t-agents", DataTable)
                for idx in range(table.row_count):
                    if table.get_row_at(idx)[0] == "stamped":
                        table.move_cursor(row=idx)
                        break
                table.focus()
                await pilot.press("enter")
                await pilot.pause()
                entity = app.screen.query_one("#t-entity", DataTable)
                return [entity.get_row_at(i)[0] for i in range(entity.row_count)]
        when = run(go())
        self.assertEqual(len(when), 1, "the derived session did not reach the drill-down")
        self.assertTrue(when[0].startswith("~"),
                        f"{when[0]!r} reads like a measured activity time")


class DashboardLeaderboardTest(TuiBase):
    """Top projects / Top agents must not spend their emptiness on the wrong claim.

    Both panels dropped every zero-count row so a leaderboard stayed a leaderboard. That
    was a lie as soon as a row could be *invisible to the range* rather than idle in it:
    an agent owning 22 undated sessions disappeared, and the panel printed "nothing in
    this window" — the very sentence an index that never synced prints. `undated` gives
    the row its slot back as a `-`, and the two kinds of empty now get two sentences.
    """

    def _past_window(self):
        import tcut_db as db
        start = int(1700002000 - 400 * 86400) * 1000
        return db.CustomWindow(start, start + 86400 * 1000)

    def _seed_hidden(self):
        """One agent and one project whose only session has no time anywhere.

        Nothing in the test path stamps `created_ts`, so this row is what the real
        footprint still has: no tag, no derivable id, invisible to every bounded range.
        """
        self._insert("INSERT INTO agents(name, kind, description)"
                     " VALUES('ghostbot',NULL,NULL)")
        self._insert("INSERT INTO sessions(session_id, project_key, project, agent,"
                     " last_ts) VALUES('ghostaaaaaaaaa','-g--p2-g','/home/user/G',"
                     "'ghostbot',NULL)")

    def _dash(self, range_key=None):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                if range_key is not None:
                    app.tab_range["tab-dashboard"] = range_key
                    app.refresh_data()
                await pilot.pause()
                return {
                    "projects": str(host.query_one("#dash-top-projects",
                                                   Static).render()),
                    "agents": str(host.query_one("#dash-top-agents", Static).render()),
                    "models": str(host.query_one("#dash-top-models", Static).render()),
                    "sessions": str(host.query_one("#dash-sessions", Static).render()),
                    "note": str(host.query_one("#dash-note", Static).render()),
                }
        return run(go())

    @staticmethod
    def _column(text, name, width):
        """The value a leaderboard line prints for `name`, after its fixed-width field."""
        for line in text.splitlines():
            body = line.split(". ", 1)[-1]
            if body.startswith(name):
                return body[width:].strip()
        return None

    def test_a_row_no_window_can_date_keeps_its_slot_and_reads_as_unknown(self):
        self._seed_hidden()
        out = self._dash()
        self.assertEqual(self._column(out["agents"], "ghostbot", 24), "-",
                         "the panel hid an agent behind a zero it never measured")
        self.assertEqual(self._column(out["agents"], "builder", 24), "1 session",
                         "a real count lost its unit on the way to the dash")
        self.assertEqual(self._column(out["projects"], "/home/user/G", 26), "-",
                         "the same blind spot on the project side stayed invisible")

    def test_an_empty_panel_names_the_missing_index(self):
        # Nothing indexed at all: no project keys, no installed agents. This is the
        # sentence that means "run tcut sync", and it must not be the one a window
        # produces.
        self._insert("UPDATE sessions SET project_key = NULL")
        self._insert("DELETE FROM agents")
        out = self._dash()
        self.assertEqual(out["projects"].strip(), "no projects indexed")
        self.assertEqual(out["agents"].strip(), "no agents installed")

    def test_a_range_that_can_date_nothing_says_so(self):
        # The seeded rows are all measured and all outside the picked span, so every
        # project lists with a real zero — nothing is hidden, and saying
        # "no projects indexed" here would send the reader to the wrong fix.
        out = self._dash(range_key=self._past_window())
        self.assertIn("none dated in", out["projects"])
        self.assertIn("none dated in", out["agents"])
        self.assertNotIn("no projects indexed", out["projects"])
        self.assertNotIn("nothing in this window", out["projects"],
                         "the one sentence that covered both cases is back")

    def test_a_range_full_of_unattributed_sessions_does_not_blame_the_clock(self):
        """The real footprint's actual state, reproduced: a full window, no labels.

        Measured on this machine — all 20 sessions inside the current 7d window carry
        `agent` NULL. Top agents printed `none dated in 7 days` beside a Sessions panel
        reading 20, which sends the reader to widen a range that is already full.
        """
        self._insert("UPDATE sessions SET agent = NULL")
        out = self._dash()
        self.assertIn("no session in this range names an installed agent", out["agents"])
        self.assertNotIn("none dated in", out["agents"],
                         "the blank was still blamed on dates")
        self.assertIn("Sessions", out["sessions"])
        self.assertIn("2", out["sessions"], "the window was not in fact empty")

    def test_the_models_panel_blames_the_window_that_hid_it(self):
        # `q_top_models` filters in SQL, so a hidden model is absent rather than zero —
        # the one panel where an empty list can mean either "never recorded" or
        # "not in this span".
        out = self._dash(range_key=self._past_window())
        self.assertIn("none dated in", out["models"])
        self.assertNotIn("no model selection recorded", out["models"])

        self._insert("DELETE FROM session_models")
        out = self._dash(range_key="all")
        self.assertEqual(out["models"].strip(), "no model selection recorded")

    def test_the_dashboard_discloses_the_sessions_it_could_not_measure(self):
        self._seed_hidden()
        out = self._dash()
        self.assertIn("1 session with no measured time", out["note"],
                      "the number that sizes the `~` caveat was on no panel at all")
        self.assertIn("session id (~)", out["note"],
                      "the marker every list prints has to be explained somewhere")
        self.assertNotIn("nothing in this window", out["note"])


if __name__ == "__main__":
    unittest.main()
