# AGENTS.md

Guidance for AI coding agents working in this repository.

> ⚠️ **Retired — archived, no longer developed.** It was built to sit beside the other three
> trackers and never could: Trae CN's local files do not line up with what they read, so the
> family's merged views could never include it. **Do not start new work here.** Fix something only
> if the owner asks for that exact fix, and say in the `D-###` entry that the repository is
> retired. `STANDARD.md` §9 is the procedure that got it here.

> **Dimension.** A — open source (strict), per `CONVENTIONS.md` §0; the shared rules live once in
> `~/.agents/standards/STANDARD.md` (§1 root files, §2 process drafts, §3 CHANGELOG entries,
> §4 runtime ignore list, §5 conflict rule, §6 remotes/pushing, §8 profile listing, §9 retirement)
> and the dimension-A detail in `~/.agents/standards/dimensions/a.md`. Neither is restated here.
>
> **Read these before the first edit** (bare `@` imports — CodeBuddy expands them; opencode reads
> the same two from `opencode.json`):
> @~/.agents/standards/STANDARD.md
> @~/.agents/standards/dimensions/a.md

## What this is

A **passive** usage tracker for Trae CN: it reads the plaintext files Trae leaves under
`~/.trae-cn` and `~/.config/Trae CN`, builds a local SQLite index, and presents it in an eight-tab
Textual TUI (plus a headless `tcut` CLI). Three layers, in dependency order:

1. `scripts/tcut-sync.py` — the parser and indexer. Reads the Trae footprint **read-only**
   (`memory/` prose, `ModularData/ai-agent/snapshot/**/.git` annotated tags, `state.vscdb`,
   `skills/`, `plugins/`, `mcps/`, `logs/**/renderer.log`) and classifies sessions, prompts,
   agents, tool-call ids, inventory and credit samples into
   `~/.local/share/trae-cn-usage-tracker/usage.db`.
2. `scripts/tcut_db.py` — the shared data layer (schema, queries, calendar-day windows, snapshots).
   Imported by the TUI, the stats CLI and the tests.
3. `scripts/tcut-tui.py` (Textual) and `scripts/tcut-stats.py` (headless CLI).

**There are two writers, not one.** `tcut sync` is the only thing that indexes the Trae footprint,
but the TUI also writes: `on_mount` runs `db.migrate()` (a read-write connection, DDL included) and
its auto-sync worker (`_auto_sync_tick` → `_do_sync` → `tcut-sync.run()`) calls the same indexer
the CLI does. Anything that assumes "the TUI is read-only" is wrong — reason about locks and
migrations accordingly. The headless CLI is read-only except for its explicit maintenance
subcommands (`backup`, `restore`, `format --write`).

`bin/tcut` is a bash dispatcher. **It is bash on purpose**: it must still run and print a useful
error when the TUI venv is missing or broken, so it cannot depend on any Python.

**The eight tab slots are shared with the sibling trackers, not owned by this repository.**
`Dashboard · Tools · Skills · Agents · Plugins · MCP · Tokens · Usage` is the same list, in the same
order, as `codebuddy-usage-tracker` and `qoder-cn-usage-tracker`; only the data behind a slot
differs. A slot here ships what Trae actually records and **names on its own note line what it does
not have** — never a placeholder that reads as `0` and never a removed tab. See the hard rule below.

This repository is private.

## Scope

This repository is a passive reader for **Trae CN only**. Do not broaden it to international Trae
or to CodeBuddy transcripts without an explicit design decision.

## Commands

```sh
python3 -m unittest discover -s scripts/tests     # stdlib unittest; pytest discovers them too
python3 -m pyflakes scripts/*.py                  # must be silent (needs `pip install pyflakes`)
./install.sh                                      # create .venv + link bin/tcut
bash -n bin/tcut                                  # syntax-check the dispatcher
```

Single file, by module path: `python3 -m unittest scripts.tests.test_sync`.

**Run the suite with the project venv** (`.venv/bin/python -m unittest …`). `test_tui.py` and
`test_config.py` need `textual`; the rest are stdlib-only and run anywhere. On a bare interpreter
without `textual`, `test_tui.py` reports *errors* from the TUI's own dependency guard: that is a
missing package, not a Python-version failure — do not read it as one.

## CI

GitHub Actions runs on every `push` and `pull_request` (`.github/workflows/ci.yml`, Python matrix
of **3.11 and 3.14** — the `requires-python` floor and the highest version the suite was run green
on):

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s scripts/tests
```

The checkout must fetch full history (`fetch-depth: 0`): `test_record_coverage.py` walks
`git log <anchor>..HEAD` back to the anchor declared in `CHANGELOG.md`'s `Coverage:` line, which a
shallow clone cannot resolve.

**It must stay green.** A red CI is a broken contract, not a warning: this is the same command as
the L0 verification tier below, so a change that fails here fails everywhere. Run it locally before
pushing — do not leave the first run to CI.

**Green CI does not certify the interpreter you are using.** CI runs 3.11 and 3.14; `install.sh`
builds a venv on whatever `python3` it finds. If a change depends on interpreter behaviour, say
which version you actually ran, and consider widening the matrix rather than assuming those two
speak for all of them.

- **Keep CI in step with the code.** Update `.github/workflows/ci.yml` in the *same change* that
  makes it stale — never as a later cleanup.
- **New or renamed tests need no CI edit** as long as CI runs the discovery command; it does, so it
  picks them up automatically. Only touch CI if the *command itself* changes.
- **Environment changes** — a new dependency, a Python version bump, or a new system tool — mean
  updating the workflow's setup/install steps.
- **Renamed or moved code**: the record-coverage test watches a declared list of code paths. If a
  watched path moves, update that list; the test goes red until you do.
- **After a refactor**, confirm CI still exercises the real code and the declared paths still cover
  it. A green CI that no longer touches the changed code is worse than a red one.
- **A new verification tier** (e.g. a live/TUI layer) — decide explicitly whether CI runs it; do
  not add it silently.
- If what CI runs changes, update this section too. CI is a signal, not a gate, until branch
  protection is enabled — read the result after every push.

## Release / version

The project's version lives in `pyproject.toml` (`[project].version`) and nowhere else; it is
currently `0.5.0`. Bump it in that one file when a release is cut — the READMEs and `CHANGELOG.md`
describe behaviour and do not carry a version to keep in sync. There is no PyPI publish step: the
tool runs from a checkout, so the version only needs to move when a documented change ships.

## Hard rules

- Read Trae's directories; never write into them.
- Keep the tracker database local. No network, upload, telemetry, or subprocess path in production scripts.
- Tests use throwaway databases and Trae host trees under temporary directories. They must never open `~/.local/share/trae-cn-usage-tracker/usage.db` or read the real `~/.trae-cn` / `~/.config/Trae CN`; `_hermetic.py` enforces both with an audit hook, and every `test_*.py` imports it.
- Treat encrypted `ModularData/ai-agent/database.db` as unreadable. Do not guess its schema or claim tool names/tokens that are not in plaintext sources. The absence of token counts on disk is a measurement (8.000 bits/byte, zero keyword hits, 11,837 files walked), recorded in `docs/maintenance/trae-cn-format.md` — re-measure before believing any claim that a new source has them.
- From a model catalog entry, read only the documented whitelist. `ak`, `sk`, `base_url` and `custom_config` can carry credentials for a custom endpoint and must never be stored; `test_sync.py::VscdbTest.test_a_model_entrys_credentials_are_never_stored` scans every value of every table to prove it.
- A credit balance is a *level* sampled at app start. `spent >=` is a lower bound derived at query time; never store or print it as measured consumption, and never turn a `skipped` fetch into a `0`.
- `models` is keyed by (account, group_name, name), never by name: one real footprint holds 284 entries under 42 distinct names, and a name-only key discards 242 of them while still reporting `unparsed=0`.
- Snapshot refs name **annotated tag objects**, not commits (measured: 87/87 in one repo). `_commit_time` must peel the tag to its `object` commit, and an object it cannot read must increment `unparsed` as `snapshot:time_unreadable` instead of silently storing `NULL`. A fixture must reproduce the shape measured on disk: lightweight-ref fixtures kept the whole suite green while every real turn and toolcall timestamp was being lost.
- A window must never report a zero for rows it cannot see. A windowed count renders `-` (`db.window_count`) only when the row has **neither** a measured `last_ts` nor a derived `created_ts`; `0` is reserved for a measured absence. On this machine that population is empty (0 of 49 sessions) — the rule stays because Trae wrote 25 of 49 rows with no timestamp at all and could stop writing the id prefix tomorrow. A drill-down inherits the window of the row it was opened from, or the two numbers disagree on one screen. A leaderboard that drops zero rows must keep the `-` ones. A blank panel names the blank it is showing — `none dated in <range>` (the range placed no session), `no session in this range names an installed agent` (it placed sessions that carry no label), `no agents installed` (the inventory table itself is empty) — because the three have three different fixes and only the first belongs to the range picker. The middle one is the common case here, not a hypothetical: measured 2026-10-12, 24 of 49 sessions carry no `agent` at all and every one of the 20 sessions in the current 7d window is label-less, which is exactly the state in which a "widen the range" sentence sends the reader to change a setting that cannot change anything.
- A total over rows that never carried the field prints `-`, never `0`. `q_entity_totals` returns `projects_missing` beside `projects` for exactly that reason (measured 2026-10-13: 28 of 49 sessions have neither a decoded project nor a raw key, so `0 projects` claims a world fact instead of a missing field). The reverse binds too: `turns` and `toolcalls` are **never** NULL (0 of 49 — the writer always stores a number, and 25 rows store `0`), so a stored zero prints as `0`; dashing it would flatten "no turns" into "the snapshot had no tags". Read the pair with `db.window_count`, and check what the writer actually stores before adding a second dash.
- `sessions.created_ts` is **derived**, never measured: it is the session id's first four hex bytes (re-measured 2026-10-12 against the 24 dated sessions: median delta 0.0 s, worst 144 s, no turn predates it — a floor, not a guess). Do not write it into `first_ts`/`last_ts`, which mean measured activity — and neither does the memory folder's day, which is a date, not a clock: it belongs in `sessions.day` and nowhere else. It enters a window only through `db.SESSION_TIME` (`COALESCE(last_ts, created_ts)`), and any surface that prints a position earned this way prints `db.derived_mark` (`~`) in front of it and discloses how many rows it applies to (`q_kpi["unmeasured"]`). A list where a derivation looks exactly like a measurement is how a derivation becomes a fact.
- `store_content = true` is an intentional project decision: session summaries, prompt history, and memory prose may be stored in the local SQLite database. `store_content = false` must purge that prose while preserving metadata. It is a **documented, deliberate departure** from the metadata-only rule the sibling trackers hold — never describe this repository as "no message bodies".
- **A tab slot is filled with what the data is, and names what it is not.** The eight slots are shared with `codebuddy-usage-tracker` and `qoder-cn-usage-tracker`, so the tab set is never trimmed to fit a sparse source and a slot is never left empty — an empty token panel reads as "0 tokens" or as a broken widget, and neither is true. Instead: **Tools** aggregates `toolcall_events` per session, which is a **count**, never a per-tool ranking (snapshot tags name `toolcall-<messageId>-<toolcallId>` and Trae stores no tool name anywhere readable); **Tokens** ranks decoded model routes by an estimate built from the credit samples Trae does write, states `est.` on every surface, tags third-party routes `3P`, and keeps a token column that is always `-` because no source writes one; **Usage** aggregates **per (session, model selection)**, not per request, because there is no per-request record on disk at all. Each of those notes is part of the contract, not decoration: delete the caveat and the panel becomes a claim. Add a slot's caveat to the README table and the tab's note line in the same change.
- **The README's eight-row tab table is generated from the same truth as the TUI.** `README.md` and `README.zh-CN.md` each carry one row per tab; if a tab's data source changes, all three (TUI note, both READMEs) change together.

## Conventions

- **Settings are read once, in one place.** `db.load_config()` resolves environment > file > `DEFAULTS`. Adding a knob means: one entry in `DEFAULTS`, one in `ENV_NAMES`, one in `_BOUNDS`, and one assignment in the app — `test_config.py::test_the_defaults_match_the_tuis_own_constants` compares each key the TUI reads against the class constant it shadows, so a settings layer cannot quietly retune shipped behaviour. The READMEs are part of the surface, not documentation someone does later: `test_both_readmes_document_every_setting` requires every default and every override name to appear in both languages. `tcut health` prints whatever `load_config()` returned, keyed by the names the file uses (`test_health_prints_every_key_the_loader_knows` enumerates `DEFAULTS` against the output), so a knob cannot be added and go unreported. A malformed file raises `ConfigError` and the entry point turns it into a message naming the path; **never fall back silently**.
- **A settings case must pass in someone else's shell.** Anything asserting the file or the defaults is asserting them *under* the environment, which outranks both — so the case reads as a settings-layer regression the moment a developer exports one `TCUT_*` value. `test_config.py` wraps those cases in `no_settings_env()`, which hides **every name derived from `db.ENV_NAMES`**.
- **A behaviour change ships with a case that fails without it.** If no test goes red when you undo the change, the change is not verified yet — and provoke it: remove the fix on purpose and read the failure.
- **A comment that describes behaviour is a claim.** The three stale comments this round found were all *assertions that stayed true while their prose went false* — `DEFAULTS["log_limit"]` still said "Prompts page rows" after the Usage page became its second reader, and `test_config.py` still excused `log_limit` from the constants comparison for the same reason. No test catches that class of drift; read the comment.

## Docs & commits

- **Docs are bilingual**: `README.md` (English, landing page) and `README.zh-CN.md` (Chinese). Edit both together and keep section order aligned; a section added on one side alone is drift.
- Commit messages are **English**, in the repository's own Conventional style (`feat` / `fix` / `test` / `docs` / `guard` / `chore`), code before docs.

## Recording conventions

Common CHANGELOG rules: `~/.agents/standards/STANDARD.md` §3.

- The `feat` exclusion is one regex over the commit subject inside the check; it must not decay into a per-commit skip flag. Features are documented in the READMEs.
- The record is held to the same metadata-not-content rule as the code.
- Run the coverage check before committing production code: `python3 -m unittest scripts.tests.test_record_coverage`. It is part of the suite.

## Verification

Named by what the claim needs, not by the tool:

- **L0** — `python3 -m unittest discover -s scripts/tests` (temp database, no host).
- **L1** — a throwaway store outside the repository, fed by the real footprint: `TCUT_DB=/tmp/tcut-check.db python3 scripts/tcut-sync.py`. This is where parser changes are proved, and a sync report covering every table's row count is how a regression in a table you did not touch stays visible.
- **L2** — the real `~/.local/share/trae-cn-usage-tracker/usage.db`. Needs the owner's go-ahead; a destructive step takes a snapshot first.

## Invariants and how to check them
Five promises are load-bearing enough that prose is not proof. Each has a command that fails when
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

**5. All eight tab slots are present, in family order.** The tab set matches
`codebuddy-usage-tracker` and `qoder-cn-usage-tracker` name for name, so a reader who knows one can
navigate the other — and a slot is never dropped to make a sparse source look tidy.

```bash
python3 -m unittest scripts.tests.test_tui      # the eight pane ids and their labels, in order
```

`test_the_eight_tabs_are_present_and_in_order` asserts the ids **and** the visible labels against a
literal, so renaming a tab or reordering two fails here rather than silently breaking the family
convention. It is deliberately a literal, not a comparison against the sibling repositories: those
are separate checkouts that CI does not read, and a check that silently compares nothing is worse
than no check.

The complement — that each slot *discloses* what it lacks — is not machine-checked. A slot can be
present and still lie, which is why the per-slot caveats are pinned in the hard rules above and
repeated in both READMEs.

Maintenance material — the format surface itself, the version matrix, the size and latency baseline
— lives in [`docs/maintenance/`](docs/maintenance/), and `test_maintenance_docs.py` keeps the
generated part of it tied to the code.

## Format coupling

Trae owns the data; this tool only reads it. **The main maintenance risk is upstream changing the file shapes**, and the failure mode is silent: a renamed field reads as `NULL`, a renamed source is simply unclaimed, the panels empty out, `tcut sync` prints "done", and CI stays green.

Keep parser assumptions in `docs/maintenance/trae-cn-format.md`. If a Trae file shape changes, update the format note, the fixture test, and the unparsed reason that makes the change observable.

## Listed on the GitHub profile

**This repository is on the owner's profile front page, marked `🧊 frozen — kept as a record`.** It
was made public and listed on 2026-10-27, after the retirement decision, so a reader finds it as a
record of the attempt rather than as a tool to install. The profile's own `AGENTS.md` is the
authoritative rulebook, and its §6 index is the reciprocal of this section.

Because it is listed, these facts must stay true on the front page:

- **Rename / transfer / delete** — the profile link dies; fix the row.
- **Purpose drift** — the profile's one-line description must still be true; the claims it copies —
  *"no network"*, "dev tooling" — are **promises**, not slogans.
- **LICENSE change** — the profile's license badge must equal this repo's `LICENSE`.
- **Version / runtime declaration change** — the matching badge must equal this repo's declaration.
- **Freeze / archive** — already stated on the profile; keep the `🧊` marker and never let a later
  edit make the row read as maintained.
- **Public ↔ private** — a repo that goes private again must be **delisted**.

**The GitHub About description is under the same rule.** It is a promise with 350 characters, and it
must describe *this* repository, not the family. Two facts a copy of a sibling's About gets wrong:

- **No "no message bodies"** — that promise belongs to `codebuddy-usage-tracker`. `store_content`
  defaults to `true` here, so prose **is** stored locally. The honest claim is *"No network"* plus
  where the data comes from.
- **No "per-model tokens"** — this tracker reads no token count at all, from any file, ever
  (invariant in "Hard rules"). The `Tokens` tab exists because the slot is shared across the family;
  it carries a per-route credit **estimate** and says so, and its token column is deliberately blank.

