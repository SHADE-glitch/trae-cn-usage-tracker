# AGENTS.md

Guidance for AI coding agents working in this repository.

> **Shared standard.** Root file names, the process-draft location (`docs/reports/`), the
> `CHANGELOG` entry format, CI version pinning and entry commands, the test entry command, and
> the runtime ignore list are defined once in the machine-wide `STANDARD.md` (outside this
> repository) and are not restated here.
>
> **Push over SSH, never HTTPS.** Verify `git remote get-url --push origin` starts with `git@`
> before pushing; if it starts with `https://`, fix it first — never push over HTTPS.

## What this is

A **passive** usage tracker for Trae CN: it reads the plaintext files Trae leaves under
`~/.trae-cn` and `~/.config/Trae CN`, builds a local SQLite index, and presents it in a five-tab
Textual TUI plus a headless `tcut` CLI. The parser and indexer live in `scripts/tcut-sync.py`, the
shared data layer (schema, queries, windows, snapshots) in `scripts/tcut_db.py`, and the two front
ends in `scripts/tcut-tui.py` (Textual) and `scripts/tcut-stats.py` (headless CLI).

`bin/tcut` is a bash dispatcher. **It is bash on purpose**: it must still run and print a useful
error when the TUI venv is missing or broken, so it cannot depend on any Python.

## Scope

This repository is a passive reader for **Trae CN only**. Do not broaden it to international Trae
or to CodeBuddy transcripts without an explicit design decision.

## Commands

```sh
python3 -m unittest discover -s scripts/tests     # stdlib unittest; pytest discovers them too
python3 -m pyflakes scripts/*.py                  # must be silent
./install.sh                                      # create .venv + link bin/tcut
bash -n bin/tcut                                  # syntax-check the dispatcher
```

## Hard rules

- Read Trae's directories; never write into them.
- Keep the tracker database local. No network, upload, telemetry, or subprocess path in production scripts.
- Tests use throwaway databases under temporary directories. They must never open `~/.local/share/trae-cn-usage-tracker/usage.db`; `_hermetic.py` enforces this with an audit hook, and every `test_*.py` imports it.
- Treat encrypted `ModularData/ai-agent/database.db` as unreadable. Do not guess its schema or claim tool names/tokens that are not in plaintext sources. The absence of token counts on disk is a measurement (8.000 bits/byte, zero keyword hits, 11,837 files walked), recorded in `docs/maintenance/trae-cn-format.md` — re-measure before believing any claim that a new source has them.
- From a model catalog entry, read only the documented whitelist. `ak`, `sk`, `base_url` and `custom_config` can carry credentials for a custom endpoint and must never be stored; `test_sync.py::VscdbTest.test_a_model_entrys_credentials_are_never_stored` scans every value of every table to prove it.
- A credit balance is a *level* sampled at app start. `spent >=` is a lower bound derived at query time; never store or print it as measured consumption, and never turn a `skipped` fetch into a `0`.
- `models` is keyed by (account, group_name, name), never by name: one real footprint holds 284 entries under 42 distinct names, and a name-only key discards 242 of them while still reporting `unparsed=0`.
- Snapshot refs name **annotated tag objects**, not commits (measured: 87/87 in one repo). `_commit_time` must peel the tag to its `object` commit, and an object it cannot read must increment `unparsed` as `snapshot:time_unreadable` instead of silently storing `NULL`. A fixture must reproduce the shape measured on disk: lightweight-ref fixtures kept the whole suite green while every real turn and toolcall timestamp was being lost.
- A window must never report a zero for rows it cannot see. A windowed count renders `-` (`db.window_count`) only when the row has **neither** a measured `last_ts` nor a derived `created_ts`; `0` is reserved for a measured absence. On this machine that population is empty (0 of 49 sessions) — the rule stays because Trae wrote 25 of 49 rows with no timestamp at all and could stop writing the id prefix tomorrow. A drill-down inherits the window of the row it was opened from, or the two numbers disagree on one screen. A leaderboard that drops zero rows must keep the `-` ones. A blank panel names the blank it is showing — `none dated in <range>` (the range placed no session), `no session in this range names an installed agent` (it placed sessions that carry no label), `no agents installed` (the inventory table itself is empty) — because the three have three different fixes and only the first belongs to the range picker. The middle one is the common case here, not a hypothetical: measured 2026-10-12, 24 of 49 sessions carry no `agent` at all and every one of the 20 sessions in the current 7d window is label-less, which is exactly the state in which a "widen the range" sentence sends the reader to change a setting that cannot change anything.
- A total over rows that never carried the field prints `-`, never `0`. `q_entity_totals` returns `projects_missing` beside `projects` for exactly that reason (measured 2026-10-13: 28 of 49 sessions have neither a decoded project nor a raw key, so `0 projects` claims a world fact instead of a missing field). The reverse binds too: `turns` and `toolcalls` are **never** NULL (0 of 49 — the writer always stores a number, and 25 rows store `0`), so a stored zero prints as `0`; dashing it would flatten "no turns" into "the snapshot had no tags". Read the pair with `db.window_count`, and check what the writer actually stores before adding a second dash.
- `sessions.created_ts` is **derived**, never measured: it is the session id's first four hex bytes (re-measured 2026-10-12 against the 24 dated sessions: median delta 0.0 s, worst 144 s, no turn predates it — a floor, not a guess). Do not write it into `first_ts`/`last_ts`, which mean measured activity. It enters a window only through `db.SESSION_TIME` (`COALESCE(last_ts, created_ts)`), and any surface that prints a position earned this way prints `db.derived_mark` (`~`) in front of it and discloses how many rows it applies to (`q_kpi["unmeasured"]`). A list where a derivation looks exactly like a measurement is how a derivation becomes a fact.
- `store_content = true` is an intentional project decision: session summaries, prompt history, and memory prose may be stored in the local SQLite database. `store_content = false` must purge that prose while preserving metadata.

## Conventions

- **Docs are bilingual**: `README.md` (English, landing page) and `README.zh-CN.md` (Chinese). Edit both together and keep section order aligned; a section added on one side alone is drift.
- **A behaviour change ships with a case that fails without it.** If no test goes red when you undo the change, the change is not verified yet — and provoke it: remove the fix on purpose and read the failure.
- Commit messages are **English**, in the repository's own Conventional style (`feat` / `fix` / `test` / `docs` / `guard` / `chore`), code before docs.

## Recording conventions

- **`feat` commits are out of scope, by class.** This is an original project with no upstream, so a feature is the product, not a droppable deviation — features are documented in the READMEs. The exclusion is one regex over the commit subject inside the check; it must not decay into a per-commit skip flag.
- `kind` ∈ `fix` | `perf` | `taste` | `guard` | `revert` | `chore`, cut by **who may demand a revert**: bug → `fix`; measurable degradation only → `perf`; only my taste → `taste` (zero obligation, discardable on an upgrade); no behaviour change, detects drift → `guard`; withdraws earlier work → `revert`; cleanup owed nothing either way → `chore`.
- **An empty covered window is legal only when the header says so.** If the window contains covered commits but the record has no entries, the check fails: a pass over an empty set proves nothing.
- `Symptom` names the mechanism, never the session: no prompt text, no command lines, no tool argument values, no real paths from `~/.trae-cn`. The record is held to the same metadata-not-content rule as the code.
- Run the coverage check before committing production code: `python3 -m unittest scripts.tests.test_record_coverage`. It is part of the suite.

## Verification

Named by what the claim needs, not by the tool:

- **L0** — `python3 -m unittest discover -s scripts/tests` (temp database, no host).
- **L1** — a throwaway store outside the repository, fed by the real footprint: `TCUT_DB=/tmp/tcut-check.db python3 scripts/tcut-sync.py`. This is where parser changes are proved, and a sync report covering every table's row count is how a regression in a table you did not touch stays visible.
- **L2** — the real `~/.local/share/trae-cn-usage-tracker/usage.db`. Needs the owner's go-ahead; a destructive step takes a snapshot first.

## CI

`.github/workflows/ci.yml` runs the offline suite on a Python 3.11 / 3.14 matrix — the declared floor
(`requires-python`) and the highest version measured green here. It is not the interpreter you develop
on (`install.sh` builds a venv), and a green run says nothing about a version it did not run.

## Release / version

The project's version lives in `pyproject.toml` (`[project].version`) and nowhere else; it is
currently `0.5.0`. Bump it in that one file when a release is cut — the READMEs and `CHANGELOG.md`
describe behaviour and do not carry a version to keep in sync. There is no PyPI publish step: the
tool runs from a checkout, so the version only needs to move when a documented change ships.

## Invariants and how to check them

Four promises are load-bearing enough that prose is not proof. Each has a command that fails when
the promise breaks — a rule without a check is a preference.

**1. Nothing leaves the machine.** No production script imports a socket, HTTP client, mail,
process-spawning or thread module, and none reaches a module by name.

```bash
python3 -m unittest scripts.tests.test_privacy      # AST import allowlist over the 4 production scripts
```

The check keeps an allowlist of roots per file and names the forbidden ones broadly (raw sockets,
`subprocess`, `multiprocessing`, `threading`), so adding one is a test failure rather than a quiet
convention change. A second pass catches a module reached through `__import__` /
`importlib.import_module` / `eval` / `exec`, which the import allowlist cannot see, and a self-test
proves that detector actually fires.

**2. Trae's own tree is never written.** `~/.trae-cn` and `~/.config/Trae CN` are opened for reading
only; indexing leaves them byte-identical.

```bash
python3 -m unittest scripts.tests.test_privacy      # fingerprints a fixture Trae tree around a real index run
```

The test builds a Trae-shaped fixture, hashes every file, runs the actual indexer over it, and
re-hashes: one changed byte fails it, and it asserts nothing new appeared beside the database (no
stray journal or side file). This is the invariant most likely to be broken by accident — a stray
`open(..., "w")` on a Trae path — so it is proven by content hash rather than by review.

**3. Content is stored only through the documented switch.** Prose (session summaries, prompt
history, memory paragraphs) *is* kept when `store_content = true` — the default, and the point of
the tool, since Trae CN persists nothing else readable. With `store_content = false` the database
must hold **zero** prose in any table.

```bash
python3 -m unittest scripts.tests.test_privacy      # sentinels in every prose slot, scanned across every text column
```

The sentinel test turns the switch off and scans **every text value of every table** — not the
columns named today, because a leak moved once the moment it was guarded in a named column — for
seven sentinel paragraphs placed where handlers genuinely read. It carries a positive control
(identifiers that *must* survive), without which the scan would pass on a database that indexed
nothing. A second test proves the switch also **purges** prose already stored.

**4. A model entry's credentials are never stored.** A custom-provider catalog entry carries
`ak` / `sk` / `base_url` / `custom_config` next to the fields we do read; the whitelist is the only
thing between those and the index.

```bash
python3 -m unittest scripts.tests.test_sync          # sentinel credentials scanned against everything stored
python3 -m unittest scripts.tests.test_format_registry
```

The first feeds `ak`/`sk`/`base_url`/`custom_config` sentinels into a catalog entry and asserts none
reaches any stored value while the entry itself lands. The second is the static half: it fails if
one of those names ever appears as a `.get()` key in the reader, which is how a credential would
first reach the index.

Maintenance material — the format surface itself, the version matrix, the size and latency baseline
— lives in [`docs/maintenance/`](docs/maintenance/), and `test_maintenance_docs.py` keeps the
generated part of it tied to the code.

## Format coupling

Trae owns the data; this tool only reads it. **The main maintenance risk is upstream changing the file shapes**, and the failure mode is silent: a renamed field reads as `NULL`, a renamed source is simply unclaimed, the panels empty out, `tcut sync` prints "done", and CI stays green.

Keep parser assumptions in `docs/maintenance/trae-cn-format.md`. If a Trae file shape changes, update the format note, the fixture test, and the unparsed reason that makes the change observable.

## Listed on the GitHub profile

**This repository is not on the owner's profile front page, and that is not an oversight.** It is a
**private** repository, and `SHADE-glitch/SHADE-glitch` lists public repositories only — the two
whitelisted private repos are the sole exception, and this is not one of them. The profile's own
`AGENTS.md` is the authoritative rulebook, and its §1 is explicit on both counts: naming another
private repo needs the owner's spoken approval first, and **a repo must never be flipped to public
just so it can be listed** — that is a privacy decision, not a profile edit.

So there is no listing obligation today, and this section exists to say so rather than to be
silently absent. If the repo is ever made public **and** added to the profile, this section becomes
the reciprocal of the profile's §6 index, and these facts must then be kept true on the front page:

- **Rename / transfer / delete** — the profile link dies; fix the row.
- **Purpose drift** — the profile's one-line description must still be true; the claims it copies —
  *"no network"*, "dev tooling" — are **promises**, not slogans.
- **LICENSE change** — the profile's license badge must equal this repo's `LICENSE`.
- **Version / runtime declaration change** — the matching badge must equal this repo's declaration.
- **Freeze / archive** — say so on the profile; never leave a stale "maintained".
- **Public ↔ private** — a repo that goes private again must be **delisted**.

