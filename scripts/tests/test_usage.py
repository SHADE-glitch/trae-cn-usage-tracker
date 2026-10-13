"""test_usage.py — the two queries that exist only to back a tab.

cbut's tab set is the navigation contract, so the Tools and Usage tabs are present here
even though Trae CN writes no per-tool name and no per-request line. That gives their
backing queries a failure mode the others cannot have: each may quietly present
something as more than it is — a call count as a tool, a stored number as a measurement,
a derived timestamp as a measured one. These cases pin what each query refuses to do.

* ``q_toolcall_sessions`` aggregates snapshot git tags into a **count per session**.
  ``test_a_session_is_counted_not_named`` fixes the column list, so a future column
  carrying a tool-call id fails instead of turning a count into a fake ranking.
* ``q_usage_summary`` fills the Usage page's panels, where a ``0`` standing in for
  something never written is the lie to avoid. The derived / undated cases pin both
  halves of that: a window may hold a derived time (the row carries ``~``), and a
  window never turns a derivation into a measurement (``unmeasured`` stays all-time).
"""

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


# Two measured sessions on two days, one session whose time came from the id rather than
# from a measurement, and one session with no timestamp at all.
MEASURED_A = "aaaaaaaaaaaa1111"   # measured, two messages / four tool calls
MEASURED_B = "bbbbbbbbbbbb2222"   # measured, one message / one tool call
DERIVED_C = "cccccccccccc3333"    # created_ts only -> derived
UNDATED_D = "dddddddddddd4444"    # no last_ts and no created_ts

A_START, A_END = 1700000000000, 1700000600000
B_START, B_END = 1700001000000, 1700001600000
C_CREATED = 1700020000000
# A window that contains only session A. Its end clears A's `last_ts`, because the
# window rides on the session's time, not on the time of any one call.
WIN_START, WIN_END = 1699999000000, 1700000700000
# A window after every fixture row's time, so it can legitimately hold nothing.
EMPTY_START, EMPTY_END = 1800000000000, 1800000000001

TOOLCALL_COLUMNS = ["session_id", "project_key", "project", "calls", "messages",
                    "shown_ts", "derived_ts", "first_ts", "last_ts"]


class UsageBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "usage.db"
        self.conn = db.open_db(self.db_path)
        db.ensure_schema(self.conn)
        self.addCleanup(self.conn.close)
        self._seed()

    def _seed(self):
        self.conn.executescript(
            "INSERT INTO sessions(session_id, project_key, project, day, agent, turns,"
            " toolcalls, first_ts, last_ts, created_ts) VALUES"
            f" ('{MEASURED_A}','-p--p2-a','/home/user/P','20231114','builder',3,2,"
            f"  {A_START},{A_END},{A_START}),"
            f" ('{MEASURED_B}','-p--p2-a','/home/user/P','20231115','reviewer',1,1,"
            f"  {B_START},{B_END},{B_START}),"
            f" ('{DERIVED_C}','-p--p2-b',NULL,'20231116','builder',4,0,"
            f"  NULL,NULL,{C_CREATED}),"
            f" ('{UNDATED_D}','-p--p2-b',NULL,NULL,NULL,2,0,NULL,NULL,NULL);"
            " INSERT INTO session_models(session_id, account, agent_label, model_id, mode)"
            f"  VALUES('{MEASURED_A}','acct-A','builder','agent_1__Model X_null',0),"
            f"         ('{MEASURED_B}','acct-A','reviewer','agent_2__Model Y_null',0),"
            f"         ('{DERIVED_C}','acct-A','builder','agent_1__Model X_null',0);"
            # A made four calls across two messages; B made one; C made one on an
            # unmeasured creation second; D made none at all.
            " INSERT INTO toolcall_events(session_id, message_id, toolcall_id, ts) VALUES"
            f"  ('{MEASURED_A}','m1','tc1',{A_START}),"
            f"  ('{MEASURED_A}','m1','tc2',{A_START + 1000}),"
            f"  ('{MEASURED_A}','m2','tc3',{A_END}),"
            f"  ('{MEASURED_A}','m2','tc4',{A_END}),"
            f"  ('{MEASURED_B}','m3','tc5',{B_START}),"
            f"  ('{DERIVED_C}','m4','tc6',{C_CREATED});"
            " INSERT INTO credit_events(source, ts, kind, remaining, generation) VALUES"
            "  ('/logs/a.log',1700000000000,'balance',1000.0,3),"
            "  ('/logs/a.log',1700000300000,'balance',940.0,4),"
            "  ('/logs/a.log',1700000300001,'skipped',NULL,4),"
            "  ('/logs/b.log',1700001000000,'balance',500.0,1);"
        )
        self.conn.commit()


class ToolcallSessionsTest(UsageBase):
    def _rows(self, **kw):
        return db.q_toolcall_sessions(self.conn, **kw)

    def _row(self, session_id, **kw):
        return {r["session_id"]: r for r in self._rows(**kw)}[session_id]

    def test_a_session_is_counted_not_named(self):
        """The row shape is the guarantee: no column can hold a tool name.

        Trae writes ``toolcall-<messageId>-<toolcallId>`` tags and nothing else readable,
        so the ids are counted and dropped. A new column carrying one would turn a count
        into a ranking the data cannot support, so the exact list is asserted here.
        """
        rows = self._rows()
        self.assertEqual(list(rows[0].keys()), TOOLCALL_COLUMNS)
        top = self._row(MEASURED_A)
        self.assertEqual(top["calls"], 4)        # four distinct tool-call tags
        self.assertEqual(top["messages"], 2)     # across two distinct message ids
        # No tool-call id survives anywhere in the row.
        flat = " ".join(str(v) for v in tuple(top))
        for toolcall_id in ("tc1", "tc2", "tc3", "tc4", "tc5", "tc6"):
            self.assertNotIn(toolcall_id, flat)

    def test_the_call_time_span_comes_from_the_tags_not_the_session(self):
        """`first_ts`/`last_ts` are the measured ends of the calls themselves.

        The session's own `last_ts` is what puts it in a window; these two say how far
        the calls reached, and conflating them would let a session's post-call idle time
        read as a call.
        """
        row = self._row(MEASURED_A)
        self.assertEqual(row["first_ts"], A_START)
        self.assertEqual(row["last_ts"], A_END)

    def test_a_session_that_called_nothing_is_absent(self):
        """A count of zero is not a row: the tab lists sessions that called something."""
        ids = [r["session_id"] for r in self._rows()]
        self.assertNotIn(UNDATED_D, ids)

    def test_the_newest_session_activity_leads_not_the_busiest(self):
        """Ordered by the session's own last call, so the list reads as recent work.

        A made four calls, C one, so "busiest ever" would lead with A. A is last here
        because C called most recently, which is the only ordering this tab is allowed to
        claim.
        """
        self.assertEqual([r["session_id"] for r in self._rows()],
                         [DERIVED_C, MEASURED_B, MEASURED_A])

    def test_the_window_rides_on_the_session_time_measured_or_derived(self):
        """`SESSION_TIME_S` admits a session whose only time came from its id."""
        self.assertEqual([r["session_id"]
                          for r in self._rows(start_ts=WIN_START, end_ts=WIN_END)],
                         [MEASURED_A])
        self.assertEqual([r["session_id"]
                          for r in self._rows(start_ts=C_CREATED, end_ts=C_CREATED + 1)],
                         [DERIVED_C])

    def test_a_derived_session_is_flagged_so_the_row_can_print_a_tilde(self):
        row = self._row(DERIVED_C)
        self.assertEqual(row["derived_ts"], 1)
        self.assertEqual(row["shown_ts"], C_CREATED)
        self.assertEqual(db.derived_mark(row["derived_ts"]), "~")

    def test_limit_is_applied_after_the_ordering(self):
        self.assertEqual([r["session_id"] for r in self._rows(limit=1)],
                         [DERIVED_C])


class UsageSummaryTest(UsageBase):
    def _summary(self, **kw):
        return db.q_usage_summary(self.conn, **kw)

    def test_all_time_totals_are_counts_of_what_the_writer_stored(self):
        s = self._summary()
        self.assertEqual(s["sessions"], 4)
        self.assertEqual(s["projects"], 2)      # distinct project_key, not decoded path
        self.assertEqual(s["turns"], 10)        # 3 + 1 + 4 + 2
        self.assertEqual(s["toolcalls"], 3)     # 2 + 1 + 0 + 0
        self.assertEqual(s["models"], 2)
        self.assertEqual(s["top_model"],
                         {"model_id": "agent_1__Model X_null", "sessions": 2})

    def test_a_window_excludes_sessions_outside_it(self):
        s = self._summary(start_ts=WIN_START, end_ts=WIN_END)
        self.assertEqual(s["sessions"], 1)
        self.assertEqual(s["projects"], 1)
        self.assertEqual(s["turns"], 3)
        self.assertEqual(s["toolcalls"], 2)
        self.assertEqual(s["models"], 1)
        self.assertEqual(s["top_model"],
                         {"model_id": "agent_1__Model X_null", "sessions": 1})

    def test_a_stored_zero_is_reported_as_zero(self):
        """The reverse of the dash rule: `turns`/`toolcalls` are never NULL.

        `window_count` would dash this zero because an undated session exists, but that
        is a *count* rule about rows the range cannot see. These totals are sums over
        rows it can see, so the stored 0 is a measurement and prints as one.
        """
        s = self._summary(start_ts=C_CREATED, end_ts=C_CREATED + 1)
        self.assertEqual(s["toolcalls"], 0)
        self.assertEqual(s["sessions"], 1)

    def test_unmeasured_stays_all_time_whatever_the_window(self):
        """A window never launders a derivation into a measurement.

        Two fixture sessions have no `last_ts`: one dated from its id, one not dated at
        all. Both are reported here and neither is reachable by changing the range.
        """
        s = self._summary(start_ts=WIN_START, end_ts=WIN_END)
        self.assertEqual(s["unmeasured"], 2)
        self.assertEqual(self._summary()["unmeasured"], 2)

    def test_an_empty_window_reports_zero_sessions_and_no_top_model(self):
        """A range that placed nothing says so with a real 0, not with a dash."""
        s = self._summary(start_ts=EMPTY_START, end_ts=EMPTY_END)
        self.assertEqual(s["sessions"], 0)
        self.assertIsNone(s["top_model"])


class CreditWindowTest(UsageBase):
    """The Tokens tab reads balances, so its one load-bearing rule is the lower bound."""

    def test_spent_is_a_lower_bound_and_a_skipped_sample_is_not_a_zero(self):
        rows = {r["ts"]: r for r in db.q_credits(self.conn)}
        self.assertEqual(rows[1700000300000]["spent_at_least"], 60)   # 1000 -> 940
        # The first sample has no predecessor, so the bound is 0 rather than a guess.
        self.assertEqual(rows[1700000000000]["spent_at_least"], 0)
        # The 'skipped' sample is not in the series at all: a 0 there would fabricate spend.
        self.assertNotIn(1700000300001, rows)
        self.assertEqual(len(db.q_credit_events(self.conn, kind="skipped")), 1)

    def test_a_grant_between_samples_never_becomes_a_negative_spend(self):
        self.conn.execute(
            "INSERT INTO credit_events(source, ts, kind, remaining, generation)"
            " VALUES('/logs/a.log',1700000400000,'balance',1200.0,5)")
        self.conn.commit()
        rows = {r["ts"]: r for r in db.q_credits(self.conn)}
        self.assertEqual(rows[1700000400000]["spent_at_least"], 0)    # balance went up


if __name__ == "__main__":
    unittest.main()