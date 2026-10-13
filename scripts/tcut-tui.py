#!/usr/bin/env python3
"""tcut-tui — interactive viewer for the Trae CN usage tracker.

Tabs: Dashboard · Skills · Agents · Plugins · MCP.

The tab set is cbut's, minus Tools, Tokens and Usage. Those three cannot be fed
from Trae CN's disk: snapshot tags carry toolcall ids but never a tool name, the
agent store is encrypted so no token count exists to read, and there is no
per-request record. docs/maintenance/trae-cn-format.md holds the measurements.
The session-level tables cbut has no room for were dropped on the same rule;
their rows stay indexed and reach the terminal through ``tcut sessions``,
``tcut projects``, ``tcut prompts`` and ``tcut memory``, and the credit balance
Trae does log sits in the Dashboard's Credits · sync panel.

Requires ``textual`` (see requirements.txt). The headless reports in
tcut-stats.py need no third-party packages; this file is the only place that
imports textual, so importing it without textual fails with a clear message
instead of a traceback.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tcut_db as db  # noqa: E402

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Grid, Horizontal, Vertical
    from textual.screen import ModalScreen, Screen
    from textual.widgets import (
        Button, Checkbox, DataTable, Footer, Input, Select, Static,
        TabbedContent, TabPane,
    )

    HAVE_TEXTUAL = True
except ImportError:  # pragma: no cover - exercised only without the dep
    HAVE_TEXTUAL = False


def ts(v):
    if not v:
        return "-"
    return datetime.fromtimestamp(v / 1000).strftime("%m-%d %H:%M")


def fmt_n(v):
    """Render a count, showing ``-`` for NULL (never a fabricated 0)."""
    if v is None:
        return "-"
    return f"{v:,}"


def clip(text, width):
    """Fit ``text`` into ``width`` cells, marking a cut with an ellipsis.

    The Dashboard's leaderboard lines are column-formatted (``{:<26}``), so a
    name longer than its field does not wrap — it pushes every column after it.
    Observed at 41 characters. Clipping keeps the columns aligned; the full name
    stays in the table on that entity's own tab.
    """
    s = str(text)
    return s if len(s) <= width else s[: width - 1] + "…"


def local_time(ms):
    """Local-time render of an epoch-ms value (query bounds stay in Unix ms)."""
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


# Range option list (values mirror tcut_db so the two stay in sync).
# Windows are whole local calendar days ending now ("Today", "2 days", …).
# "Custom…" is the escape hatch to the date picker; it is never stored as a
# tab's range (a picked range is a db.CustomWindow instead).
RANGE_OPTIONS = [(db.USAGE_RANGE_LABELS[k], k)
                 for k in ("1d", "2d", "3d", "7d", "30d", "all")] + [
    ("Custom…", "custom")]
CUSTOM_RANGE = "custom"
# Per-tab column order. Declared here rather than inline at ``add_columns``
# because the narrow-terminal plan needs the full list to compute the prefix it
# keeps, and a plan that cannot name the columns it dropped is a silent
# truncation wearing a guard's clothes.
#
# cbut's own tabs are usage counters (calls, ok, last used). Trae CN records no
# invocations per skill, plugin or MCP server — only what is installed — so the
# same tabs read as inventory here. Agents is the one table with a session count,
# because the agent label is written per session.
AGENTS_COLUMNS = ("agent", "kind", "sessions")
SKILLS_COLUMNS = ("skill", "source", "owner", "path")
PLUGINS_COLUMNS = ("plugin", "version", "source", "path")
MCP_COLUMNS = ("server", "source", "path")
# The sessions behind one entity. The subject is in the screen title, so it is not
# repeated in every row; the columns are the ones that read differently per session.
ENTITY_COLUMNS = ("when", "session", "turns", "calls", "model", "intent")
# kind -> the q_sessions filter it maps to.
ENTITY_FILTERS = {"project": "project", "agent": "agent", "model": "model_id"}
ENTITY_LABELS = {"project": "Project", "agent": "Agent", "model": "Model"}


if HAVE_TEXTUAL:

    class TopBar(Horizontal):
        """标题栏 + 共享时间范围选择器（取代 textual 的 Header）。

        去掉两个内置行为：点击不再切换 'tall' 高度；没有左上角图标，不会打开命令面板。
        只有主界面带选择器；详情屏用 with_range=False。
        """
        DEFAULT_CSS = """
        TopBar { dock: top; width: 100%; height: 1; background: $panel; color: $foreground; }
        TopBar > #topbar-title { width: 1fr; padding: 0 1; content-align: left middle;
                                 text-wrap: nowrap; text-overflow: ellipsis; }
        TopBar > #date-range { width: auto; min-width: 0; height: 1; border: none;
                               padding: 0 1; background: $panel; color: $foreground; }
        TopBar > #date-range:hover { background: $boost; }
        TopBar > #range { width: 30; }
        TopBar > #range SelectCurrent { border: none; padding: 0 1; background: $panel; }
        """

        def __init__(self, title: str, *, with_range: bool = False,
                     range_value: str = "7d", id: str | None = None):
            super().__init__(id=id)
            self._title = title
            self._with_range = with_range
            self._range_value = range_value

        def compose(self) -> ComposeResult:
            yield Static(self._title, id="topbar-title")
            if self._with_range:
                # A compact 📅 control showing the active tab's window; pressing it
                # opens the date picker (same as picking "Custom…" in the Select).
                yield Button("📅", id="date-range")
                yield Select(RANGE_OPTIONS, value=self._range_value,
                             allow_blank=False, id="range")

        def set_range_label(self, text: str) -> None:
            """Show the active tab's window on the 📅 control ('' hides it)."""
            try:
                btn = self.query_one("#date-range", Button)
            except Exception:
                return
            btn.label = f"📅 {text}" if text else "📅"
            btn.display = bool(text)
            # A Button does not re-lay-out when its label grows, so the control
            # kept the width it was built with ("📅 Today" = 10 cells) and cut
            # the longer span down to "📅 10-06" until the next full relayout.
            btn.refresh(layout=True)

    class TimeInput(Input):
        """A clock field you can scrub as well as type.

        Typing is the fast path (``00:00`` and ``9:5 PM`` are both understood);
        ↑/↓ and the mouse wheel step the value so it can be nudged without the
        keyboard. The step is a per-instance count of minutes, set by the
        picker's step selector, so one key press can move a minute, ten, or an
        hour. The value is re-rendered through ``db.format_time``, so what stays
        in the field is always the canonical 24-hour ``HH:MM``.
        """

        BINDINGS = [
            Binding("up", "nudge_up", "Later", show=False),
            Binding("down", "nudge_down", "Earlier", show=False),
        ]
        STEP = 1  # minutes per nudge, until the picker's step selector says otherwise

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.step = self.STEP

        def action_nudge_up(self) -> None:
            self._nudge(self.step)

        def action_nudge_down(self) -> None:
            self._nudge(-self.step)

        def on_mouse_scroll_up(self, event) -> None:
            self._nudge(self.step)
            event.stop()

        def on_mouse_scroll_down(self, event) -> None:
            self._nudge(-self.step)
            event.stop()

        def _nudge(self, minutes: int) -> None:
            try:
                hour, minute = db.parse_time(self.value)
            except ValueError:
                # An empty or half-typed field nudges from *now*, so the first
                # ↑/↓ yields a valid time instead of an error.
                now = datetime.now()
                hour, minute = now.hour, now.minute
            total = (hour * 60 + minute + minutes) % (24 * 60)
            self.value = db.format_time(total // 60, total % 60)
            self.cursor_position = len(self.value)

    class DateRangeModal(ModalScreen):
        """The custom date-range picker: preset chips, two cards, two grids.

        Left column: the shortcut chips, an editable START TIME and END TIME (a
        date plus a 24-hour time each), a quick-time row under each card, a
        nudge-step selector and the "end follows now" switch. Right column: a
        month calendar whose ‹ › step the month (and, at the year's ends, the
        year), with a 24-cell hour grid below it. Clicking a card makes it
        active; a day or an hour then writes into the active card — start and
        end are picked the same way, and the calendar and the grid are the two
        halves of one clock.

        Opened from the top bar's 📅 control or the Select's "Custom…". Confirm
        dismisses with a ``db.CustomWindow``; Cancel or Esc dismisses with
        ``None``. A blank start date means all time.
        """

        BINDINGS = [Binding("escape", "cancel", "Cancel")]
        CELLS = 42                       # 6 rows × 7 columns covers any month
        DOW = ("S", "M", "T", "W", "T", "F", "S")
        # (chip label, widget id, preset key). "Today" and "1d" both name the
        # single whole calendar day that our window model calls "1d".
        PRESETS = (
            ("Today", "dr-today", "1d"),
            ("1d", "dr-1d", "1d"),
            ("7d", "dr-7d", "7d"),
            ("14d", "dr-14d", "14d"),
            ("30d", "dr-30d", "30d"),
            ("All time", "dr-all", "all"),
        )
        # The quick-time row under each card. The start card offers the day's
        # edges and the common halves; the end card also offers ``now``, which
        # is the same thing as ticking "follows current time" — the two ends of
        # the same choice, one click each.
        QUICK_START = ("00:00", "06:00", "12:00", "18:00", "23:59")
        QUICK_END = ("now", "00:00", "12:00", "23:59")
        # The nudge selector: (label, minutes). ↑/↓ and the wheel move by the
        # selected step, so a day's edge is reachable without typing.
        STEPS = (("1m", 1), ("10m", 10), ("1h", 60))
        HOURS = 24

        DEFAULT_CSS = """
        DateRangeModal { align: center middle; overflow: auto; }
        /* Width budget, so the whole picker fits an 80-column terminal:
           1 border + 1 padding + 53 (left column, of which the six preset chips
           use 52) + 1 margin + 21 (7 day cells of 3, and 6 hour cells of 3) +
           1 padding + 1 border = 79. The day and hour cells are Statics, not
           Buttons: a Button renders a two-digit label as one digit at width 3. */
        #dr-box { width: auto; height: auto; border: round $primary;
                  background: $surface; padding: 1 1; }
        #dr-left { width: 53; height: auto; }
        #dr-presets { height: auto; }
        .dr-card { border: round $panel; height: auto; padding: 0 1; margin-top: 1; }
        .dr-card.-active { border: round $accent; background: $boost; }
        .dr-card-title { color: $text-muted; text-style: bold; }
        .dr-fields { height: auto; }
        #dr-start-date, #dr-end-date { width: 1fr; margin: 0 1 0 0; }
        /* An Input spends 6 cells on its border and its 0-2 padding, so 16 is
           what a 5-cell "23:59" needs with room to type over it. */
        #dr-start-time, #dr-end-time { width: 16; }
        /* The quick-time rows: one cell tall, so five chips + four chips cost
           two rows rather than six. 5 × (5 + 2 padding + 1 margin) = 40 ≤ 53. */
        #dr-start-quick, #dr-end-quick { height: auto; }
        #dr-follow { height: auto; }
        #dr-nudge { height: auto; }
        /* A bare Static in a Horizontal takes the whole row and pushes the
           buttons past the column (and off the modal), so the label is pinned
           to its own cells. */
        #dr-nudge .dr-card-title { width: 7; }
        #dr-actions { height: auto; align-horizontal: right; }
        #dr-cal { width: 21; height: auto; margin-left: 1; }
        #dr-cal-head { height: auto; align: center middle; }
        #dr-cal-month { width: 1fr; text-align: center; text-style: bold; }
        #dr-cal-grid { grid-size: 7; grid-gutter: 0; height: auto; }
        /* 6 columns of 3 = 18 of the 21 available, so the 24 hours land in 4
           rows under the month. */
        #dr-hour-grid { grid-size: 6; grid-gutter: 0; height: auto; margin-top: 1; }
        /* Every rule that touches a Button is scoped by an id: Button's own
           `Button:ansi.-style-default` selector outranks a bare class, so
           `.dr-day { border: none }` silently lost and the calendar rendered
           with tall borders and no room for the number. */
        #dr-presets Button { width: auto; min-width: 0; height: 3; border: none;
                             padding: 0 1; margin: 0 1 0 0; background: $boost;
                             color: $foreground; }
        #dr-start-quick Button, #dr-end-quick Button {
                             width: auto; min-width: 0; height: 1; border: none;
                             padding: 0 1; margin: 0 1 0 0; background: $boost;
                             color: $foreground; }
        #dr-nudge Button { width: auto; min-width: 0; height: 1; border: none;
                           padding: 0 1; margin: 0 1 0 0; background: $boost;
                           color: $foreground; }
        /* -selected, not -active: Button uses -active for its own 0.2s pressed
           effect and strips it on a timer, so the chosen step flickered off. */
        #dr-nudge Button.-selected { background: $accent; color: $text;
                                     text-style: bold; }
        #dr-actions Button { width: auto; min-width: 0; margin-left: 1; }
        #dr-cal-head Button { width: auto; min-width: 0; border: none;
                              background: $surface; color: $foreground; }
        #dr-cal-grid .dr-dow { text-align: center; color: $text-muted; }
        /* 3, not 4: a Static renders "30" at width 3, where a Button shows " 3 ".
           The clicks are read from the cell id in on_click. */
        #dr-cal-grid .dr-day { width: 3; height: 1; text-align: center;
                               background: $surface; color: $foreground; }
        #dr-cal-grid .dr-day.-other { color: $text-disabled; }
        #dr-cal-grid .dr-day.-today { color: $accent; text-style: bold; }
        #dr-cal-grid .dr-day.-selected { background: $accent; color: $text;
                                         text-style: bold; }
        #dr-hour-grid .dr-hour { width: 3; height: 1; text-align: center;
                                 background: $surface; color: $foreground; }
        #dr-hour-grid .dr-hour.-selected { background: $accent; color: $text;
                                           text-style: bold; }
        """

        def __init__(self, current, now_ms: int, id: str | None = None):
            super().__init__(id=id)
            self._current = current
            self._now = now_ms
            self._active = "start"       # which card the calendar writes into
            self._step = self.STEPS[0][1]   # minutes per ↑/↓ nudge
            self._view = datetime.fromtimestamp(now_ms / 1000).date().replace(day=1)
            # What we last wrote into each field, so a *user* edit can be told
            # from our own prefill/preset write (both post Input.Changed).
            self._written = {}

        def compose(self) -> ComposeResult:
            with Horizontal(id="dr-box"):
                with Vertical(id="dr-left"):
                    with Horizontal(id="dr-presets"):
                        for label, wid, _key in self.PRESETS:
                            yield Button(label, id=wid)
                    with Vertical(id="dr-start-card", classes="dr-card"):
                        yield Static("START TIME", classes="dr-card-title")
                        with Horizontal(classes="dr-fields"):
                            yield Input(placeholder="MM/DD/YYYY", id="dr-start-date")
                            yield TimeInput(placeholder="00:00", id="dr-start-time")
                        with Horizontal(id="dr-start-quick"):
                            for i, label in enumerate(self.QUICK_START):
                                yield Button(label, id=f"dr-start-quick-{i}")
                    with Vertical(id="dr-end-card", classes="dr-card"):
                        yield Static("END TIME", classes="dr-card-title")
                        with Horizontal(classes="dr-fields"):
                            yield Input(placeholder="MM/DD/YYYY", id="dr-end-date")
                            yield TimeInput(placeholder="00:00", id="dr-end-time")
                        with Horizontal(id="dr-end-quick"):
                            for i, label in enumerate(self.QUICK_END):
                                yield Button(label, id=f"dr-end-quick-{i}")
                    yield Checkbox("End time follows current time", True, id="dr-follow")
                    with Horizontal(id="dr-nudge"):
                        yield Static("step", classes="dr-card-title")
                        for label, minutes in self.STEPS:
                            yield Button(label, id=f"dr-step-{minutes}")
                    with Horizontal(id="dr-actions"):
                        yield Button("Cancel", id="dr-cancel")
                        yield Button("Confirm", variant="primary", id="dr-ok")
                with Vertical(id="dr-cal"):
                    with Horizontal(id="dr-cal-head"):
                        yield Button("‹", id="dr-prev")
                        yield Static("", id="dr-cal-month")
                        yield Button("›", id="dr-next")
                    with Grid(id="dr-cal-grid"):
                        for dow in self.DOW:
                            yield Static(dow, classes="dr-dow")
                        for i in range(self.CELLS):
                            # A Static, not a Button: a Button renders the
                            # two-digit label "30" as " 3 " at a 3-cell width,
                            # and widening every cell to 4 would not fit the
                            # calendar beside the cards. The day is read from
                            # the cell id in on_click instead.
                            yield Static("", id=f"dr-day-{i}", classes="dr-day")
                    with Grid(id="dr-hour-grid"):
                        for h in range(self.HOURS):
                            yield Static(f"{h:02d}", id=f"dr-hour-{h}",
                                         classes="dr-hour")

        def on_mount(self) -> None:
            self._prefill()
            # The reference popup's "Supports both date and time" note, on the
            # box's bottom border so it costs no extra row.
            self.query_one("#dr-box").border_subtitle = "Supports both date and time"
            self._set_active("start")
            self._render_steps()

        # -- prefill from the tab's current window --------------------------
        def _prefill(self) -> None:
            cur = self._current
            follow = True
            if isinstance(cur, db.CustomWindow):
                start, end, follow = cur.start_ms, cur.end_ms, cur.follow_now
            else:
                start, end = db.window_bounds(cur, self._now)
            self._set_field("#dr-start", start)
            # A following end shows *now*; a fixed one shows the stored bound.
            self._set_field("#dr-end", self._now if follow else end)
            self.query_one("#dr-follow", Checkbox).value = follow
            anchor = start if start is not None else self._now
            self._view = datetime.fromtimestamp(anchor / 1000).date().replace(day=1)

        def _set_field(self, prefix: str, ms) -> None:
            date_in = self.query_one(f"{prefix}-date", Input)
            time_in = self.query_one(f"{prefix}-time", Input)
            if ms is None:
                date_in.value = time_in.value = ""
            else:
                dt = datetime.fromtimestamp(ms / 1000)
                date_in.value = db.format_date(dt)
                time_in.value = db.format_time(dt.hour, dt.minute)
            self._written[date_in.id] = date_in.value
            self._written[time_in.id] = time_in.value
            self._render_hours()

        def _follows_now(self) -> bool:
            return self.query_one("#dr-follow", Checkbox).value

        # -- the calendar ----------------------------------------------------
        def _grid_start(self) -> date:
            """The date in cell 0: the first day of the view, back to Sunday."""
            lead = (self._view.weekday() + 1) % 7      # Sunday-first column
            return self._view - timedelta(days=lead)

        def _day_at(self, index: int) -> date:
            return self._grid_start() + timedelta(days=index)

        def _active_date(self):
            """The active card's typed date, or ``None`` if it is blank/bad."""
            try:
                return db.parse_date(
                    self.query_one(f"#dr-{self._active}-date", Input).value,
                    self._view.year).date()
            except ValueError:
                return None

        def _render_calendar(self) -> None:
            today = datetime.fromtimestamp(self._now / 1000).date()
            chosen = self._active_date()
            self.query_one("#dr-cal-month", Static).update(
                self._view.strftime("%B %Y"))
            for i in range(self.CELLS):
                day = self._day_at(i)
                cell = self.query_one(f"#dr-day-{i}", Static)
                cell.update(str(day.day))
                cell.set_class(day.month != self._view.month, "-other")
                cell.set_class(day == today, "-today")
                cell.set_class(day == chosen, "-selected")

        def _step_month(self, delta: int) -> None:
            month = self._view.month + delta
            year = self._view.year + (month - 1) // 12
            self._view = date(year, (month - 1) % 12 + 1, 1)
            self._render_calendar()

        # -- the hour grid ---------------------------------------------------
        def _active_time(self):
            """The active card's typed time as ``(hour, minute)``, or ``None``."""
            try:
                return db.parse_time(
                    self.query_one(f"#dr-{self._active}-time", Input).value)
            except ValueError:
                return None

        def _render_hours(self) -> None:
            """Mark the active card's hour in the 24-cell grid."""
            parsed = self._active_time()
            hour = parsed[0] if parsed else None
            for h in range(self.HOURS):
                self.query_one(f"#dr-hour-{h}", Static).set_class(
                    h == hour, "-selected")

        def _pick_hour(self, hour: int) -> None:
            """Write a clicked hour into the active card, keeping its minute.

            The grid is the calendar's other half: the day cells set the date,
            these set the hour, and both land in whichever card is active.
            """
            parsed = self._active_time()
            minute = parsed[1] if parsed else 0
            self._write_time(self._active, db.format_time(hour, minute))

        def _write_time(self, card: str, value: str) -> None:
            """Set one card's time field, and fix the end if that is the card."""
            if card == "end":
                # A chosen end time means a fixed end, not "now".
                self.query_one("#dr-follow", Checkbox).value = False
            self.query_one(f"#dr-{card}-time", Input).value = value
            self._written[f"dr-{card}-time"] = value
            self._render_hours()

        def _pick_day(self, index: int) -> None:
            """Write a clicked day into the active card."""
            day = self._day_at(index)
            if self._active == "end":
                # Choosing an end date means a fixed end, not "now".
                self.query_one("#dr-follow", Checkbox).value = False
            self.query_one(f"#dr-{self._active}-date", Input).value = db.format_date(day)
            self._written[f"dr-{self._active}-date"] = db.format_date(day)
            if (day.year, day.month) != (self._view.year, self._view.month):
                self._view = day.replace(day=1)
            self._render_calendar()

        def _set_active(self, which: str) -> None:
            self._active = which
            self.query_one("#dr-start-card").set_class(which == "start", "-active")
            self.query_one("#dr-end-card").set_class(which == "end", "-active")
            self._render_calendar()
            self._render_hours()

        # -- presets ---------------------------------------------------------
        def _apply_preset(self, key: str) -> None:
            start, _ = db.window_bounds(key, self._now)
            self._set_field("#dr-start", start)
            self.query_one("#dr-follow", Checkbox).value = True
            if start is not None:
                self._view = datetime.fromtimestamp(start / 1000).date().replace(day=1)
            self._render_calendar()

        def _apply_quick(self, card: str, label: str) -> None:
            """A quick-time chip: ``now`` re-follows the clock, a time fixes it."""
            if label == "now":
                self._set_field("#dr-end", self._now)
                self.query_one("#dr-follow", Checkbox).value = True
                self._render_hours()
                return
            hour, minute = db.parse_time(label)
            self._write_time(card, db.format_time(hour, minute))

        # -- nudge step ------------------------------------------------------
        def _set_step(self, minutes: int) -> None:
            self._step = minutes
            for wid in ("#dr-start-time", "#dr-end-time"):
                self.query_one(wid, TimeInput).step = minutes
            self._render_steps()

        def _render_steps(self) -> None:
            for _label, minutes in self.STEPS:
                self.query_one(f"#dr-step-{minutes}", Button).set_class(
                    minutes == self._step, "-selected")

        # -- confirm ---------------------------------------------------------
        def _confirm(self) -> None:
            follow = self._follows_now()
            year = self._view.year
            try:
                start = db.parse_datetime(
                    self.query_one("#dr-start-date", Input).value,
                    self.query_one("#dr-start-time", Input).value, year)
                end = None if follow else db.parse_datetime(
                    self.query_one("#dr-end-date", Input).value,
                    self.query_one("#dr-end-time", Input).value, year)
            except ValueError:
                self.notify("Dates are MM/DD/YYYY, times HH:MM (24-hour)",
                            severity="error")
                return
            if not follow and end is None:
                self.notify("Set an end date, or tick 'End follows current time'",
                            severity="error")
                return
            if start is not None and end is not None and end < start:
                self.notify("End is before start", severity="error")
                return
            self.dismiss(db.CustomWindow(start, end, follow))

        def action_cancel(self) -> None:
            self.dismiss(None)

        # -- events ----------------------------------------------------------
        def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
            if event.checkbox.id == "dr-follow" and event.value:
                # Ticking "follows current time" puts the end back on now.
                self._set_field("#dr-end", self._now)

        def on_input_changed(self, event: Input.Changed) -> None:
            # A *user* edit of an end field means a fixed end, so drop the
            # follow switch. Our own prefill/preset writes are ignored by
            # matching the value we recorded.
            wid = event.input.id or ""
            if wid.endswith("-time"):
                self._render_hours()      # a typed hour re-marks the grid
            if not wid.startswith("dr-end") or not self._follows_now():
                return
            if self._written.get(wid) == event.value:
                return
            self.query_one("#dr-follow", Checkbox).value = False

        def on_click(self, event) -> None:
            # A calendar day and an hour cell are Statics, so their clicks
            # arrive here rather than as a Button.Pressed — read the index from
            # the cell's id.
            wid = getattr(event.widget, "id", "") or ""
            if wid.startswith("dr-day-"):
                self._pick_day(int(wid.rsplit("-", 1)[1]))
                return
            if wid.startswith("dr-hour-"):
                self._pick_hour(int(wid.rsplit("-", 1)[1]))
                return
            # Clicking anywhere on a card makes it the calendar's target.
            node = event.widget
            while node is not None:
                if getattr(node, "has_class", None) and node.has_class("dr-card"):
                    self._set_active(
                        "start" if node.id == "dr-start-card" else "end")
                    return
                node = getattr(node, "parent", None)

        def on_descendant_focus(self, event) -> None:
            wid = getattr(event.control, "id", "") or ""
            if wid.startswith("dr-start"):
                self._set_active("start")
            elif wid.startswith("dr-end"):
                self._set_active("end")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            bid = event.button.id or ""
            preset = next((key for _l, wid, key in self.PRESETS if wid == bid), None)
            if preset is not None:
                self._apply_preset(preset)
            elif bid.startswith("dr-start-quick-"):
                self._apply_quick("start", self.QUICK_START[int(bid.rsplit("-", 1)[1])])
            elif bid.startswith("dr-end-quick-"):
                self._apply_quick("end", self.QUICK_END[int(bid.rsplit("-", 1)[1])])
            elif bid.startswith("dr-step-"):
                self._set_step(int(bid.rsplit("-", 1)[1]))
            elif bid == "dr-prev":
                self._step_month(-1)
            elif bid == "dr-next":
                self._step_month(1)
            elif bid == "dr-cancel":
                self.dismiss(None)
            elif bid == "dr-ok":
                self._confirm()


    class WideTableMixin:
        """The narrow-terminal column plan, shared by every host that owns a table.

        A rule that covers two of the eight tables is not a rule, so the mechanism
        lives here and each host declares its own ``WIDE_TABLES``. ``_wide_rows`` is
        created by each host's ``__init__`` — it must not be a class attribute, or two
        open screens would share one row cache.

        The numbers a host registers are measured on this machine, not derived: a column
        costs its content width plus a 2-cell gutter (``virtual_size.width ==
        sum(content_width) + 2 * n_columns``, checked on every table), and a table loses
        a fixed number of cells to its surroundings — 2 inside a tab pane, 0 on a pushed
        screen that spans the terminal.
        """

        CELL_COST = 2
        MIN_SHOWN = 2      # never narrow a table down to a single unnamed column
        # Measured on this machine's database, not guessed: skill / plugin / mcp
        # names and agent ids all fit well under 28, but project and inventory
        # paths run past it (the longest project path here is 74 cells). A cap at
        # 28 keeps every name whole and buys back the cells a path was spending.
        NAME_CAP = 28

        @property
        def name_cap(self) -> int:
            """The cap this host actually renders with.

            ``NAME_CAP`` is the shipped default, which the app shadows from the
            settings file. A screen pushed on top of the app has no config of its
            own, so it overrides this to read the app — otherwise a configured cap
            would silently apply to the tabs and not to the detail screens.
            """
            return self.NAME_CAP

        def _cap_cell(self, text: str) -> str:
            """Fit one cell to ``name_cap``, keeping the half that carries meaning.

            A path's beginning is the shared prefix (`/home/user/…` repeated down
            the column) and its end is what distinguishes the rows, so paths are
            capped from the left. Everything else — a skill, a plugin, an agent — is
            read from the start, so it is capped from the right.
            """
            cap = self.name_cap
            if len(text) <= cap:
                return text
            keep = cap - 1
            return ("…" + text[-keep:]) if "/" in text else (text[:keep] + "…")

        def _fill(self, table, rows, key_index=0, key_kind=None, key_rows=None):
            # Remember the highlighted row by its ROW KEY, not by index: a
            # re-sort between refreshes must not move the highlight onto a
            # different entity (index-based restore would).
            cur_key = None
            cur = table.cursor_row
            if key_kind and table.row_count:
                try:
                    cur_key = table.coordinate_to_cell_key(
                        table.cursor_coordinate).row_key
                except Exception:
                    cur_key = None
            table.clear()
            n = 0
            for i, r in enumerate(rows):
                # NULL renders as "-", matching fmt_n (never a blank cell).
                cells = [("-" if c is None else str(c)) for c in r]
                key = None
                if key_kind:
                    # key_index may be a single index or a tuple of indices for
                    # a composite (unique) key, e.g. mcp -> (server, tool).
                    # ``key_rows`` carries the UNCAPTED values: two entities whose
                    # names share the visible prefix render identically and must
                    # still route apart, so the key cannot come from the cell.
                    idx = (key_index if isinstance(key_index, (tuple, list))
                           else (key_index,))
                    src = key_rows[i] if key_rows is not None else r
                    key = "\t".join([key_kind] + [str(src[j]) for j in idx])
                table.add_row(*cells, key=key)
                n += 1
            if cur_key is not None and cur_key in table.rows:
                table.move_cursor(row=table.get_row_index(cur_key))
            elif not key_kind and 0 <= cur < n:
                # Unkeyed tables keep the old index-based restore.
                table.move_cursor(row=cur)

        def _fill_or_empty(self, table, rows, empty_msg, key_index=0,
                           key_kind=None, key_rows=None):
            """Fill a table, or show an explicit empty-state row.

            An empty tab must never render a blank region. The empty row carries
            no key, so selecting it is a no-op.
            """
            if rows:
                self._fill(table, rows, key_index=key_index, key_kind=key_kind,
                           key_rows=key_rows)
            else:
                table.clear()
                table.add_row(empty_msg, *(["-"] * (len(table.columns) - 1)))

        @staticmethod
        def _column_widths(labels, rows):
            """What DataTable will charge for each column: label or widest cell."""
            return [max(len(str(label)),
                        max((len(str(r[i])) for r in rows), default=0))
                    for i, label in enumerate(labels)]

        def _set_columns(self, table, cols) -> None:
            if [str(c.label) for c in table.columns.values()] == list(cols):
                return
            table.clear(columns=True)
            table.add_columns(*cols)

        def _fill_wide(self, table_id, rows, empty_msg, key_index=0, key_kind=None,
                       width=None, key_rows=None):
            """Fill a wide table with the longest prefix of columns that fits.

            Prefix, not priority re-ordering: every table is already ordered most
            essential first (the name, then the counts, then the prose), so
            dropping the tail is the plan. The cells past the right edge used to
            be cut mid-label with no keyboard way to reach them.

            ``key_rows`` carries the un-truncated values a key is built from when
            the key is not among the visible cells — the Sessions tab's
            ``session_id`` rides there, so a row can open its own detail without
            spending a column on it. It defaults to the visible rows.
            """
            table = self.query_one(f"#{table_id}", DataTable)
            labels, note_id, chrome = self.WIDE_TABLES[table_id]
            self._wide_rows[table_id] = (rows, empty_msg, key_index, key_kind,
                                         key_rows)
            note = self.query_one(f"#{note_id}", Static)
            width = width or self.size.width or table.region.width
            if not width or not rows:
                # Either the first layout has not happened yet (both are 0, and
                # planning against 0 would drop everything) or there is nothing to
                # protect: an empty-state row spans the whole label set.
                self._set_columns(table, labels)
                self._fill_or_empty(table, rows, empty_msg, key_index, key_kind,
                                    key_rows=key_rows)
                note.update("")
                note.display = False
                if not width:
                    self.call_after_refresh(self._plan_wide_tables)
                return
            raw = [[("-" if c is None else str(c)) for c in r] for r in rows]
            shown = [[self._cap_cell(c) for c in rr] for rr in raw]
            capped = any(a != b for rr, ss in zip(raw, shown) for a, b in zip(rr, ss))
            full = self._column_widths(labels, raw)
            budget = width - chrome
            if sum(full) + self.CELL_COST * len(labels) <= budget:
                # Everything fits at its real length, so the cap stays out: a wide
                # terminal has no reason to lose characters, and "widen to N" would
                # otherwise promise a number that buys nothing.
                self._set_columns(table, labels)
                self._fill_or_empty(table, raw, empty_msg, key_index, key_kind,
                                    key_rows=key_rows)
                note.update("")
                note.display = False
                return
            widths = self._column_widths(labels, shown)
            keep = len(labels)
            while keep > self.MIN_SHOWN and sum(widths[:keep]) + self.CELL_COST * keep > budget:
                keep -= 1
            self._set_columns(table, labels[:keep])
            self._fill_or_empty(table, [r[:keep] for r in shown],
                                empty_msg, key_index, key_kind,
                                key_rows=key_rows if key_rows is not None else rows)
            cap_note = f" · cells capped at {self.name_cap}" if capped else ""
            if keep >= len(labels):
                # Nothing is hidden, so the only thing worth saying is that
                # characters were cut — and the full value only comes back at the
                # width named below, which is why it has to be said out loud.
                note.update(f"cells capped at {self.name_cap}" if capped else "")
                note.display = capped
                return
            cuts = sum(widths[:keep]) + self.CELL_COST * keep > budget
            note.update(f"{keep} of {len(labels)} columns · hidden: "
                        f"{', '.join(labels[keep:])} · widen to "
                        f"{sum(full) + self.CELL_COST * len(labels) + chrome}"
                        + (" · even these are cut" if cuts else "")
                        + cap_note)
            note.display = True

        def _plan_wide_tables(self, width=None) -> None:
            """Re-plan from the cached rows — a resize must not re-query."""
            for table_id, (rows, empty_msg, key_index, key_kind,
                           key_rows) in list(self._wide_rows.items()):
                self._fill_wide(table_id, rows, empty_msg,
                                key_index=key_index, key_kind=key_kind,
                                width=width, key_rows=key_rows)

    class SessionScreen(Screen):
        """One session's full detail, pushed when a Sessions row is selected.

        Trae's memory layer writes prose, not call records: the intent, the
        outcome, the model's own action list, what it says it learned, and the
        topic lines. This screen renders all of it. A plain ``Screen`` (not the
        ``WideTableMixin``) because the detail is a scrolling label/value list,
        not a wide table — so it needs neither the column plan nor a registered
        ``DataTable``.
        """

        BINDINGS = [Binding("escape,q", "app.pop_screen", "Back")]

        def __init__(self, session_id: str):
            super().__init__()
            self.session_id = str(session_id)

        def compose(self) -> ComposeResult:
            yield TopBar(f"Session · {self.session_id[:12]}")
            with Vertical(id="session-body"):
                yield Static(f"[b]Session[/b] · {self.session_id}",
                             id="session-title")
            yield Footer()

        def on_mount(self) -> None:
            self.title = f"Session: {self.session_id[:12]}"
            conn = db.open_db(self.app.db_path, readonly=True)
            try:
                row = db.q_session(conn, self.session_id)
                actions = db.q_session_actions(conn, self.session_id)
                learned = db.q_session_learned(conn, self.session_id)
                topics = db.q_topics(conn, self.session_id)
                models = db.q_session_models(conn, self.session_id)
            finally:
                conn.close()
            body = self.query_one("#session-body")
            if row is None:
                body.mount(Static("session not found", classes="sess-value"))
                return
            for label, value in self._summary_rows(row, models):
                body.mount(Horizontal(Static(label, classes="sess-label"),
                                      Static(value, classes="sess-value")))
            cap = self.app.DETAIL_LIMIT
            self._mount_list(body, "actions", [a["text"] for a in actions[:cap]])
            self._mount_list(body, "learned", [a["text"] for a in learned[:cap]])
            self._mount_list(body, "topics",
                             [f"{ts(t['ts'])}  {t['summary']}" for t in topics[:cap]])

        @staticmethod
        def _summary_rows(row, models=()):
            """``(label, text)`` for a session's scalar fields, in reading order.

            NULL renders as "-" (never a fabricated 0). ``intent``/``outcome``
            are prose; they are absent when ``store_content`` is off. ``models``
            is one line per agent label, because a session can carry two.
            """
            def when(v):
                return "-" if not v else local_time(v)
            rows = [
                ("project", row["project"] or row["project_key"] or "-"),
                ("agent", row["agent"] or "-"),
                ("day", row["day"] or "-"),
            ]
            for m in models:
                rows.append((f"model · {m['agent_label']}", m["model_id"]))
            if not models:
                rows.append(("model", "-"))
            rows += [
                ("turns", fmt_n(row["turns"])),
                ("tool calls", fmt_n(row["toolcalls"])),
                ("span", f"{when(row['first_ts'])} → {when(row['last_ts'])}"),
                ("intent", row["intent"] or "-"),
                ("outcome", row["outcome"] or "-"),
            ]
            return rows

        @staticmethod
        def _mount_list(body, heading: str, items) -> None:
            """Mount a titled bullet list, or nothing when it is empty."""
            items = [i for i in items if i]
            if not items:
                return
            body.mount(Static(f"[b]{heading}[/b]", classes="sess-heading"))
            for text in items:
                body.mount(Static(f"  • {text}", classes="sess-item"))

    class EntityScreen(WideTableMixin, Screen):
        """The sessions behind one project, agent or model.

        Every table already stamped its rows with a `key_kind`, but the app's
        row-selected handler only understood `session` — so Enter did nothing on the
        Projects, Agents, Skills, Plugins, MCP, Prompts and Memory tabs while the
        registry made the rows look routable. This is the drill-down cbut has:
        click a project, get its sessions; click a session inside, get its detail.

        Kinds Trae cannot support (a skill, a plugin, an mcp server) are refused out
        loud in the app's handler rather than left silent: an unresponsive key reads
        as a broken terminal, not as absent data.
        """

        BINDINGS = [Binding("escape,q", "app.pop_screen", "Back")]

        WIDE_TABLES = {"t-entity": (ENTITY_COLUMNS, "colnote-entity", 0)}

        def __init__(self, kind: str, value: str, start=None, end=None,
                     window_label: str = ""):
            super().__init__()
            self.kind = str(kind)
            self.value = str(value)
            # The window the row was read from. Without it this screen listed every
            # session the agent ever had while the tab above it printed a count for
            # the range — two numbers for one row, disagreeing on the same screen.
            self.start = start
            self.end = end
            self.window_label = window_label or ""
            # Per-host, not a class attribute: two open screens must not share one
            # row cache (the mixin's contract).
            self._wide_rows = {}

        @property
        def name_cap(self) -> int:
            # A pushed screen has no config of its own; reading the app's is what
            # makes a configured cap apply here too.
            return self.app.name_cap

        def compose(self) -> ComposeResult:
            label = ENTITY_LABELS.get(self.kind, self.kind)
            yield TopBar(f"{label} · {clip(self.value, 44)}")
            with Vertical(id="entity-body"):
                yield Static(f"[b]{label}[/b] · {self.value}"
                             + (f" · {self.window_label}" if self.window_label else ""),
                             id="entity-title")
                yield Static(id="entity-summary")
                yield Static(id="colnote-entity", classes="col-note")
                yield DataTable(id="t-entity", zebra_stripes=True)
            yield Footer()

        def on_mount(self) -> None:
            self.title = f"{self.kind}: {self.value[:32]}"
            for tid, (cols, _note, _chrome) in self.WIDE_TABLES.items():
                table = self.query_one(f"#{tid}", DataTable)
                table.cursor_type = "row"
                table.add_columns(*cols)
            self._reload()

        def _summary_line(self, s) -> str:
            """One line of windowed totals, over exactly the rows this screen lists.

            The span marks itself when an edge came from a session id rather than from a
            measured activity time: `first_measured` aggregates only measured rows, so an
            edge that differs from it is a derived position, and a header that prints the
            two identically turns a derivation into a fact.
            """
            if not s["sessions"]:
                return (f"no sessions · {self.window_label}" if self.window_label
                        else "no sessions recorded")
            first = (db.derived_mark(s["first_ts"] != s["first_measured"])
                     + ts(s["first_ts"]))
            last = (db.derived_mark(s["last_ts"] != s["last_measured"])
                    + ts(s["last_ts"]))
            # `projects` is the one total that can be unmeasurable: 28 of this machine's 49
            # sessions carry no project key at all, so a 0 there is the absence of a field,
            # not a counted none. turns/toolcalls are stored counts (never NULL in the real
            # index) and their 0 is a real reading.
            line = (" · ".join([db.count_n(s["sessions"], "session"),
                                db.count_n(s["turns"], "turn"),
                                db.count_n(s["toolcalls"], "tool call"),
                                db.window_count(s["projects"], s["projects_missing"],
                                                "project")])
                    + f" · {first} → {last}")
            return f"{line} · {self.window_label}" if self.window_label else line

        def _reload(self) -> None:
            conn = db.open_db(self.app.db_path, readonly=True)
            # One argument dict, unpacked into both queries: the header's numbers are
            # only worth printing if they are the same set of rows the table shows.
            scope = {"start_ts": self.start, "end_ts": self.end,
                     ENTITY_FILTERS[self.kind]: self.value}
            try:
                found = db.q_sessions(conn, **scope)
                totals = db.q_entity_totals(conn, **scope)
            except sqlite3.Error as exc:
                self.app._report_query_error(exc)
                return
            finally:
                conn.close()
            self.query_one("#entity-summary", Static).update(self._summary_line(totals))
            rows = [[db.derived_mark(r["derived_ts"]) + ts(r["shown_ts"]),
                     r["session_id"][:12], f"{r['turns']:,}",
                     f"{r['toolcalls']:,}", r["model_id"] or "-",
                     r["intent"] or "-"] for r in found]
            empty = (f"No sessions for this {self.kind} in {self.window_label}"
                     if self.window_label else
                     f"No sessions recorded for this {self.kind}")
            self._fill_wide("t-entity", rows, empty,
                            key_kind="session",
                            key_rows=[[r["session_id"]] for r in found])

        def on_resize(self, event) -> None:  # textual.events.Resize
            # Same contract as the tabs: a screen the user narrowed must re-plan, or
            # the column it dropped stays dropped when the terminal widens again.
            self._plan_wide_tables(event.size.width)

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            # Stop here: the app's handler would push a second screen for the same
            # key, and the row keys of this screen are sessions by design.
            key = event.row_key.value
            if key and key.startswith("session\t"):
                event.stop()
                # The screen pops (its own binding); pushing is the app's job —
                # `Screen` has no push_screen in this Textual release.
                self.app.push_screen(SessionScreen(key.partition("\t")[2]))

    class TrackerApp(WideTableMixin, App):
        CSS = """
        #session-title { padding: 1 2; }
        DataTable { height: 1fr; }
        #status { padding: 0 2; color: $text-muted; }
        /* The session detail: a scrolling label/value list plus bullet lists. The
           label column is fixed so long prose values wrap in the 1fr column. */
        #entity-title { padding: 1 2; }
        /* The drill-down's aggregate line: same gutter as the title it sits under,
           muted so it reads as a caption and not as another heading. */
        #entity-summary { padding: 0 2; color: $text-muted; }
        #entity-body { height: 1fr; padding: 0 1; }
        #session-body { height: 1fr; overflow-y: auto; padding: 0 1; }
        .sess-label { width: 12; color: $text-muted; }
        .sess-value { width: 1fr; }
        .sess-heading { padding: 1 0 0 0; color: $accent; }
        .sess-item { width: 1fr; }
        /* The Dashboard is a stack of .dash-row rows; #dash-box scrolls. Each row
           is a Horizontal; .compact makes it two-up, .compact.stacked stacks it. */
        #dash-box { height: 1fr; padding: 0 1; overflow-y: auto; }
        .usage-panel {
            border: round $primary;
            padding: 0 1;
            margin: 0 1 0 0;
            width: 1fr;
            height: auto;
        }
        #panel-dash-inventory, #panel-dash-activity,
        #panel-dash-projects, #panel-dash-agents { margin: 0; }
        .panel-title { text-style: bold; color: $accent; }
        #dash-note { padding: 0 1; color: $text-muted; }
        /* One line per wide table, only when columns were dropped — an always-on
           note above a table that hides nothing is noise that costs a row. Auto
           height because a note that is itself cut off at the right edge would be
           the same defect it exists to report. */
        .col-note { padding: 0 1; color: $text-muted; height: auto; display: none; }
        #dash-activity { color: $accent; }
        #dash-activity-axis { color: $text-muted; }
        /* Two panels side by side need ~28 cells each (a 24-char line plus border
           and padding), so 2 x 28 = 56; below 60 a second column wraps a value
           mid-line and stacking is the only layout that fits. */
        .dash-row.compact { layout: grid; grid-size: 2; }
        .dash-row.compact.stacked { layout: vertical; }
        .dash-row.compact .usage-panel { width: 100%; margin: 0 0 1 0; }
        .dash-row { height: auto; margin: 0 0 1 0; }
        """
        # Pane ids in display order. Used for wrap-around tab cycling.
        TAB_IDS = [
            "tab-dashboard", "tab-skills", "tab-agents", "tab-plugins", "tab-mcp",
        ]
        # The tab shown on launch. The TopBar Select must start on this tab's
        # own range (see compose), or its mount-time Changed would overwrite
        # that tab's default before the user touches anything.
        INITIAL_TAB = "tab-dashboard"
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("r", "refresh", "Refresh"),
            Binding("s", "toggle_auto_sync", "Auto sync"),
            Binding("tab", "next_tab", "Next tab", priority=True),
            Binding("shift+tab", "previous_tab", "Prev tab", priority=True),
        ]
        TITLE = "Trae CN usage tracker"
        # No built-in header means no ctrl+p palette; disable it outright too.
        ENABLE_COMMAND_PALETTE = False

        DASH_TOP = 5            # rows in the Dashboard's Top projects / Top agents
        DETAIL_LIMIT = 200      # items on a session's action / learned / topic lists

        def __init__(self, db_path, clock=None, config=None):
            super().__init__()
            self.db_path = str(db_path)
            # Settings come from ~/.config/tcut/config.toml (or TCUT_CONFIG), with
            # the environment able to override one key. Tests pass a dict to avoid
            # reading a real file; a broken file raises ConfigError, which main()
            # turns into a message rather than a traceback.
            self.config = dict(db.DEFAULTS) if config is None else dict(config)
            self.DASH_TOP = self.config["top_n"]
            self.DETAIL_LIMIT = self.config["detail_limit"]  # session detail lists
            # Shadows WideTableMixin.NAME_CAP for this host and every screen pushed
            # on top of it; the property ``name_cap`` is what reads it.
            self.NAME_CAP = self.config["name_cap"]
            # Injectable wall clock (seconds since the epoch). Defaults to
            # time.time, so a real run is unchanged; tests pass a fixed value to
            # pin "now". The calendar-day windows are derived from this clock,
            # so without a pin a `now - 1h` fixture falls out of a Today window
            # when the suite runs in the first hour after local midnight.
            self._clock = clock or time.time
            self._auto_sync = True
            self._sync_running = False
            self._sync_pending = False
            self.sync_mod = None
            # Per-tab range state: each tab keeps its own window, so changing one
            # tab's range never moves another's. The Dashboard and the Agents tab
            # count sessions, so they have a window; the three inventory tabs have
            # no timestamp of their own, so they are all-time and their range
            # selector is hidden.
            self.tab_range = {
                "tab-dashboard": "7d", "tab-agents": "7d",
            }
            self._data_ready = False
            # table id -> (rows, empty message, key index, key kind, key rows)
            # for every wide table, so a resize can re-plan them without
            # re-querying.
            self._wide_rows = {}
            # Set from migrate() on mount: "" when the schema is usable,
            # otherwise the reason it is not ("newer", "failed: …").
            self._schema_note = ""
            # The status line is composed from these in one function
            # (`_status_line`), because several events change it — a full
            # refresh, a failed re-query, the `s` toggle — and a line overwritten
            # by one of them used to stay wrong until an unrelated refresh.
            self._overview = None            # db.overview() dict, or None
            self._status_note = ""           # last failure the bar is reporting
            self._last_sync = None           # epoch seconds of the last successful index
            # Bumped by every report, so a refresh can tell "nothing complained
            # during this call" from "this call cleared the old warning" without
            # comparing message text.
            self._report_seq = 0

        def compose(self) -> ComposeResult:
            yield TopBar(self.TITLE, with_range=True,
                         range_value=self.tab_range[self.INITIAL_TAB],
                         id="topbar")
            with TabbedContent(initial=self.INITIAL_TAB):
                with TabPane("Dashboard", id="tab-dashboard"):
                    yield Vertical(
                        # Row 1: session counts and the installed inventory.
                        Horizontal(
                            Vertical(
                                Static("Sessions", classes="panel-title"),
                                Static(id="dash-sessions"),
                                Static(id="dash-projects"),
                                Static(id="dash-turns"),
                                Static(id="dash-toolcalls"),
                                classes="usage-panel", id="panel-dash-sessions",
                            ),
                            Vertical(
                                Static("Inventory", classes="panel-title"),
                                Static(id="dash-inv-prompts"),
                                Static(id="dash-inv-agents"),
                                Static(id="dash-inv-skills"),
                                Static(id="dash-inv-plugins"),
                                Static(id="dash-inv-mcp"),
                                classes="usage-panel", id="panel-dash-inventory",
                            ),
                            classes="dash-row", id="dash-row-1",
                        ),
                        # Row 2: the leaderboards.
                        Horizontal(
                            Vertical(
                                Static("Top projects", classes="panel-title"),
                                Static(id="dash-top-projects"),
                                classes="usage-panel", id="panel-dash-projects",
                            ),
                            Vertical(
                                Static("Top agents", classes="panel-title"),
                                Static(id="dash-top-agents"),
                                classes="usage-panel", id="panel-dash-agents",
                            ),
                            Vertical(
                                Static("Top models", classes="panel-title"),
                                Static(id="dash-top-models"),
                                classes="usage-panel", id="panel-dash-models",
                            ),
                            classes="dash-row", id="dash-row-2",
                        ),
                        # Row 3: the per-day trend.
                        Horizontal(
                            Vertical(
                                Static("Sessions per day", classes="panel-title"),
                                Static(id="dash-activity"),
                                Static(id="dash-activity-axis"),
                                classes="usage-panel", id="panel-dash-activity",
                            ),
                            Vertical(
                                # cbut's Runtime panel counts completed/incomplete calls;
                                # Trae records no call status, so this holds the balance
                                # and the index's own freshness instead.
                                Static("Credits · sync", classes="panel-title"),
                                Static(id="dash-credits-latest"),
                                Static(id="dash-credits-spent"),
                                Static(id="dash-sync-last"),
                                Static(id="dash-sync-auto"),
                                classes="usage-panel", id="panel-dash-runtime",
                            ),
                            classes="dash-row", id="dash-row-3",
                        ),
                        Static(id="dash-note"),
                        id="dash-box",
                    )
                with TabPane("Skills", id="tab-skills"):
                    yield Static(id="colnote-skills", classes="col-note")
                    yield DataTable(id="t-skills", zebra_stripes=True)
                with TabPane("Agents", id="tab-agents"):
                    yield Static(id="colnote-agents", classes="col-note")
                    yield DataTable(id="t-agents", zebra_stripes=True)
                with TabPane("Plugins", id="tab-plugins"):
                    yield Static(id="colnote-plugins", classes="col-note")
                    yield DataTable(id="t-plugins", zebra_stripes=True)
                with TabPane("MCP", id="tab-mcp"):
                    yield Static(id="colnote-mcp", classes="col-note")
                    yield DataTable(id="t-mcp", zebra_stripes=True)
            yield Static("", id="status")
            yield Footer()

        def on_mount(self) -> None:
            # One source of column truth: the registry the plan reads is the registry
            # that creates the columns, so a table cannot gain a column the plan does
            # not know how to drop.
            for tid, (cols, _note, _chrome) in self.WIDE_TABLES.items():
                t = self.query_one(f"#{tid}", DataTable)
                t.cursor_type = "row"
                t.add_columns(*cols)
            # Best-effort schema upgrade: an old DB lacks the columns every usage
            # query needs. migrate() returns a status now, so a locked or damaged
            # file is named on the status line instead of showing an empty panel
            # as though that were the user's actual usage.
            note = db.migrate(self.db_path)
            self._schema_note = "" if note in ("current", "migrated") else note
            self._data_ready = True
            # Auto sync (incremental, ~30s) + UI refresh (~5s). Both are timers,
            # not subprocesses; the sync runs in a worker thread (see _do_sync).
            self.set_interval(self.config["sync_secs"], self._auto_sync_tick)
            self.set_interval(self.config["refresh_secs"], self._auto_refresh_tick)
            self.refresh_data()

        # --- tab cycling (uses the real TabbedContent.active API) -----------

        def _cycle_tab(self, delta: int) -> None:
            tc = self.query_one(TabbedContent)
            try:
                idx = self.TAB_IDS.index(tc.active)
            except ValueError:
                idx = 0
            nxt = (idx + delta) % len(self.TAB_IDS)
            tc.active = self.TAB_IDS[nxt]

        def action_next_tab(self) -> None:
            self._cycle_tab(1)

        def action_previous_tab(self) -> None:
            self._cycle_tab(-1)

        # --- data fill / refresh --------------------------------------------



        def _set_status(self, msg: str) -> None:
            self.query_one("#status", Static).update(msg)

        # --- per-tab data fills ---------------------------------------------





        def _fill_agents(self, conn, start=None, end=None) -> None:
            rows = [[r["agent"], r["kind"] or "-",
                     db.window_count(r["sessions"], r["undated"])]
                    for r in db.q_agents(conn, start_ts=start, end_ts=end)]
            self._fill_wide("t-agents", rows, "No agents recorded",
                            key_kind="agent")

        def _fill_skills(self, conn, start=None, end=None) -> None:
            found = db.q_inventory(conn, "skill")
            self._fill_inventory(
                "t-skills", found,
                [[r["name"], r["source"] or "-", r["owner_plugin"] or "-",
                  r["path"] or "-"] for r in found],
                "No skills installed")

        def _fill_plugins(self, conn, start=None, end=None) -> None:
            found = db.q_inventory(conn, "plugin")
            self._fill_inventory(
                "t-plugins", found,
                [[r["name"], r["version"] or "-", r["source"] or "-",
                  r["path"] or "-"] for r in found],
                "No plugins installed")

        def _fill_mcp(self, conn, start=None, end=None) -> None:
            found = db.q_inventory(conn, "mcp")
            self._fill_inventory(
                "t-mcp", found,
                [[r["name"], r["source"] or "-", r["path"] or "-"]
                 for r in found],
                "No MCP servers installed")

        def _fill_inventory(self, table_id, found, rows, empty_msg) -> None:
            """Fill an inventory tab. No window: the inventory has no timestamps.

            The row key is ``(name, owner_plugin)`` — the inventory's own primary
            key — so two same-named entries from different owners do not collide.
            """
            self._fill_wide(
                table_id, rows, empty_msg, key_index=(0, 1), key_kind="inv",
                key_rows=[[r["name"], r["owner_plugin"]] for r in found])

        # pane id -> the fill method for that tab (dashboard handled separately).
        _PANE_FILL = {
            "tab-dashboard": "_fill_dashboard",
            "tab-skills": "_fill_skills", "tab-agents": "_fill_agents",
            "tab-plugins": "_fill_plugins", "tab-mcp": "_fill_mcp",
        }

        def refresh_data(self, conn=None) -> None:
            """Full refresh: every tab + the status bar.

            Used on mount and after a sync that actually indexed new files. Pass
            an existing readonly ``conn`` to avoid opening a second one.
            """
            seq = self._report_seq
            own = conn is None
            if own:
                try:
                    conn = db.open_db(self.db_path, readonly=True)
                except sqlite3.Error as exc:
                    self._report_query_error(exc)
                    return
            try:
                self._sync_range_widget()      # initial 📅 label + Select value
                # Each tab is filled with its own window, so one tab's range
                # never moves another's. The three inventory tabs (Skills /
                # Plugins / MCP) are all-time — they carry no timestamp of their
                # own, so their range selector is hidden.
                self._fill_dashboard(conn, *self._bounds_for("tab-dashboard"))
                self._fill_skills(conn)
                self._fill_agents(conn, *self._bounds_for("tab-agents"))
                self._fill_plugins(conn)
                self._fill_mcp(conn)
                o = db.overview(conn)          # status bar stays all-time
            except sqlite3.Error as exc:
                # This runs during on_mount: letting it raise kills the app
                # before it draws a frame, and the other alternative — panels of
                # zeros — is indistinguishable from a quiet day.
                self._report_query_error(exc)
                return
            finally:
                if own:
                    conn.close()
            self._overview = o
            if self._report_seq == seq:
                # Nothing complained during a refresh that re-queried every tab,
                # so any warning the bar was carrying has been disproved.
                self._status_note = ""
            self._set_status(self._status_line())

        def _status_line(self) -> str:
            """The status line, composed from what the app currently knows.

            One composer because `s`, a failed re-query and a sync with nothing to
            index each used to overwrite the line with a message that then stayed
            there — "Syncing…" outliving a finished sync was the visible one.
            """
            if self._overview is None:
                return f"! {self._status_note}" if self._status_note else ""
            o = self._overview
            status = (
                f"db={self.db_path} · {db.count_n(o['sessions'], 'session')} · "
                f"{db.count_n(o['projects'], 'project')} · "
                f"{db.count_n(o['turns'], 'turn')} · "
                f"{db.count_n(o['toolcalls'], 'tool call')} · "
                f"{db.count_n(o['skills'], 'skill')} · "
                f"{db.count_n(o['agents'], 'agent')} · "
                f"{o['models']:,} models · {o['credits']:,} credits · "
                f"{o['mcp']:,} mcp · "
                f"last {ts(o['last_ts'])}"
            )
            if not self._auto_sync:
                status += " · auto-sync OFF"
            if o["unparsed_records"]:
                # Keep the status line honest: panels showing 0 while records
                # went unclaimed means the format moved, not that usage stopped.
                status += f" · ! {db.count_n(o['unparsed_records'], 'record')} unparsed"
            if self._schema_note:
                status += f" · schema: {self._schema_note}"
            if self._status_note:
                # Every number above is the last known one, not the current one.
                status += f" · ! {self._status_note}"
            return status

        def _report_query_error(self, exc: sqlite3.Error) -> None:
            """Name a failed re-query instead of leaving the old page on screen.

            A tab that could not be refreshed keeps its previous rows, which look
            exactly like usage the user still has; a locked or damaged file has to
            say so in the one place the user reads.
            """
            self._report_seq += 1
            self._status_note = f"{type(exc).__name__}: {exc}"
            self._set_status(self._status_line())

        def _refresh_active_tab(self, conn=None) -> None:
            """Refresh only the visible tab (5s timer / tab activation).

            Hidden tabs are left alone; they are populated when the user opens
            them (see ``on_tabbed_content_tab_activated``).
            """
            if not self._data_ready:
                return
            seq = self._report_seq
            pane = self.query_one(TabbedContent).active
            own = conn is None
            if own:
                try:
                    conn = db.open_db(self.db_path, readonly=True)
                except sqlite3.Error as exc:
                    self._report_query_error(exc)
                    return
            try:
                fn = self._PANE_FILL.get(pane)
                if fn:
                    # Prompts / inventory / Memory ignore their bounds (all-time).
                    getattr(self, fn)(conn, *self._bounds_for(pane))
            except sqlite3.Error as exc:
                self._report_query_error(exc)
                return
            finally:
                if own:
                    conn.close()
            if self._report_seq == seq and self._status_note:
                # These queries went through and nothing in them complained, so
                # the bar's warning has been disproved. No full refresh is owed:
                # a hidden tab is re-queried the moment the user opens it.
                self._status_note = ""
                self._set_status(self._status_line())

        def on_tabbed_content_tab_activated(
                self, event: TabbedContent.TabActivated) -> None:
            # Populate the tab the user just switched to (hidden tabs are not
            # polled by the 5s timer) and point the range Select at its window.
            if self._data_ready:
                self._sync_range_widget()
                self._refresh_active_tab()

        # --- narrow-terminal column plan ------------------------------------

        # Below COMPACT_WIDTH the dashboard rows sit two-up instead of side by
        # side; below STACKED_WIDTH a second column would wrap a value mid-line
        # and the row stacks. A panel line is 24 columns of content plus 2 border
        # and 2 padding, so a two-up cell needs 28, and the region is 2 cells
        # narrower than the terminal: two columns stop fitting below 60.
        COMPACT_WIDTH = 112
        STACKED_WIDTH = 60

        # Every table the plan manages: id -> (its columns in display order, the
        # note that names what the plan dropped, the cells it loses to its
        # surroundings). Chrome is 2 for a table sitting directly in a tab pane —
        # measured at 80/100/160 columns, not derived. A table that fits keeps
        # every column and shows no note, so registering one that does not need
        # the plan costs nothing.
        WIDE_TABLES = {
            "t-skills": (SKILLS_COLUMNS, "colnote-skills", 2),
            "t-agents": (AGENTS_COLUMNS, "colnote-agents", 2),
            "t-plugins": (PLUGINS_COLUMNS, "colnote-plugins", 2),
            "t-mcp": (MCP_COLUMNS, "colnote-mcp", 2),
        }

        def _apply_responsive_layout(self, width=None) -> None:
            # Dashboard rows sit two-up on wide terminals and stack below
            # STACKED_WIDTH, where a second column would wrap a value mid-line.
            if width is None:
                width = self.size.width
            try:
                compact = width < self.COMPACT_WIDTH
                stacked = width < self.STACKED_WIDTH
                for el in self.query(".dash-row"):
                    el.set_class(compact, "compact")
                    el.set_class(stacked, "stacked")
            except Exception:
                pass

        def on_resize(self, event) -> None:  # textual.events.Resize
            # event.size carries the NEW size (self.size still lags here).
            self._apply_responsive_layout(event.size.width)
            self._plan_wide_tables(event.size.width)

        def _range_of(self, pane):
            """The window key for a pane, or ``None`` when it has no window.

            Prompts, the inventory tabs (Skills / Plugins / MCP) and Memory carry
            no timestamp of their own, so they are not in ``self.tab_range`` and
            their range selector is hidden.
            """
            return self.tab_range.get(pane)

        def _now_ms(self) -> int:
            """The current time in epoch milliseconds, via the injectable clock."""
            return int(self._clock() * 1000)

        def _bounds_for(self, pane):
            """``(start_ms, end_ms)`` for a pane's **own** window, from now.

            Never cached: every refresh derives the window from the current
            time, so a long-running app does not drift. ``None`` as the start
            means all-time (a tab with no window).
            """
            rng = self._range_of(pane)
            now = self._now_ms()
            if rng is None:
                return None, now
            if isinstance(rng, db.CustomWindow):
                return rng.start_ms, (now if rng.follow_now else rng.end_ms)
            return db.window_bounds(rng, now)

        def _sync_range_widget(self) -> None:
            """Point the shared range Select at the active tab's own window.

            Every windowed tab keeps its own range (``self.tab_range``), so
            switching tabs shows that tab's range, not the one you last picked
            elsewhere. A tab with no window (``_range_of`` returns ``None``)
            hides the Select. Setting ``Select.value`` posts a ``Changed``
            message, which ``on_select_changed`` ignores when it already matches
            the active tab's range (so this never re-triggers a refresh loop).
            """
            try:
                sel = self.query_one("#range", Select)
            except Exception:
                return
            pane = self.query_one(TabbedContent).active
            value = self._range_of(pane)
            if value is None:
                sel.display = False
                return
            sel.display = True
            # A custom window is shown as "Custom…" in the Select, with the span
            # itself on the 📅 control next to it.
            target = CUSTOM_RANGE if isinstance(value, db.CustomWindow) else value
            if target is not None and sel.value != target:
                sel.value = target
            self._set_date_label(db.window_label(value))

        def _set_date_label(self, text: str) -> None:
            try:
                self.query_one("#topbar", TopBar).set_range_label(text)
            except Exception:
                pass

        # --- Dashboard page ------------------------------------------------

        @staticmethod
        def _panel_line(label: str, value: str) -> str:
            # Fixed-width label + right-aligned value keeps the panels aligned
            # without relying on text-align. 12 + 12 = 24 columns, so the line
            # does not wrap inside a quarter-width panel at 120+ columns.
            return f"[dim]{label:<12}[/dim]{value:>12}"

        def _fill_dashboard(self, conn, start=None, end=None) -> None:
            """Render every Dashboard panel for this tab's own window.

            All panels reflect the Dashboard's window only — the other tabs are
            untouched. Every query takes the same ``(start, end)`` so the tab
            always agrees with itself.
            """
            try:
                kpi = db.q_kpi(conn, start, end)
                daily = db.q_activity_daily(conn, start, end)
                projects = db.q_top_projects(conn, self.DASH_TOP, start, end)
                agents = db.q_top_agents(conn, self.DASH_TOP, start, end)
                models = db.q_top_models(conn, self.DASH_TOP, start, end)
                credits = db.q_credits(conn, start_ts=start, end_ts=end)
            except sqlite3.Error as e:
                self.query_one("#dash-note", Static).update(
                    f"dashboard query failed ({e}); run: tcut sync")
                self._report_query_error(e)
                return
            self._render_dashboard_sessions(kpi)
            self._render_dashboard_inventory(kpi)
            # Every leaderboard sentence that is not a number has to name the range it
            # is blaming, and the range is this tab's own — never the top bar's.
            window = db.window_label(self._range_of("tab-dashboard"))
            all_time = start is None and end is None
            span = "" if all_time else " in this range"
            self._render_dashboard_projects(
                projects, self._blank_text(kpi["sessions"], window, span,
                                           "has a project key"))
            self._render_dashboard_agents(
                agents, self._blank_text(kpi["sessions"], window, span,
                                         "names an installed agent"))
            self._render_dashboard_activity(daily, start, end)
            self._render_dashboard_models(
                models, self._blank_text(kpi["sessions"], window, span,
                                         "records a model selection"), all_time)
            self._render_dashboard_credits(credits)
            note = ("No sessions in this window — widen the range above."
                    if not (kpi["sessions"] or kpi["turns"] or kpi["toolcalls"])
                    else "Range: the top bar · this tab keeps its own window")
            if kpi["unmeasured"]:
                # One place that says what the `~` in every list means, sized to the
                # population it marks: Trae left these sessions with no measured time.
                note += (f" · {db.count_n(kpi['unmeasured'], 'session')}"
                         " with no measured time, dated from the session id (~)")
            self.query_one("#dash-note", Static).update(note)
            self._apply_responsive_layout()

        def _render_dashboard_models(self, rows, blank: str, all_time: bool) -> None:
            """Sessions per selected model — the only model ranking Trae supports."""
            top = rows[: self.DASH_TOP]
            if not top:
                # This query filters in SQL, so a model whose sessions all fall outside
                # the range is absent rather than zero. Under All time an empty result is
                # the literal truth — no session ever recorded a selection — and only a
                # bounded range has to work out whether it hid rows or the index has none.
                self.query_one("#dash-top-models", Static).update(
                    "no model selection recorded" if all_time else blank)
                return
            lines = [f"{i}. {clip(r['model_id'], 24):<24}"
                     f"{db.count_n(r['sessions'], 'session'):>12}"
                     for i, r in enumerate(top, 1)]
            self.query_one("#dash-top-models", Static).update("\n".join(lines))

        def _render_dashboard_credits(self, credits) -> None:
            """Balance level, spend lower bound, and how fresh the index is."""
            latest = credits[0]["remaining"] if credits else None
            spent = sum(c["spent_at_least"] or 0 for c in credits)
            self._put_panel("#dash-credits-latest", "Latest balance",
                            db.credit_num(latest))
            self._put_panel("#dash-credits-spent", "Spent at least",
                            db.credit_num(spent))
            # Labelled "session sync" because it is the app's own action, not the
            # file's history: a database the CLI indexed a minute ago legitimately
            # reads "-" here, and "Last sync" would make that look like a failure.
            self._render_sync_state()

        def _render_sync_state(self) -> None:
            """The two sync lines, from app state alone — no query, no window.

            They used to be redrawn only with the rest of the Dashboard, so a sync
            that indexed nothing (the common case) took the light-refresh path and
            left "Session sync not yet" on screen long after the timestamp changed.
            """
            self._put_panel("#dash-sync-last", "Session sync",
                            "not yet" if self._last_sync is None
                            else local_time(int(self._last_sync * 1000)))
            self._put_panel("#dash-sync-auto", "Auto sync",
                            "on" if self._auto_sync else "OFF")

        def _put_panel(self, wid: str, label: str, val: str) -> None:
            self.query_one(wid, Static).update(self._panel_line(label, val))

        def _render_dashboard_sessions(self, k: dict) -> None:
            # COUNT-based -> a real 0, never a dash.
            self._put_panel("#dash-sessions", "Sessions", f"{k['sessions']:,}")
            self._put_panel("#dash-projects", "Projects", f"{k['projects']:,}")
            self._put_panel("#dash-turns", "Turns", f"{k['turns']:,}")
            self._put_panel("#dash-toolcalls", "Tool calls", f"{k['toolcalls']:,}")

        def _render_dashboard_inventory(self, k: dict) -> None:
            # All-time: the inventory and the prompt history have no timestamp.
            self._put_panel("#dash-inv-prompts", "Prompts", f"{k['prompts']:,}")
            self._put_panel("#dash-inv-agents", "Agents", f"{k['agents']:,}")
            self._put_panel("#dash-inv-skills", "Skills", f"{k['skills']:,}")
            self._put_panel("#dash-inv-plugins", "Plugins", f"{k['plugins']:,}")
            self._put_panel("#dash-inv-mcp", "MCP", f"{k['mcp']:,}")

        def _blank_text(self, in_window: int, window: str, span: str, verb: str) -> str:
            """Which sentence an empty panel owes the reader.

            Two blanks wear the same face. One is "this range placed no session at all" —
            widen it and the panel fills. The other is "this range placed N sessions and
            none carries the field the panel reads" — widening changes nothing, because Trae
            never wrote that label. Measured on the real index: all 20 sessions in the
            current 7d window have `agent` NULL, so Top agents sat blank beside a Sessions
            panel reading 20 while telling the reader the *dates* were the problem.
            """
            if not in_window:
                return f"none dated in {window}"
            return f"no session{span} {verb}"

        def _render_dashboard_projects(self, rows, blank: str) -> None:
            self._render_leaderboard(rows, "#dash-top-projects",
                                     lambda r: r["project"] or r["project_key"],
                                     26, "no projects indexed", blank)

        def _render_dashboard_agents(self, rows, blank: str) -> None:
            self._render_leaderboard(rows, "#dash-top-agents",
                                     lambda r: r["agent"],
                                     24, "no agents installed", blank)

        def _render_leaderboard(self, rows, wid: str, name_of, width: int,
                                none_indexed: str, blank: str) -> None:
            """One Dashboard leaderboard: the entities this range can say something about.

            Zero-count rows are dropped, because a leaderboard of nothing-but-zeros is
            noise. The row that keeps its place is the one with `undated` sessions: its
            zero is the window's blind spot, not a measurement, and `window_count` prints
            it as `-`. Three empties, three sentences — `none_indexed` is the panel's own
            table being empty, `blank` is the range's, and they have different fixes.
            """
            top = [r for r in rows if r["sessions"] or r["undated"]][: self.DASH_TOP]
            if not top:
                self.query_one(wid, Static).update(
                    none_indexed if not rows else blank)
                return
            lines = [f"{i}. {clip(name_of(r), width):<{width}}"
                     f"{db.window_count(r['sessions'], r['undated'], 'session'):>12}"
                     for i, r in enumerate(top, 1)]
            self.query_one(wid, Static).update("\n".join(lines))

        # Block characters for the per-day sparkline (index 0 = no activity).
        _SPARK = " ▁▂▃▄▅▆▇█"

        def _sparkline(self, values) -> str:
            peak = max(values) if values else 0
            if peak <= 0:
                # A quiet window still draws something: an empty string left a
                # blank region on the Dashboard, which reads as "widget broken"
                # rather than "no sessions". A dotted baseline says the same thing
                # as the zero-height bars it replaces, without inventing a bar.
                return "·" * len(values)
            out = []
            for v in values:
                level = 0 if v <= 0 else min(8, max(1, round(v / peak * 8)))
                out.append(self._SPARK[level])
            return "".join(out)

        def _render_dashboard_activity(self, daily, start, end) -> None:
            """A one-line sparkline of sessions per local day across the window.

            ``daily`` only carries days that had sessions, so the gaps are filled
            from the window bounds. For the all-time range the series starts at
            the first day with data (never from the epoch).
            """
            counts = {r["day"]: r["sessions"] for r in daily}
            now = self._now_ms() if end is None else end
            end_day = datetime.fromtimestamp(now / 1000).date()
            if start is not None:
                start_day = datetime.fromtimestamp(start / 1000).date()
            elif daily:
                start_day = datetime.strptime(daily[0]["day"], "%Y-%m-%d").date()
            else:
                start_day = end_day
            days, d = [], start_day
            while d <= end_day:
                days.append(d)
                d += timedelta(days=1)
            series = [counts.get(day.isoformat(), 0) for day in days]
            self.query_one("#dash-activity", Static).update(self._sparkline(series))
            # The day list is never empty (a window always contains at least
            # today), so the branch that matters is "no sessions in it", not
            # "no days" — the old `if series:` test was always true.
            if any(series):
                self.query_one("#dash-activity-axis", Static).update(
                    f"{days[0]:%m-%d} → {days[-1]:%m-%d} · peak {max(series):,}/day")
            else:
                self.query_one("#dash-activity-axis", Static).update(
                    f"{days[0]:%m-%d} → {days[-1]:%m-%d} · no activity")

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id != "range":
                return
            pane = self.query_one(TabbedContent).active
            if self._range_of(pane) is None:
                return                    # this tab has no window
            if event.value == CUSTOM_RANGE:
                # "Custom…" opens the picker — unless this is the programmatic
                # sync that points the Select at an already-custom window.
                if not isinstance(self._range_of(pane), db.CustomWindow):
                    self._open_date_range(pane)
                return
            if event.value == self._range_of(pane):
                return                    # programmatic sync, not a user change
            self.tab_range[pane] = event.value
            self._sync_range_widget()     # refresh the 📅 label
            self._refresh_active_tab()    # re-query only the visible tab

        def _open_date_range(self, pane) -> None:
            """Open the date picker for a pane and apply the picked window to it."""
            modal = DateRangeModal(self._range_of(pane), self._now_ms())

            def done(result) -> None:
                if result is None:
                    self._sync_range_widget()   # cancel: revert the Select
                    return
                self.tab_range[pane] = result
                self._sync_range_widget()
                self._refresh_active_tab()

            self.push_screen(modal, done)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            # Only the top bar's 📅 control reaches the app; the modal handles its
            # own buttons (it is the active screen).
            if event.button.id == "date-range":
                pane = self.query_one(TabbedContent).active
                if self._range_of(pane) is not None:
                    self._open_date_range(pane)

        # --- row select: route to detail screens ---------------------------

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            # An agent row opens the sessions behind it, and a session row inside
            # that screen opens its detail. The inventory kinds have no history to
            # show — Trae records no usage per skill, plugin or MCP server — so
            # they say so instead of swallowing the key press.
            key = event.row_key.value
            if not key or "\t" not in key:
                return
            kind, _, rest = key.partition("\t")
            if not rest:
                return
            if kind == "session":
                self.push_screen(SessionScreen(rest))
            elif kind in ENTITY_FILTERS:
                # Inherit the tab's own window, so the list opening under a count is
                # a count of the same thing, and its heading says which range that was.
                pane = self.query_one(TabbedContent).active
                start, end = self._bounds_for(pane)
                self.push_screen(EntityScreen(kind, rest, start, end,
                                              db.window_label(self._range_of(pane))))
            else:
                self.notify(
                    "No detail: Trae CN records no usage per "
                    + self.NO_DETAIL_NOTE.get(kind, kind),
                    severity="warning")

        NO_DETAIL_NOTE = {"inv": "skill, plugin or MCP server"}

        # --- R / S shortcuts ------------------------------------------------

        def action_refresh(self) -> None:
            # R = incremental sync + reload DB + refresh the UI (not just a
            # re-render of already-loaded data).
            self._set_status("Syncing…")
            self._request_sync()

        def action_toggle_auto_sync(self) -> None:
            # S = toggle the automatic sync switch. Distinct from R: it does not
            # trigger a sync itself.
            self._auto_sync = not self._auto_sync
            # The line itself carries the state ("· auto-sync OFF"); a bespoke
            # message here used to wipe the counts off the bar until an unrelated
            # refresh happened to put them back.
            self._set_status(self._status_line())
            self._render_sync_state()
            self.notify(f"Auto sync: {'ON' if self._auto_sync else 'OFF'}")

        # --- automatic sync / refresh timers --------------------------------

        def _auto_sync_tick(self) -> None:
            # The same shutdown guard as _auto_refresh_tick (D-003). A timer can
            # fire once more while the app is closing; _request_sync then reaches
            # for an event loop that is already gone and raises
            # "RuntimeError: no running event loop", leaving a worker coroutine
            # that is never awaited.
            if not self.is_running:
                return
            if self._auto_sync:
                self._request_sync()

        def _auto_refresh_tick(self) -> None:
            # Only the visible tab is re-queried; hidden tabs refresh when the
            # user opens them. The is_running guard matters because a timer can
            # fire once more while the app is shutting down (e.g. run_test's
            # teardown), after the widgets are gone — query_one then raises
            # NoMatches from inside the timer and fails the test run.
            if not self.is_running:
                return
            self._refresh_active_tab()

        def _request_sync(self) -> None:
            # Guard against concurrent syncs: if one is running, mark a pending
            # request and return; the running worker will retry on completion.
            if self._sync_running:
                self._sync_pending = True
                return
            self._sync_running = True
            self.run_worker(self._do_sync, thread=True, group="sync")

        def _do_sync(self) -> None:
            # Runs in a worker thread. tcut-sync.run() opens its own RW
            # connection and uses the incremental sync_state table, so no
            # connection is shared across threads.
            try:
                if self.sync_mod is None:
                    self.sync_mod = db.load_sync()
                stats = self.sync_mod.run(quiet=True, db_path=self.db_path)
                self.call_from_thread(self._on_sync_done, True, stats, None)
            except Exception as e:  # report, never swallow
                self.call_from_thread(self._on_sync_done, False, None, str(e))

        def _on_sync_done(self, ok: bool, stats, err) -> None:
            self._sync_running = False
            if ok:
                # The sync reports per-source counts in ``results`` (not a
                # ``files_indexed`` total). ``inventory`` deletes and re-inserts
                # its whole — tiny — list every run, so it is not a change
                # signal; the file-backed sources are.
                results = (stats or {}).get("results", {})
                indexed = sum(n for label, n in results.items()
                              if label != "inventory")
                if indexed:
                    self.refresh_data()          # new rows can touch any tab
                else:
                    self._refresh_active_tab()   # nothing changed -> light refresh
                    # A light refresh does not rewrite the bar, so without this
                    # the transient "Syncing…" from `r` survives the sync that
                    # already finished.
                    self._set_status(self._status_line())
                self._last_sync = self._clock()
                self._render_sync_state()
                self.notify(f"Synced {db.count_n(indexed, 'record')}")
            else:
                # The same composer as the data line: a failed sync is a fact
                # *about* the numbers, not a replacement for them.
                self._status_note = "Sync failed: " + (err or "unknown error")[:200]
                self._set_status(self._status_line())
                self.notify("Sync failed — keeping current data", severity="error")
            if self._sync_pending:
                self._sync_pending = False
                self._request_sync()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Interactive Trae CN usage tracker.")
    ap.add_argument("--db", default=str(db.DB_PATH))
    args = ap.parse_args(argv)

    if not HAVE_TEXTUAL:
        print(
            "textual is not installed — the TUI needs it.\n"
            "  pip install -r requirements.txt   (or run ./install.sh)\n"
            "Headless reports still work:  tcut stats",
            file=sys.stderr,
        )
        return 2
    if not Path(args.db).exists():
        print(f"no database at {args.db} — run: tcut sync", file=sys.stderr)
        return 1
    try:
        app = TrackerApp(args.db, config=db.load_config())
    except db.ConfigError as exc:
        # A broken settings file is the user's to fix, and starting with defaults
        # silently would leave them editing a file that is not being read.
        print(f"your settings are not usable: {exc}\n"
              f"  fix or remove that file, or point TCUT_CONFIG somewhere else",
              file=sys.stderr)
        return 2
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
