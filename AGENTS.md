# AGENTS.md — Trae CN Usage Tracker

## Scope

This repository is a passive reader for Trae CN only. Do not broaden it to international Trae or to CodeBuddy transcripts without an explicit design decision.

本仓库只被动读取 Trae CN。未经明确设计决策，不要扩展到国际版 Trae 或 CodeBuddy transcript。

## Hard rules

- Read Trae's directories; never write into them.
- Keep the tracker database local. No network, upload, telemetry, or subprocess path in production scripts.
- Tests use throwaway databases under temporary directories. They must never open `~/.local/share/trae-cn-usage-tracker/usage.db`; `_hermetic.py` enforces this with an audit hook.
- Treat encrypted `ModularData/ai-agent/database.db` as unreadable. Do not guess its schema or claim tool names/tokens that are not in plaintext sources. The absence of token counts on disk is a measurement (8.000 bits/byte, zero keyword hits, 11,837 files walked), recorded in `docs/maintenance/trae-cn-format.md` — re-measure before believing any claim that a new source has them.
- From a model catalog entry, read only the documented whitelist. `ak`, `sk`, `base_url` and `custom_config` can carry credentials for a custom endpoint and must never be stored; `test_sync.py::VscdbTest.test_a_model_entrys_credentials_are_never_stored` scans every value of every table to prove it.
- A credit balance is a *level* sampled at app start. `spent >=` is a lower bound derived at query time; never store or print it as measured consumption, and never turn a `skipped` fetch into a `0`.
- `models` is keyed by (account, group_name, name), never by name: one real footprint holds 284 entries under 42 distinct names, and a name-only key discards 242 of them while still reporting `unparsed=0`.
- Snapshot refs name **annotated tag objects**, not commits (measured: 87/87 in one repo). `_commit_time` must peel the tag to its `object` commit, and an object it cannot read must increment `unparsed` as `snapshot:time_unreadable` instead of silently storing `NULL`. A fixture must reproduce the shape measured on disk: lightweight-ref fixtures kept the whole suite green while every real turn and toolcall timestamp was being lost.
- A window must never report a zero for rows it cannot see. A windowed count renders `-` (`db.window_count`) only when the row has **neither** a measured `last_ts` nor a derived `created_ts`; `0` is reserved for a measured absence. On this machine that population is empty (0 of 49 sessions) — the rule stays because Trae wrote 25 of 49 rows with no timestamp at all and could stop writing the id prefix tomorrow. A drill-down inherits the window of the row it was opened from, or the two numbers disagree on one screen. A leaderboard that drops zero rows must keep the `-` ones. A blank panel names the blank it is showing — `none dated in <range>` (the range placed no session), `no session in this range names an installed agent` (it placed sessions that carry no label), `no agents installed` (the inventory table itself is empty) — because the three have three different fixes and only the first belongs to the range picker. The middle one is the common case here, not a hypothetical: measured 2026-10-12, 24 of 49 sessions carry no `agent` at all and every one of the 20 sessions in the current 7d window is label-less, which is exactly the state in which a "widen the range" sentence sends the reader to change a setting that cannot change anything.
- `sessions.created_ts` is **derived**, never measured: it is the session id's first four hex bytes (re-measured 2026-10-12 against the 24 dated sessions: median delta 0.0 s, worst 144 s, no turn predates it — a floor, not a guess). Do not write it into `first_ts`/`last_ts`, which mean measured activity. It enters a window only through `db.SESSION_TIME` (`COALESCE(last_ts, created_ts)`), and any surface that prints a position earned this way prints `db.derived_mark` (`~`) in front of it and discloses how many rows it applies to (`q_kpi["unmeasured"]`). A list where a derivation looks exactly like a measurement is how a derivation becomes a fact.
- `store_content = true` is an intentional project decision: session summaries, prompt history, and memory prose may be stored in the local SQLite database. `store_content = false` must purge that prose while preserving metadata.
- Commit messages are English, in the repository's own Conventional style (`feat` / `fix` / `test` / `docs` / `guard` / `chore`).

## Verification

Run:

```sh
python3 -m unittest discover -s scripts/tests
python3 -m pyflakes scripts/*.py
```

The first command must finish with `OK`; the second must be silent. A real-footprint read-only check may use `TCUT_DB=/tmp/tcut-check.db tcut sync --quiet`, never the default database.

## Change discipline

Keep parser assumptions in `docs/maintenance/trae-cn-format.md`. If a Trae file shape changes, update the format note, the fixture test, and the unparsed reason that makes the change observable.
