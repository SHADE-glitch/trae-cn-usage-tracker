# CHANGELOG — trae-cn-usage-tracker

Original project, **no upstream**: nothing here is a deviation from somebody else's code, so this
record is not a divergence list. It records the repairs, the performance work, the drift guards and
the withdrawals — the things a Trae update, a Textual update, or an on-disk-format change can
invalidate.

Coverage: 9b59873..HEAD
Check with `python3 -m unittest scripts.tests.test_record_coverage`. Entries are `D-###`, monotonic,
never reused. An entry states what was true **as of its commit**, not current state, and aggregate
counts are printed by the check, never copied into this file.

> **Why the record is short.** The initial import (`9b59873`) bundled the product itself — the
> parser, the ten-tab TUI, the headless CLI and the first cut of the credit and model axes — and it
> is the coverage anchor, so its content sits outside the window by construction. Features are
> documented in the READMEs; only the non-feature commits that touch a production path appear below.
>
> **The bundled `feat` commit.** D-002…D-007 all cite `b18ae3c`, whose subject is `feat:` and which
> the class rule would therefore skip. It landed as one bundled commit, and inside it are repairs and
> guards, not product: a parser that was losing every snapshot timestamp, a window that hid what it
> could not date, a derived creation second that had to be kept from reading as a measurement, and
> two guards that compared a document with a document. The exclusion is by commit **class**, and a
> bundled commit is exactly where the class stops describing the content — so the entries are
> recorded against the one hash, and each names the specific test or measurement that proves its own
> half.

`kind` ∈ `fix` | `perf` | `taste` | `guard` | `revert` | `chore` — see AGENTS.md § Recording
conventions for the cut.

---

### D-001 · 2026-10-12 · fix
Symptom  This machine's real home path was on its way into public history: the ported fixtures
         spelled out `/home/shade` and its encoded project-key form, and the `decode_project`
         docstring quoted a real-looking key.
Change   Scrub both spellings to a neutral `/home/user` — 23 path sites and 14 key sites across four
         test modules plus the decoder docstring — keeping each input paired with the path it must
         decode to. The sibling tracker already uses the neutral path for exactly this reason.
Evidence L0 2026-10-12 `python3 -m unittest discover -s scripts/tests` (green at the time); the
         scrub is proved by `test_sync.py`'s decode cases, which still pass on the neutral key.
Cost     The examples are less concrete than the ones they replaced, which is the point: a path in
         a public fixture is a fact about the author, not about the format.
Commit   6808f70

### D-002 · 2026-10-12 · fix
Symptom  The parser was losing **every** snapshot timestamp. The refs name annotated tag objects,
         and `_commit_time` recognised only a `commit ` header, so all 89 turn rows and 139 toolcall
         rows stored `ts = NULL` on this machine — while the suite stayed green, because the
         fixtures wrote lightweight refs (ref → commit), a shape the real app never produces.
Change   Peel the tag to its `object` commit; use the `tagger` line (measured ~10 s behind the
         commit) only when the commit cannot be read; count an unreadable object as
         `unparsed = snapshot:time_unreadable` instead of going quietly undated. The fixtures now
         build both shapes and assert each result.
Evidence L2 2026-10-12 after a real `sync`: turns 89/89 and toolcalls 139/139 dated, sessions 24/49
         with a **measured** time. L0 `test_sync.py` gained a case per shape.
Cost     A tag whose commit object is missing is now counted rather than silently dated from the
         tagger line — one more number to read, in exchange for not losing the timestamp in silence.
Commit   b18ae3c

### D-003 · 2026-10-12 · fix
Symptom  A windowed count that the range could not see rendered `0`, not `-`. A row printed
         `0 sessions` and Enter on it opened a list of 22 — the same row, two numbers, one screen.
Change   `db.window_count` renders `-` when the row has neither a measured `last_ts` nor a derived
         `created_ts`, and `0` is reserved for a measured absence. The Agents drill-down inherits the
         window of the row it was opened from and names that range in its heading.
Evidence L0 2026-10-12 `test_stats.py` and `test_tui.py`: the three windowed views and the drill-down
         each carry a case, provoked by reverting the fix in a throwaway copy.
Cost     A count can now be a third thing (`-`) beside a number and a zero, so every surface that
         prints one owes the reader a definition.
Commit   b18ae3c

### D-004 · 2026-10-12 · fix
Symptom  25 of 49 sessions have no measured timestamp anywhere in Trae's plaintext, so no range
         could place them and they vanished from every windowed view — including "All time".
Change   Schema **v4** adds `sessions.created_ts`, filled from the session id's first four hex bytes.
         Re-measured 2026-10-12 against the 24 sessions that also have a dated turn: median delta
         0.0 s, worst 144 s, and **no turn predates it** — a floor, not a guess at the middle. It
         enters a window only through `COALESCE(last_ts, created_ts)` (`db.SESSION_TIME`), and any
         surface that prints a position earned this way prints `db.derived_mark` (`~`) in front of it
         and discloses how many rows it applies to (`q_kpi["unmeasured"]`).
Evidence L2 2026-10-12: an upgraded index places all 49 sessions and rewrites no row, so everything
         it had measured is still measured. L0 the v4 backfill and its plausibility bound have cases.
Cost     A table where a derivation looks exactly like a measurement is how a derivation becomes a
         fact — hence the `~` and the disclosure line, both of which must be kept.
Commit   b18ae3c

### D-005 · 2026-10-12 · fix
Symptom  The Dashboard's **Top projects** and **Top agents** dropped the rows they could not date,
         so a capped leaderboard hid exactly the objects it could not place. A blank **Top agents**
         blamed the time range while the sessions were right beside it, labelled with nothing.
Change   `q_projects` reports `undated` beside `sessions` the way `q_agents` already did, both sort
         the `-` rows ahead of a real `0`, and a blank panel names its own cause: `no agents
         installed` (nothing indexed), `no session in this range names an installed agent` (the
         sessions are there, the label is not), or `none dated in <range>` (the range placed
         nothing). Measured 2026-10-12: 24 of 49 sessions carry no `agent` at all, and every one of
         the 20 sessions in the current 7d window is one of them.
Evidence L0 2026-10-12 `test_tui.py`: the leaderboards, the three empty sentences and the fallback
         that feeds the windowed views each have a case, each provoked in a throwaway copy.
Cost     Three sentences where there was one — because the three have three different fixes, and
         only the range one is solved by widening the picker.
Commit   b18ae3c

### D-006 · 2026-10-12 · fix
Symptom  `window_bounds("all")` also dropped its upper bound. With `last_ts < now` it excluded every
         row that has no timestamp, so "All time" — the range that is supposed to be the escape
         hatch — was the second place the 25 undated sessions went missing.
Change   Give "All time" no upper bound, and cover `window_bounds` with cases; no test had ever
         exercised it.
Evidence L0 2026-10-12 `test_stats.py`: two cases now pin the bounds, provoked by reverting each.
Cost     None — a range that excluded rows by a clock it was not supposed to consult was simply
         wrong.
Commit   b18ae3c

### D-007 · 2026-10-12 · guard
Symptom  Two guards compared a document with a document: `bin/tcut`'s advertised tab count and the
         README's `Ran N tests` line were each checked against a hand-typed literal, so a stale
         claim and its guard could stay green together — which is what happened when tabs were cut
         and tests went with them.
Change   Both guards now read the product: the dispatcher's count is checked against the `TabPane`s
         the app composes, and the README line against `unittest` discovery. Each failed on the
         stale claim it used to bless, which is the evidence that it now checks something.
Evidence L0 2026-10-12 `test_dispatcher.py` and `test_readme_counts.py` (the latter now over the
         README pair).
Cost     The guards fail on a stale claim instead of blessing it, so a tab change or a suite change
         now owes a README edit.
Commit   b18ae3c

### D-008 · 2026-10-12 · guard
Symptom  The parser's coupling to Trae's on-disk shape was scattered: six `state.vscdb` keys were
         inlined at their call sites, and the model-catalog whitelist and the `unparsed` vocabulary
         existed only inside the handlers. A rename would read as an unclaimed source, the panels
         would empty out, `tcut sync` would print "done", and CI would stay green.
Change   A registry at the top of `tcut-sync.py` states the surface once; `format_doc()` renders it
         and `tcut format --write` writes it into the generated block in
         `docs/maintenance/trae-cn-format.md`. `test_format_registry.py` holds the registry to the
         parser in both directions (nothing read unregistered, nothing registered unread, no inlined
         key literal), and `test_maintenance_docs.py` fails when the block and the renderer disagree.
Evidence L0 2026-10-12 `python3 -m unittest discover -s scripts/tests` — 215 tests OK.
Cost     A rename is now one edit the suite reports with line numbers; the registry can no longer be
         silently ahead of or behind the parser. It checks the coupling, not the *values* Trae writes.
Commit   b536f2e

### D-009 · 2026-10-13 · fix
Symptom  `tcut export` was documented as the machine-readable form of the whole index and emitted
         eight hand-copied query sections instead: `turns`, `toolcall_events`, `topics`,
         `session_actions`, `session_learned`, `session_models`, `workspaces`, `sync_state`,
         `unparsed` and `meta` were indexed and exported by nobody. Reading the index's coverage
         meant opening the database, and the test that owned the claim only checked that the JSON
         parsed plus three fields — so the gap could not be noticed from either side. A hand-kept
         table list also cannot fail when a future migration adds a table, which is how the claim
         stayed unexamined.
Change   `db.table_names` enumerates `sqlite_master`, `cmd_export` dumps every table verbatim
         ordered by rowid, and the only derived section left is `overview`. Query-time readings
         (`spent_at_least`, the windowed counts, the `~` marker) are deliberately absent: a
         derivation shipped beside stored columns gets read as stored data. The check compares the
         exported key set with the schema's table set in both directions — missing table or ghost
         section — and a second case reads rows, not just keys.
Evidence L0 2026-10-13 228 tests OK; `test_stats.py`
         `test_export_carries_every_table_the_schema_has` and
         `test_export_dumps_rows_verbatim_and_no_query_time_derivation`. Reversals in throwaway
         copies, control green first: loop skips one table, section list back to hand-copied, a
         ghost section added, a derivation leaked into the dump — 4/4 red. L1 on the real footprint
         now reports 18 sections (`sessions 49`, `turns 89`, `toolcall_events 139`, `prompts 293`,
         `models 284`, `sync_state 84`, `unparsed 0`, `meta` = schema_version 4).
Cost     One breaking change to the JSON shape: the old `projects`, `credits` and the `model_id`
         that rode on `sessions` are gone, their inputs are now present as raw tables. A dashboard
         that reads the schema itself has no reason left to open the database by hand.
Commit   b0dcd72

### D-010 · 2026-10-13 · fix
Symptom  The agent drill-down listed sessions and totalled nothing, and the header's first shape
         printed `22 sessions · 0 projects` for exactly the set where no session carries a project
         key (measured: 28 of 49 sessions have neither a decoded project nor a raw key). That is a
         claim about the world built out of a missing field — the same class as an empty token
         panel reading as zero.
Change   `db.q_entity_totals` aggregates the entity's windowed sessions, turns, tool calls,
         distinct projects and the first→last span. It builds its predicates from
         `db._entity_conds`, the same list `q_sessions` now uses, so the header cannot count a
         different set than the table beneath it. `projects` pairs with `projects_missing` and is
         read through `window_count`, printing `-` when no row had a key. `turns`/`toolcalls` get
         **no** dash: measured on this footprint they are never NULL (0 of 49), so a stored 0 is a
         reading and dashing it would flatten "no turns" into "no snapshot tags". Each edge of the
         span is marked separately against `first_measured`/`last_measured`, because a set can be
         dated at one end by a session id and at the other by Trae.
Evidence L0 2026-10-13 228 tests OK; `test_tui.py` `test_the_drill_down_totals_the_rows_it_lists`,
         `test_the_header_and_the_list_agree_when_the_window_cuts_the_set`,
         `test_the_summary_marks_a_span_whose_edge_came_from_the_id`,
         `test_a_session_set_with_no_project_key_reads_as_unknown_not_zero` and its keyed
         counterpart. Reversals, control green first: header ignores the window, header stops
         sharing the list's filter, derived edge unmarked, project dash removed, line never
         filled — 5/5 red. Real index: `builder · All time · 22 sessions · 0 turns · 0 tool calls ·
         - · ~04-26 11:22 → ~09-05 08:56`, `solo_coder · 2 sessions · 41 turns · 4 tool calls · 1
         project · ~09-05 08:59 → 09-25 20:22`.
Cost     One extra aggregate query per drill-down. It also commits the repo to checking what the
         writer stores before adding a second dash — the reason `turns` is not dashed here is a
         measurement, not a judgement.
Commit   b0dcd72

### D-011 · 2026-10-13 · fix
Symptom  `bin/tcut`'s header block named 14 of the 17 headless commands: `models`, `credits` and
         `format` were reachable but unlisted. That header is what a person reads when the TUI
         venv is broken, so the dispatcher's own help under-reported the tool it dispatches to.
Change   The block lists every command, and the guard reads the real `COMMANDS` table instead of
         the prose: a command the help never names fails, and a name the help still advertises
         after the command is gone fails too. `test_dispatcher.py` loads `tcut-stats.py` for this,
         the same way the tab-count guard (D-007) reads the app rather than a document.
Evidence L0 2026-10-13 `test_dispatcher.py::test_the_help_names_every_headless_command`.
         Reversals, control green first: help back to the short list, help given a name no command
         is — 2/2 red. The extraction had to strip the comment block's indentation after the first
         version passed over lines that never started where the pattern looked.
Cost     Adding a command now owes a help line, and deleting one does not get to leave a ghost.
Commit   b0dcd72

### D-012 · 2026-10-13 · guard
Symptom  The tripwire guarded one path. `_hermetic.py` recognised the live `usage.db` and nothing
         else, so a fixture was free to read `~/.trae-cn/**` — and the host is *input* to this
         reader, not state it could damage, which is exactly why the rule had never covered it. A
         test that reads the host stops testing the code and starts testing the machine. The
         sibling `ocut` shipped that bug: a fixture opened the developer's real plugin-events
         sidecar, so three cases were green in CI (no sidecar) and red on the one machine that
         needed them red.
Change   `PROTECTED_DIRS` carries the agent home and the VS Code user-data dir, and the hooks
         cover three read paths instead of one — `open`, `os.scandir`/`os.listdir` (a glob reaches
         a host file's contents without ever calling `open`) and `sqlite3.connect`. A child must
         pin `TCUT_TRAE_CN_HOME` **and** `TCUT_TRAE_CN_DATA` for the reason it must pin
         `TCUT_DB`: this launcher resolves them independently, so pinning the database left both
         host dirs as wide open as before. Ten cases became thirteen.
Evidence L0 2026-10-13 245 tests OK. Each new refusal ships with the case that keeps it honest:
         `test_an_ordinary_test_host_is_left_alone` walks an ordinary temp path through the same
         three hooks and must come back clean, so a hook that refuses everything fails the suite
         rather than passing it, and the child refusal has the matched positive
         `test_the_same_child_is_allowed_once_its_paths_are_pinned`.
Cost     A test that shells out now pins two more variables or it is refused. That refusal at
         commit time is the cheaper place to learn it than a red test on one machine.
Commit   e1397bc

### D-013 · 2026-10-13 · fix
Symptom  Three comments and one case name described a TUI that no longer existed, and every
         assertion in them was still correct — so nothing was red, which is the whole problem. The
         Usage page now reads `log_limit`, yet `DEFAULTS["log_limit"]` still said "Prompts page
         rows"; `test_config.py` still skipped `log_limit` in the constants comparison on the
         stated ground that "it drives `tcut prompts`, not the TUI"; and `test_stats.py`'s case was
         named `..._now_that_the_tui_has_no_prompts_tab`, a fact that stayed true after the tab
         came back with a different job. Separately, three docstrings in `tcut_db.py` and
         `tcut-tui.py` were written in Chinese, which the machine-wide standard reserves for the
         two bilingual READMEs — a language-policy violation in a repository whose own rule says
         "docs are bilingual, code comments are not".
Change   Each comment now names both readers of the key; `log_limit` joins the constants
         comparison in `test_the_defaults_match_the_tuis_own_constants`, and that case's own
         comment says every key a renderer reads participates. The `test_stats.py` case is renamed
         for what it does now (`..._caps_the_cli_now_that_the_prompts_tab_is_gone`) and points at
         `test_config.py` for the TUI side. The three docstrings are English. `bin/tcut`'s help
         says eight tabs, which is what it launches.
Evidence L0 2026-10-13 245 tests OK. No provocation, and none is possible: the assertions were
         valid before the change and are valid after it — the defect was in the sentences, not the
         checks, which is why the suite could not find it and why the fix is `fix` rather than
         `guard`. The Chinese in `test_sync.py` is percent-decoding test data and is left alone
         under the standard's verbatim-literal exemption.
Cost     A comment that describes behaviour is now a claim someone has to keep true, and there is
         no check that reads them. The only control is reading the diff.
Commit   e1397bc

### D-014 · 2026-10-13 · guard
Symptom  The root-file layer was a naming convention with nothing behind it. No check in this
         repository asserted that the finalized files sit at the repository root, that `LICENSE`
         exists, or that `AGENTS.md` points at the machine-wide standard instead of restating it.
         A renamed or deleted root file would only be noticed by a person reading the diff.
Change   Add `scripts/tests/test_conventions.py` (9 cases, standard library only, and it installs
         the same hermetic tripwire its siblings require). It asserts the finalized layer is
         present at the root and that `pyproject.toml` is the only manifest; that `AGENTS.md`
         carries the one-line dimension pointer and reproduces none of the standard's own numbered
         section headings; that `.gitignore` still covers the runtime state the standard lists and
         that `git ls-files` tracks none of it; and that no process draft is tracked anywhere.
         `AGENTS.md` gains the dimension line above the shared-standard pointer it already had. The
         README pair moves from 245 to 254 tests, because `test_readme_counts.py` compares the
         table against `scripts/tests/` and a new suite has to be counted, not ignored. Nothing is
         fetched — every assertion reads this working tree.
Evidence `python3 -m pytest scripts/tests -q` 254 passed (91 subtests), run with the final content
         of this entry in the tree. Provoked for real: moving `LICENSE` out of the tree turns the
         root-layer case red with `AssertionError: Lists differ: [] != ['LICENSE: create this file
         at the repository root']`, and restoring it turns the suite green again. Two earlier
         drafts of the guard were themselves red and were corrected rather than suppressed — a
         heading match that also caught this repository's own `## CI`, and an ignore-list spelling
         that only matched `.venv/`. No test was skipped, widened or moved to make a check pass.
Cost     The manifest and ignore lists are hard-coded, so a deliberate second manifest or a new
         runtime artefact is a change to this file rather than a surprise failure. The README
         aggregate is a second place to update for every new suite; that is the repository's own
         rule, not something this entry introduces.

Commit   467af1a
