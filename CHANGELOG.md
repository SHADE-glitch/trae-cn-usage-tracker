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
