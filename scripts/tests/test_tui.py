"""test_tui.py — the interface, driven headlessly through Textual's own test harness.

``app.run_test()`` runs the real app against a real (throwaway) database in a simulated
terminal, which is the only way to assert the things the interface actually promises: that
the ten tabs exist in the order the docs list, that each renders its own columns, that the
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
        conn.close()

    def app(self, config=None):
        cfg = dict(tui.db.DEFAULTS) if config is None else config
        # A fixed clock keeps the "7d" windows stable no matter when the suite runs;
        # pick a "now" just after the seeded rows so they are inside the window.
        return tui.TrackerApp(db_path=self.db_path, clock=lambda: 1700002000.0,
                              config=cfg)


class StructureTest(TuiBase):
    def test_the_ten_tabs_are_present_and_in_order(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(120, 40)) as pilot:
                tc = app.query_one(TabbedContent)
                return [pane.id for pane in tc.query(TabPane)]
        ids = run(go())
        self.assertEqual(ids, tui.TrackerApp.TAB_IDS)
        self.assertEqual(len(ids), 10)

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

    def test_the_sessions_tab_lists_the_seeded_sessions(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                table = app.query_one("#t-sessions", DataTable)
                return table.row_count
        self.assertEqual(run(go()), 2)

    def test_the_sessions_tab_shows_the_recorded_model_and_never_a_guess(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                table = app.query_one("#t-sessions", DataTable)
                # Positional, not ``get_cell(index, label)``: this Textual release
                # keys cells by RowKey, and a row index raises instead of reading.
                labels = [str(c.label) for c in table.columns.values()]
                pos = labels.index("model")
                return sorted(str(table.get_row_at(idx)[pos])
                              for idx in range(table.row_count))
        cells = run(go())
        self.assertEqual(cells, ["-", "agent_1__Model X_null"],
                         "a session with no recorded selection must read as unknown")

    def test_the_range_selector_is_visible_only_on_windowed_tabs(self):
        """Prompts, the inventory tabs and Memory have no timestamp of their own."""
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
        windowed = {"tab-dashboard", "tab-sessions", "tab-projects", "tab-agents",
                    "tab-usage"}
        for pane, has in seen.items():
            with self.subTest(pane=pane):
                self.assertEqual(has, pane in windowed,
                                 f"{pane} range visibility is wrong")


class InteractionTest(TuiBase):
    def test_enter_on_a_session_opens_its_detail_and_escape_returns(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                tc = app.query_one(TabbedContent)
                tc.active = "tab-sessions"
                await pilot.pause()
                table = app.query_one("#t-sessions", DataTable)
                table.focus()
                await pilot.press("enter")
                await pilot.pause()
                opened = type(app.screen).__name__
                # The pushed screen is app.screen; querying the app resolves against
                # the default screen underneath, which does not have #session-body.
                body_children = len(app.screen.query_one("#session-body").children)
                await pilot.press("escape")
                await pilot.pause()
                after = type(app.screen).__name__
                return opened, body_children, after
        opened, children, after = run(go())
        self.assertEqual(opened, "SessionScreen", "Enter did not open the session detail")
        self.assertGreater(children, 0, "the session detail screen rendered nothing")
        self.assertNotEqual(after, "SessionScreen", "Escape did not leave the detail screen")

    def test_session_detail_shows_the_actions_learned_and_topics(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                tc = app.query_one(TabbedContent)
                tc.active = "tab-sessions"
                await pilot.pause()
                table = app.query_one("#t-sessions", DataTable)
                # Rows sort by last_ts DESC, so target the seeded session that has
                # actions/learned/topics rather than assuming it is row 0.
                for idx in range(table.row_count):
                    if table.get_row_at(idx)[1] == "aaaaaaaaaaaa":
                        table.move_cursor(row=idx)
                        break
                table.focus()
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
        self.assertIn("agent_1__Model X_null", text)

    def test_tab_binding_cycles_through_all_ten(self):
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

    Before `EntityScreen` existed, seven of the eight tables stamped a `key_kind`
    on their rows and the app's handler understood only `session` — Enter was a
    no-op that looked like a frozen terminal.
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

    def test_a_project_row_opens_its_sessions(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-projects", "t-projects")
                name = type(app.screen).__name__
                rows = [app.screen.query_one("#t-entity", DataTable).get_row_at(i)
                        for i in range(app.screen.query_one("#t-entity", DataTable).row_count)]
                return name, rows
            return None, None
        name, rows = run(go())
        self.assertEqual(name, "EntityScreen", "a project row went nowhere")
        self.assertEqual(len(rows), 2, "the project holds both seeded sessions")
        self.assertEqual(sorted(r[1] for r in rows), ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])

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

    def test_a_session_inside_the_drill_down_still_opens_its_detail(self):
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                await self._open(pilot, "tab-projects", "t-projects")
                await self._open(pilot, None, "t-entity", want_cell="bbbbbbbbbbbb", column=1)
                return type(app.screen).__name__, app.screen.session_id
        name, sid = run(go())
        self.assertEqual(name, "SessionScreen",
                         "the project screen stole a session row's own routing")
        self.assertEqual(sid, "bbbbbbbbbbbb2222")

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




class UsageTabTest(TuiBase):
    """The Usage tab and the two new Dashboard panels.

    cbut's Usage page counts requests, tokens and cache; none of that exists for
    Trae CN. What this tab must still do is say so in the UI, and render the one
    number Trae does write.
    """

    def _seed_credits(self):
        import tcut_db as db
        conn = db.open_db(self.db_path)
        conn.executescript(
            " INSERT INTO credit_events(source, ts, kind, remaining, generation)"
            "  VALUES('/x/logs/20261001T100000/window1/renderer.log',"
            " 1700000000000,'balance',1800,0),"
            "  ('/x/logs/20261002T100000/window1/renderer.log',"
            " 1700001500000,'balance',154.0244,0),"
            "  ('/x/logs/20261002T100000/window1/renderer.log',"
            " 1700001560000,'skipped',NULL,NULL);"
        )
        conn.commit()
        conn.close()

    def test_the_usage_tab_lists_balances_and_names_the_bound(self):
        self._seed_credits()
        async def go():
            app = self.app()
            async with app.run_test(size=(140, 45)) as pilot:
                host = app.screen
                host.query_one(TabbedContent).active = "tab-usage"
                await pilot.pause()
                table = host.query_one("#t-usage", DataTable)
                return (str(host.query_one("#usage-note", Static).render()),
                        [table.get_row_at(i) for i in range(table.row_count)],
                        [str(c.label) for c in table.columns.values()])
        note, rows, labels = run(go())
        self.assertIn("Tokens, cost, requests and tool names are absent", note)
        self.assertIn("tcut format", note)
        self.assertEqual(labels, list(tui.USAGE_COLUMNS))
        self.assertEqual(len(rows), 2, "the numberless skipped row joined the series")
        self.assertEqual(rows[0][1], "154.0244")
        self.assertEqual(rows[0][2], "1645.9756", "the fall between samples is the bound")
        self.assertNotIn("token", " ".join(str(c) for r in rows for c in r).lower())

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
        self.assertIn("agent_1__Model X_null", out["models"],
                      "the Dashboard has no model ranking")
        self.assertIn("1", out["models"], "the ranking shows no session count")
        self.assertIn("Latest balance", out["latest"])
        self.assertIn("Spent at least", out["spent"])
        self.assertIn("Session sync", out["sync"])
        self.assertIn("not yet", out["sync"],
                      "a database the CLI indexed must not look like a failed sync")


if __name__ == "__main__":
    unittest.main()
