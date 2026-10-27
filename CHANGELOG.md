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

### D-015 · 2026-10-16 · chore
Symptom  The pointer in AGENTS.md is followed only by an agent that chooses to follow it: it named
         `~/.agents/standards/`, but nothing made that text reach the context, and the section list
         it carried had drifted — §5 (the conflict rule) was missing.
Change   End the pointer block with two bare `@` imports (`@~/.agents/standards/STANDARD.md`,
         `@~/.agents/standards/dimensions/a.md`) and add `opencode.json`, whose `instructions` array
         names the same two files. Add `§5 conflict rule` to the section list. `test_conventions.py`'s
         `ROOT_FILES` gains `opencode.json`.
Evidence 2026-10-16: CodeBuddy CLI (`-p --tools ''`, every tool disabled) in a directory whose only
         memory file was an `AGENTS.md` carrying the two imports printed the tokens they carried — the
         text is injected, not read by a tool. opencode `run` printed the token its `instructions`
         named, with no tool call. `python3 -m pytest scripts/tests/test_conventions.py -q`
         9 passed.
Cost     Both hooks name `~/.agents`, absent in another clone, so they are skipped there — the
         pointer stays the portable part. Nothing is copied, so nothing can drift.
Commit   923c26a

### D-016 · 2026-10-16 · fix
Symptom  Three non-whitelisted `docs/maintenance/*.md` carried Chinese `## 中文说明` prose
         summaries, which dimension A forbids: it reserves bilingual documents for the README and
         MAINTENANCE pairs, so a document under `docs/` holding Chinese is a defect. Worse,
         `test_maintenance_docs.py` asserted the opposite — `compatibility.md` had to contain at
         least 20 CJK characters — so the guard blessed the drift instead of catching it.
Change   Translate the three `## 中文说明` sections into English `## Summary` sections (meaning
         kept, heading renamed), and state the English-only intent in `docs/maintenance/README.md`
         the way the sibling `opencode-usage-tracker` does. In `test_maintenance_docs.py`, replace
         the `>= 20 CJK` assertion with `== 0`: the document must carry no Chinese at all.
Evidence L0 2026-10-16 `python3 -m unittest discover -s scripts/tests` — 254 tests OK (the flip is
         not a new case, so the README total is unchanged). `grep -rlP '[\x{4e00}-\x{9fff}]' docs
         --include='*.md'` prints nothing.
Cost     The summaries are English prose that partly restates the sections above them; deleting
         them outright was the alternative and was rejected to keep the meaning. The guard now
         fails on a Chinese character in `compatibility.md` instead of requiring one, so the same
         class of drift is caught in the other direction.
Commit   29d1cdb

### D-017 · 2026-10-19 · chore

Symptom  AGENTS.md cited the shared standard by bare STANDARD.md, a name that only resolves via
         the pointer block above it.
Change   The reference now carries the full ~/.agents/standards/STANDARD.md path.
Evidence 2026-10-19: python3 -m unittest discover -s scripts/tests — 254 tests, OK.
Cost     None; wording only.
Commit   df18129

### D-018 · 2026-10-26 · fix
Symptom  The `memory` table was emptied on every scan and then only the documents whose size or
         mtime had changed were re-read, so the first sync filled it and every later sync of the
         30-second timer left it empty for good. `tcut memory` answered "run `tcut sync`" — the
         one command that kept it empty — and `overview.memory_docs` read 0 over a full table.
Change   Replace per document instead of clearing per run: each changed document drops its own
         rows and writes the current paragraphs, and a scope the scan did not see is a deleted
         document whose rows go with it. `store_content = false` still purges the whole table.
Evidence L0 2026-10-26 `test_sync.py::MemoryDocsTest::test_a_second_run_keeps_the_documents_it_did_not_reread`
         fails before the change with `[] != [('project:-p--p2-a', 0, 'project line'), …]` and passes
         after; `test_a_deleted_document_takes_its_paragraphs_with_it` holds the other half, and
         `RunTest::test_a_second_run_indexes_nothing_new` still reports 0 for an unchanged tree.
Cost     A run now enumerates every document to find the deleted ones — it already did — and a
         document is identified by its scope, so a project key that changes hands leaves the old
         scope to the deletion pass rather than being overwritten in place.
Commit   0eaa6e6

### D-019 · 2026-10-26 · fix
Symptom  `topics` was only ever upserted, so a line the model withdrew stayed indexed for good, and
         `unparsed` was keyed by the reason alone, so every whole-file re-read added a second copy
         of the same bad record: one unparseable line in a `topics.md` reported three unparsed
         records after three edits, and `_scan_mcps` re-reads its tree on every sync, so
         `mcp:bad_metadata` grew once per run. The docstring already promised "once per reason per
         file"; the table had no place to put the file.
Change   Schema **v6**: `unparsed` is keyed by `(reason, source)` (rebuilt, old counts kept under
         an empty source) and `topics` gains the `topics.md` a line came from. A handler that
         re-reads a whole source calls `db.forget_unparsed(conn, source, prefix…)` first, and
         `_ingest_topics` deletes that file's rows before writing them. Streamed sources pass
         their path too, and forget it when a shrunk or rotated file is re-read from zero.
Evidence L0 2026-10-26 `test_sync.py::TopicsTest::test_a_removed_line_stops_being_indexed`
         (`['gone', 'kept'] != ['kept']` before) and
         `test_a_bad_line_is_counted_once_however_often_the_file_is_reread` (`3 != 1` before).
         `test_snapshots.py::PerSourceMigrationTest` holds the v5→v6 upgrade to keeping every row
         and to two sources holding the same reason, and the schema-version guard in
         `test_maintenance_docs.py` pins `compatibility.md` to v6.
Cost     A schema version, and `unparsed` rows written before v6 cannot name their file — they are
         kept with an empty source rather than guessed at. Two concepts now share one table by
         `(reason, source)`, so `q_unparsed` sums and `overview.unparsed_kinds` counts distinct
         reasons instead of rows.
Commit   d7f06dc

### D-020 · 2026-10-26 · fix
Symptom  `scan_state_vscdb` wrote the file's cursor even after the read raised, and the cursor is
         the file's size and mtime — so a workspace database that could not be opened was recorded
         as indexed and every later sync skipped it. Its prompts and its model catalog never
         arrived, and the only trace was one `vscdb:read_failed` that a retry never repeated.
Change   Advance the cursor only when `_ingest_vscdb` returned; a failed read is retried on the
         next sync, the way `scan_credit_logs` already behaved.
Evidence L0 2026-10-26 `test_sync.py::VscdbTest::test_a_failed_read_does_not_advance_the_cursor`
         fails before with `1 != 0` on the cursor row and passes after.
Cost     A permanently unreadable database is re-attempted every 30 seconds and counted each time;
         that is the cost of not silently dropping a source, and the count is now per file (D-019).
Commit   6df13ce

### D-021 · 2026-10-26 · fix
Symptom  The memory folder's midnight was written into `first_ts` and `last_ts` — the two columns
         that mean "Trae measured activity here". A day-name guess therefore printed with no `~`,
         was never counted in `q_kpi["unmeasured"]`, and won its `COALESCE` forever: a summary
         that moved to another day folder kept the first guess, and the window of the day it now
         belonged to excluded the session.
Change   The day stays in `sessions.day`; `first_ts`/`last_ts` are written only by `finalize`
         from snapshot tag times. A session with no tag is undated and prints as derived.
         `AGENTS.md` and the `SESSION_TIME` comment now say that, and the schema says it per column.
Evidence L0 2026-10-26 `test_sync.py::FinalizeTest::test_a_day_directory_is_a_day_not_a_measured_time`
         (fails with `1772553600000 is not None` before) and
         `test_a_summary_that_moves_to_another_day_follows_its_day`. `FinalizeTest`'s existing case
         still proves a tag beats the empty column.
Cost     Sessions that used to show a day-shaped timestamp now show `~` and count as unmeasured —
         which is what they are. Measured 2026-10-26 on a copy of this machine's live index: 28 of
         50 sessions had no `last_ts`, and the other 22 were dated by their day folder alone (89 of
         90 turn times were NULL, so nothing else could date them).
Commit   e97c801

### D-022 · 2026-10-26 · fix
Symptom  Cursors record that a file was read, never which parser read it, so a repaired decoder only
         ever applied to files that changed afterwards. Measured 2026-10-26 on this machine's live
         index: `turns.ts` NULL in 89 of 90 rows, `toolcall_events.ts` NULL in 139 of 148,
         `unparsed` empty and `tcut health` green — every one of those rows was written by the
         pre-D-002 parser, and only `--full` could repair them.
Change   `PARSER_VERSION` is stamped in `meta`; when the stored generation differs, `run()` drops
         every cursor once so each source is re-read (the handlers replace rather than merge, so
         this is idempotent), and `tcut health` names a stale index until that sync runs.
Evidence L0 2026-10-26 `test_sync.py::RunTest::test_a_parser_generation_change_reindexes_what_the_old_one_wrote`
         fails before with `None != 1700000000000` on `turns.ts`, and proves the pass after it is
         incremental again; `test_stats.py::HealthTest` holds both the stale and the current line.
         L2 2026-10-26 on a **copy** of the live v5 index, one incremental sync: `turns` 90/90 and
         `toolcall_events` 148/148 dated (was 89 and 139 NULL), `schema_version` 6,
         `parser_version` 2, `unparsed` 0, and 25 of 50 sessions carrying a measured time where 22
         had been dated by a day folder. The live database itself was not touched.
Cost     One full re-read per parser generation, including sources the change did not touch — the
         alternative is a per-source version table that nobody remembers to bump. The invalidation
         is a cursor drop, not a rebuild: no snapshot, no table dropped.
Commit   ac119c7

### D-023 · 2026-10-26 · fix
Symptom  `tcut sync` and every reporting subcommand called `db.load_config()` outside any handler,
         so a malformed `config.toml` or a bad `TCUT_*` value answered with a traceback — the TUI
         was the only entry point that had ever turned `ConfigError` into a message. A refused
         sync could also leave an empty database behind for the next run to read as indexed.
Change   Both headless entry points catch `ConfigError`, print the one line the exception already
         carries (it names the path or the variable) and exit 2, matching `tcut-tui.py`.
Evidence L0 2026-10-26 `test_stats.py::BrokenSettingsTest` (file and environment) fails before with
         `ConfigError` escaping the child, and `test_sync.py::EntryPointSettingsTest` fails the same
         way in-process while also asserting no database file was created.
Cost     Exit code 2 now means "your settings", on three entry points instead of one; the message
         is the exception's own text, so it stays in step with the loader.
Commit   e097add

### D-024 · 2026-10-26 · fix
Symptom  `tcut stats` printed the catalog count twice — "models" on the prompts line and "models" on
         the credit line — and the same word carried the count of models a session had actually
         selected: 291 above and 9 below on one TUI screen (status bar against the Tokens/Usage
         panel), with nothing to tell the reader which was which.
Change   The catalog count is named `catalog`/`catalog models`, the selected-model count is
         "Models used" in both panels, and the status line says "catalog models". One number per
         word.
Evidence L0 2026-10-26 `test_stats.py::CommandTest::test_stats_names_the_catalog_once_and_never_prints_two_model_counts`
         fails before with `2 != 1` occurrences of "models", and
         `test_tui.py::DashboardPanelTest::test_a_catalog_count_and_a_used_count_never_share_one_word`
         holds the two labels apart.
Cost     Two labels get longer ("catalog models" in the status bar, "Models used" in a panel whose
         label column is 12 cells — it fits, but a third word would not).
Commit   f942459

### D-025 · 2026-10-26 · fix
Symptom  `tcut credits --limit N` summed the rows the limit left visible, so asking for fewer lines
         lowered the reported spend: the same database reported "at least 94.0244 credits spent"
         unrestricted and "at least 10" with `--limit 1`.
Change   Read the whole series and print a slice of it; the total is the series' own, and the line
         says "showing the newest N" when it is showing fewer rows than it counted.
Evidence L0 2026-10-26 `test_stats.py::CommandTest::test_credits_total_does_not_shrink_with_the_limit`
         fails before with `'10' != '94.0244'` and passes after.
Cost     `tcut credits` reads every balance observation even when it prints one; the series is one
         row per app start, so this stays cheap, and the alternative — a total that depends on a
         display flag — is a number nobody can quote.
Commit   f942459

### D-026 · 2026-10-26 · fix
Symptom  The date picker is the second way into every windowed tab and nothing tested it. Its All
         time chip — and the picker prefilled on All time — left "end follows now" ticked, so
         confirming produced `[all, now]` instead of the preset `db.window_bounds` defines as
         having neither bound. A window ending at now silently drops every row with no timestamp:
         measured 2026-10-26, 28 of this machine's 50 sessions. Confirm also refused a blank start
         with a blank end, so the picker could not express all time at all.
Change   A preset follows the clock only when it has a live end; the picker's all-time window lands
         on the `all` preset, so the two ways in cannot drift; and `db.window_label` can print a
         window with neither bound ("all time") instead of dividing `None` by 1000.
Evidence L0 2026-10-26 `test_tui.py::DateRangePickerTest` — the chip case fails before with
         `(None, None, True) != (None, None, False)`, the prefill case the same, and the app-level
         case returns `'7d'` instead of `'all'`; `test_stats.py::RenderingTest` holds the label.
Cost     "All time" from the picker is stored as the preset, so a later change to the preset's
         bounds reaches both entry points — which is the point, and also means the picker can no
         longer produce "everything up to now" by clearing the start; that needs a fixed end.
Commit   ff71a97

### D-027 · 2026-10-26 · fix
Symptom  The end card's "23:59" chip wrote 23:59:00 into a window whose upper bound is exclusive, so
         picking the end of the day dropped everything between 23:59:00 and 23:59:59.999 — the last
         minute of the day it named.
Change   The chip reads `24:00` and writes the next midnight into the end card (moving the card's
         date with it), which is the same instant written where a right-open window can include it.
Evidence L0 2026-10-26 `test_tui.py::DateRangePickerTest::test_the_end_of_day_chip_includes_the_last_minute`
         fails before with `1700063940000 != 1700064000000` (23:59:00 against the next midnight).
Cost     The end card can now show a date one day past the start date's day, which is what "the end
         of that day" means in a half-open interval; `24:00` is the label for it.
Commit   b71d0a6

### D-028 · 2026-10-26 · fix
Symptom  In the entity drill-down (a project, an agent, a session list) the model, route and credit
         cells were a hard-coded `-`, so a session Trae had a selection for read as unknown and the
         estimate the balance split had already computed was dropped on the one list that shows
         the session.
Change   `q_sessions` joins the same selection the model column always used (agent before
         solo_agent, then by label) and returns its decoded `model`, `provider`, `third_party` and
         the session's whole estimated share; the row prints them and `-` means unknown again.
Evidence L0 2026-10-26 `test_tui.py::DrillDownTest::test_the_drill_down_prints_the_selection_it_knows_instead_of_a_dash`
         fails before with the raw id in the model cell and `-` in the other two.
         `StructureTest::test_the_drill_down_reads_the_recorded_model_and_never_a_guess` now expects
         the decoded name for the recorded selection and still expects `-` for the session with none.
Cost     `q_sessions` carries four more columns and one join; every caller that ignores them pays
         for a subquery over `credit_alloc` it does not read.
Commit   8df94ff

### D-029 · 2026-10-26 · fix
Symptom  The Usage table cut at `log_limit` and the session detail cut every list at
         `detail_limit` without a word, so a screen showing 100 of 900 rows looked exactly like a
         screen showing all 100 — the same defect as a zero that means "unknown".
Change   The Usage note ends with "showing N of M rows — raise `log_limit` for more" (the count is
         only queried when the cap was reached), and a cut detail list ends with
         "showing N of M (detail_limit)".
Evidence L0 2026-10-26 `test_tui.py::TruncationDisclosureTest` — both cases fail before (the note
         lacks the sentence; the action list shows 2 of 3 with no marker).
Cost     One extra `COUNT(*)` per Usage refresh, and only while the table is actually capped; the
         note gains a sentence that is absent whenever nothing was hidden.
Commit   8a9e8b5

### D-030 · 2026-10-26 · fix
Symptom  D-002's Evidence claims a real sync left "turns 89/89 and toolcalls 139/139 dated". On this
         machine's live index that is not true today: measured 2026-10-26, `turns.ts` is NULL in 89
         of 90 rows and `toolcall_events.ts` in 139 of 148, with `unparsed` empty and `health`
         green. Both statements are correct about their own moment: those rows were written by the
         pre-fix parser, and a cursor then told every later sync the repositories were done.
Change   Record the correction here rather than editing D-002 — an entry states what was true as of
         its commit. The repair is D-022: a parser-generation mismatch now drops the cursors, so an
         incremental sync re-reads the repositories. A new database, or `--full`, never showed the
         symptom, which is why D-002's measurement was reproducible then and is not now.
Evidence L2 2026-10-26 the live index queried read-only (`turns` 90 rows / 89 NULL, `toolcall_events`
         148 / 139 NULL, `unparsed` 0, `meta.schema_version` 5, no `parser_version`).
         L0 `test_sync.py::RunTest::test_a_parser_generation_change_reindexes_what_the_old_one_wrote`
         rebuilds exactly that state and shows the next sync repairing it.
Cost     None; the record now says which of its own numbers depended on how the index was built.
Commit   ac119c7

---

### D-031 · 2026-10-27 · chore

Symptom  本仓早已归档，但"归档"只体现在 GitHub 的那个开关上：README 与 About 都不说它停更，
         `AGENTS.md` 也没有一句"别再开发"；而 `## Listed on the GitHub profile` 一节写的是
         "本仓不在 profile 上，这不是疏忽"——一旦公开，这句话立刻变成假的。归档决定本身也没有
         任何 `D-###` 记录，读者查不到它为什么停。
         （归档的决定早于本条记录，当时没有留下日期；本条记的是 2026-10-27 的状态。）

Change   ① 仓库转为公开，随后**重新归档**——作为一次尝试的记录保留，不再维护。
         ② GitHub About 追加一句退休说明（共 346 字符，未超 350）：Trae CN 的文件和其它追踪器
           对不上，因此不再维护。topics 未动。
         ③ `README.md` / `README.zh-CN.md` 的四段式之后各加一个 `⚠️` 块：它本来要和另外三个
           追踪器并排，但 Trae CN 落盘的文件和那三家读的对不上，家族的合并视图始终没法把它
           算进去。
         ④ `AGENTS.md` 顶部加退休横幅——**不要在这里开新活**，只修主人点名要修的那一处，并在
           `D-###` 里写明本仓已退休；维度指针的节号列表补上 §9。
         ⑤ `## Listed on the GitHub profile` 翻面：从"不在榜上、且这不是疏忽"改成"在榜上、
           标了 `🧊 frozen — kept as a record`"，义务清单保留；`Freeze / archive` 一条改为
           "榜上已写明，别让后续编辑读成仍在维护"。
         ⑥ 这套程序写在 `~/.agents/standards/STANDARD.md` §9，本仓是它的第一次应用。

Evidence `python3 -m unittest discover -s scripts/tests` 仍是 287 个用例，README 的计数行未动；
         本次只改 About、README 两半、`AGENTS.md` 与 CHANGELOG。

Cost     公开意味着 43 个提交的历史也一并公开。历史 blob 里仍有 `/home/shade`（旧 CHANGELOG），
         判断是**不阻塞**：handle 本身就是 `SHADE-glitch`，而 GitHub 按 SHA 保留旧对象，重写
         历史既清不掉也换不来什么。刻意不删仓库、不改写历史。

Commit   d0d4996
