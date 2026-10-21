<p align="right"><a href="README.md"><b>English</b></a> | <a href="README.zh-CN.md">简体中文</a></p>

# 🐾 Trae CN Usage Tracker (`tcut`)

![Trae CN](https://img.shields.io/badge/Trae%20CN-reads%20local%20files-blue?logo=robotframework&logoColor=white)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-ff69b4?logo=terminal&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey?logo=linux&logoColor=black)
[![Repository](https://img.shields.io/badge/repository-GitHub-black?logo=github)](https://github.com/SHADE-glitch/trae-cn-usage-tracker)

**What it is** — A passive, read-only tracker for Trae CN: an eight-tab TUI and headless reports over the skills, agents, plugins and MCP servers installed, the tool calls made, and the credit balance the account was left at.

**What it solves** — Trae CN persists little that is readable; `tcut` indexes what it can into one local SQLite file and is honest about the gaps it cannot fill.

**How to run** — `./install.sh`, then `tcut sync`.

**Where to look** — See [AGENTS.md](AGENTS.md) and [MAINTENANCE.md](MAINTENANCE.md).

> 🔭 See how you **actually** use Trae CN — every 🎯 skill, 🤖 agent, 🧩 plugin and
> 🔌 MCP server that is installed, every 🧰 tool call that was made, and the 💳 credits
> the account was left at.

---

## 📖 Table of Contents

- [✨ Features](#-features)
- [🤔 Why this exists](#-why-this-exists)
- [📝 What is recorded, and what is not](#-what-is-recorded-and-what-is-not)
- [🏗️ How it works](#️-how-it-works)
- [📊 The eight tabs](#-the-eight-tabs)
- [💳 Credits vs tokens](#-credits-vs-tokens)
- [📋 Requirements](#-requirements)
- [🚀 Install](#-install)
- [🧭 Usage](#-usage)
- [⚙️ Configuration](#️-configuration)
- [🔒 Storage and privacy](#-storage-and-privacy)
- [🧪 Testing](#-testing)
- [📁 Repository layout](#-repository-layout)
- [📚 Maintenance notes](#-maintenance-notes)
- [⚠️ Limitations & roadmap](#️-limitations--roadmap)
- [🧹 Uninstall](#-uninstall)
- [🙏 Attribution](#-attribution)
- [📄 License](#-license)

## ✨ Features

- 🧰 **Eight views, one command** — a dashboard, tools, skills, agents, plugins, MCP, tokens, usage.
- 📜 **Full history, instantly** — backfills every session already on disk; only new bytes after that.
- 🪶 **Passive & read-only** — no hook, no plugin, no Trae source changes. Trae's own directories are opened for reading and hashed byte-identical afterwards.
- 🗃️ **One local SQLite file** — no network, no upload, no telemetry.
- 💳 **Honest about the two gaps** — the slot other trackers fill with model tokens is filled here with a **per-route credit estimate** (marked `est.`, with `3P` routes tagged); the token column stays blank and says why, and every panel that has no data source says so in words instead of drawing zeros.
- 🧰 **Tool calls counted per session** — Trae's snapshot repositories name a call by id and never by name, so the Tools tab aggregates ids into sessions rather than inventing a tool it cannot read.
- 📅 **Calendar-day windows, per tab** — the top-bar range (Today / 2 days / 3 days / 7 days / 14 days / 30 days / All time) is kept **per tab**, so changing one never moves another. Entity tabs default to **7 days**, the Dashboard and the Tokens / Usage pages to **7 days**, and Skills, Plugins and MCP are always all-time. Windows are whole local calendar days (00:00 → now), never "now minus N hours".
- 🔎 **Two-level drill-down** — <kbd>Enter</kbd> or double-click a row on Tools or Agents to open that session's detail screen: its intent, its actions, what it learned, its topics, the model it selected and its credit window.
- 📝 **Prose is stored, on purpose and on a switch** — session summaries, prompts and memory paragraphs are kept in the local database by default, because Trae CN persists nothing else readable. `store_content = false` purges them and keeps the metadata. This is a documented deviation from the metadata-only rule the sibling trackers follow, and it is one setting away from being off.
- 🔐 **A derived time never reads as a measured one** — 25 of this machine's 49 sessions carry no timestamp anywhere in Trae's plaintext, so a session id's creation second is used instead and printed with a leading `~`, with the count of such rows disclosed on the panel.

## 🤔 Why this exists

Trae CN **writes** the raw data — it just never **shows** it. It keeps:

- 📜 **per-session summaries, topic lines and memory prose** under `~/.trae-cn/memory/`;
- 🏷️ **annotated snapshot tags** in a per-session git repository, one tag per turn and one per tool call;
- 🗃️ **prompts, the model catalog and the agent inventory** in a `state.vscdb` SQLite file;
- 📦 **installed skills, plugins and MCP servers** as plain directories;
- 💳 **credit balance lines** in the renderer log it appends at app start;

…yet the app only shows a context meter. There is **no** cross-session breakdown of what was
used, and nothing at all about where the credits went. That gap is what `tcut` fills.

## 📝 What is recorded, and what is not

The high-fidelity plaintext that exists on disk is what this tracker records: sessions with
their project, agent, turn and tool-call counts, the model each session was set to, the full
model catalog with its account and agent group, the installed inventory, topic lines, prompts,
memory paragraphs, and the credit balance samples Trae logs at app start.

Three things it does **not** record, each because the measurement says they are not there:

| Absent | Why |
|---|---|
| 🔢 **token counts** | 11,837 files under `~/.trae-cn` and `~/.config/Trae CN` were walked for quoted token keys (`prompt_tokens`, `rawUsage`, …) and none matched, while the identical walk finds them in CodeBuddy's transcripts. The agent database reads at 8.000 bits/byte with zero readable keywords and its WAL frames are ciphertext; the usage endpoints appear in `main.log` as a URL plus a status code with no response body. Every token position therefore renders `-`. |
| 🧰 **tool names** | A snapshot tag is `toolcall-<messageId>-<toolcallId>` — the id pair and nothing else. `toolcall_events` stores those ids, so the Tools tab is a **count per session**, not a per-tool ranking. A tool name would have to be invented. |
| 📊 **per-request records** | Trae writes no request log at all, so the Usage page aggregates by **session** and says so on its note line rather than rendering a request table with no requests in it. |

The evidence is in [`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md).

## 🏗️ How it works

```text
   ~/.trae-cn/                 tcut                    ~/.local/share/
   ~/.config/Trae CN/                              trae-cn-usage-tracker/
 ┌──────────────────┐        ┌─────────────────────┐        ┌────────────────────────┐
 │ memory/projects/ │        │  tcut-sync.py       │        │  usage.db               │
 │   **/*.jsonl  ───┼─ read ─▶  parse + classify  │  write │  SQLite (sessions ·     │
 │                  │ (only) │  incremental,       ├───────▶│  tools · skills ·       │
 │ ModularData/     │        │  idempotent         │        │  agents · plugins ·     │
 │   ai-agent/      │        └─────────────────────┘        │  mcp · credits)         │
 │   snapshot/**/.git                                       └───────────┬────────────┘
 │ skills/ plugins/ mcps/             ▲                             │
 │ User/**/state.vscdb      ┌─────────┴───────────┐                 │
 │ logs/**/renderer.log     │  tcut-tui.py (TUI)  │◀─── query ────────┘
 └──────────────────┘       │  tcut-stats.py (CLI)│
       untouched            └─────────────────────┘
```

`tcut` is a **passive reader**: it parses the files Trae already writes and builds an index.
It never touches Trae's files, installs no hook, and adds no runtime overhead.

## 📊 The eight tabs

The **Dashboard** opens first: an at-a-glance summary of the important numbers. A shared top
bar above the tabs carries the range selector, and **each tab keeps its own range** — changing
one tab's window never moves another's. The Dashboard, Tools, Agents, Tokens and Usage tabs
default to **7 days**; Skills, Plugins and MCP carry no timestamp at all, so they are all-time
and the selector is hidden there. A window only changes the **counts**, never the list.

| | Tab | What it shows |
|---|-----|---------------|
| 🧭 | **Dashboard** | usage KPIs (sessions, projects, turns, tool calls, prompts, agents, skills, plugins, MCP), the installed-inventory counts, Top 5 projects / agents / models (3P tagged), a per-day activity sparkline, and a `Credits · routes · sync` panel with the balance, the spend lower bound, the estimate's allocated / unallocated parts, and 3P sessions |
| 🧰 | **Tools** | tool calls **per session** — id-derived counts with the session's first and last call. A count, not a per-tool name: see [Credits vs tokens](#-credits-vs-tokens) |
| 🎯 | **Skills** | the installed skill inventory. All-time: Trae records no per-skill invocation |
| 🤖 | **Agents** | installed agents, and how many sessions in the window name one |
| 🧩 | **Plugins** | the installed plugin inventory, with version. All-time |
| 🔌 | **MCP** | the installed MCP server inventory. All-time |
| 🔢 | **Tokens** | **model routes ranked by estimated credits** — model, provider, `Built-in` / `3P`, `credits est.`, share, sessions, last used. The token column stays `-` because Trae writes no token count (third-party routes included) |
| 📊 | **Usage** | summary panels plus one row **per (session, model selection)** — when, session, model, route, credit estimate, project, turns, calls |

<kbd>Enter</kbd> (or a double-click) opens the **drill-down** for a session row on Tools or
Usage, an agent row on Agents, or a model-route row on Tokens. The three inventory tabs have
nothing behind a row, and they say that in a notification rather than opening an empty screen.

Three rules hold across every table, and they exist because the alternative reads as a fact:

- **A window never reports a zero for rows it cannot see.** A windowed count renders `-`
  (`db.window_count`) only when the row has neither a measured `last_ts` nor a derived
  `created_ts`. `0` is reserved for a measured absence.
- **A derived time prints `~`.** 25 of this machine's 49 sessions have no measured timestamp at
  all; the creation second is decoded from the session id (median delta 0.0 s against the 24
  dated sessions), and the panels disclose how many rows are in that state.
- **A total over rows that never carried the field prints `-`, not `0`.** 28 of 49 sessions
  carry neither a decoded project nor a raw project key, so a window can genuinely have no
  project key to count.

A table never shows a half column: each table keeps the longest **prefix** of its columns that
fits and names the dropped ones on the note line above it, so a narrow terminal costs columns,
not legibility. A long cell is capped at `name_cap` and the note prints the number in force.

## 💳 Credits vs tokens

This is the one Trae-specific fact worth understanding before reading the numbers, and it was
measured on this machine rather than assumed:

| Axis | Trae CN reports | Does not report |
|---|---|---|
| 💳 **credits** | a **balance level** sampled at app start in the renderer log | any per-request spend — a sample is a level, never a delta, and a fetch Trae declined is stored with no number at all |
| 🔢 **tokens** | nothing, anywhere on disk (third-party routes included) | — |

The Tokens tab therefore does not list raw balances. It lists a **per-route estimate**: the drop
between two balance samples is the only measured spend, and the indexer splits it across the
sessions created inside that interval by turn count. A session that selected two models splits
its share evenly. Every row is marked `est.`, the parts add up to the drop, and a share no
recorded selection can claim is reported separately as `Unallocated` rather than smeared over a
model. The `share` column is a share of the **allocated** estimate, not of all spend — otherwise
92% would read as "92% of the credits" rather than "92% of what could be placed".

- **The route comes from the id's shape, not a guess.** `...__Model_null` is Trae's own route;
  an id that carries a channel and a trailing id (e.g.
  `solo_agent_3_volcengine-plan_..._2837387906`) is third-party. The `Route` column says
  `Built-in` / `3P`, and `Provider` names the channel only for 3P. The catalog supplies the name;
  it cannot turn a `_null` selection into 3P.
- **`spent ≥` is a lower bound, computed at query time.** It is the drop between a balance
  sample and the one before it. Because a daily grant also lands between samples, the true spend
  over any interval can be higher — which is exactly why the column is named `spent ≥` and never
  read as consumption.
- **A declined fetch is not a `0`.** Two of the twelve samples here are fetches Trae did not
  answer; they are stored as no-number and left out of the series rather than turning a missing
  balance into a drop.
- **The token column cannot be filled.** Quoted token keys (`prompt_tokens`, `rawUsage`, …) were
  searched across `~/.trae-cn` and `~/.config/Trae CN` with zero hits; the agent database is
  encrypted and the usage endpoints appear in the log as a URL plus a status code. Third-party
  routes run through the same host and write no token count either.
- **The tool-call ids are counts, not names.** `toolcall-<messageId>-<toolcallId>` is the whole
  tag. The Tools tab aggregates them per session, which is the most the tag supports.

The integers are daily grants; the single fractional balance (154.0244, out of 1400…1800) is
the only sample that proves consumption happened, and a grant landed inside that interval too.

## 📋 Requirements

| | |
|---|---|
| 🐧 OS | Linux — developed and verified on Ubuntu; other distributions **unverified** |
| 🐾 Trae CN | the desktop app; the schema is verified against **the files on this machine**, not against a version number. International Trae is out of scope — see [`docs/maintenance/compatibility.md`](docs/maintenance/compatibility.md) |
| 🐍 Python | 3.11 — 3.14, both ends measured green (CI runs them). Headless commands need only the stdlib; the TUI needs `textual` |
| 🖥️ `textual` | only for the interactive TUI (installed by `install.sh`) |

## 🚀 Install

```bash
cd trae-cn-usage-tracker
./install.sh          # creates .venv with textual, links ~/.local/bin/tcut
tcut sync             # build the index from your existing Trae CN files
tcut                  # launch the TUI
```

Prefer no venv? The headless reports work with plain `python3`:

```bash
python3 scripts/tcut-sync.py
python3 scripts/tcut-stats.py stats
```

### 🔄 Optional: keep the index fresh without opening the TUI

Two user units ship in [`systemd/`](systemd). Installing them runs
`tcut sync --quiet` once a day:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/tcut-sync.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tcut-sync.timer
```

`Persistent=true` catches up a run missed while the machine was off, the wake-up is
jittered by up to 15 minutes, and the service runs at `Nice=10`.

## 🧭 Usage

```bash
tcut                     # 🖥️  interactive TUI (eight tabs)
tcut sync                # 🔄  incremental index of new Trae data
tcut sync --full         # ♻️  rebuild the database from scratch
tcut stats               # 📊  overview of all categories
tcut sessions            # 📋  session table, with each session's selected model
tcut recent              # 🕒  most recent sessions, counts only
tcut show SESSION_ID     # 🔍  session detail
tcut projects            # 📁  project counts
tcut prompts             # 💬  local prompt history
tcut agents              # 🤖  agents and session counts
tcut credits             # 💳  credit balance samples and the spend lower bound
tcut models              # 🔢  model catalog: account, group, rate, context window
tcut inventory           # 📦  every installed row in one table
tcut skills|plugins|mcp  # 🎯 installed inventory
tcut memory              # 🧠  stored memory paragraphs
tcut export              # 💾  dump every table as JSON
tcut health              # 🩺  database + data-source check
tcut backup              # 💾  snapshot before a risky step
tcut restore             # ⏪  list snapshots; `tcut restore NAME` rolls one back
tcut format              # 🧾  the Trae CN fields and paths this tool depends on
```

The Tools, Tokens and Usage surfaces are TUI-only: their aggregates are per-window summaries,
which is what the top bar is for, and none of them has a headless report.

| Variable | Default | Purpose |
|---|---|---|
| `TCUT_DB` | `~/.local/share/trae-cn-usage-tracker/usage.db` | database location |
| `TCUT_TRAE_CN_HOME` | `~/.trae-cn` | source directory (memory, snapshots) |
| `TCUT_TRAE_CN_DATA` | `~/.config/Trae CN` | source directory (agent database, inventory, logs) |

Every command accepts `--db` before or after the subcommand.

## ⚙️ Configuration

Every knob has the value the app already shipped with, and the file is optional:
`tcut` behaves exactly as documented until you add one.

Settings file: `~/.config/tcut/config.toml` — or point `TCUT_CONFIG` somewhere else.
Environment variables take precedence over the file.

| Key | Default | Environment | What it caps |
| --- | ---: | --- | --- |
| `top_n` | `5` | `TCUT_TOP_N` | rows in the Dashboard's Top projects / Top agents |
| `log_limit` | `100` | `TCUT_LOG_LIMIT` | rows on the Usage page's session log, and on `tcut prompts` |
| `detail_limit` | `200` | `TCUT_DETAIL_LIMIT` | rows on a history screen |
| `name_cap` | `28` | `TCUT_NAME_CAP` | widest cell a table renders before it cuts the value |
| `refresh_secs` | `5` | `TCUT_REFRESH_SECS` | TUI redraw timer |
| `sync_secs` | `30` | `TCUT_SYNC_SECS` | TUI auto-sync timer |
| `store_content` | `true` | `TCUT_STORE_CONTENT` | whether prose is stored at all |

- **A broken file stops the TUI** with the path and the reason rather than quietly starting on
  defaults. `tcut health` prints the same verdict, including which file it read.
- **Unknown keys are refused**, and values are type- and range-checked (`top_n = 0` is a blank
  panel, not a preference).
- Parsed by the standard library's `tomllib`, so this adds **no dependency** and no network
  path. Nothing ever writes this file, and no setting is stored in the database.

## 🔒 Storage and privacy

The index is local SQLite. Nothing is uploaded and the production scripts import no network or
process-spawning module. Trae's own directories are read-only inputs.

This project intentionally differs from the CodeBuddy tracker's metadata-only policy:
`store_content = true` by default stores session `intent`/`outcome`, actions, learned items,
topic summaries, prompt history, and memory paragraphs **in the local SQLite only**. Set
`store_content = false` to keep metadata while removing all of that prose; the next sync also
purges prose already present in the database. Both directions are checked, not merely intended —
see [`AGENTS.md`](AGENTS.md#invariants-and-how-to-check-them).

Model data is metadata: the catalog (account, agent group, name, provider, price multiplier,
context window) and each session's selected model are stored regardless of `store_content`,
because they are not prose. A custom-provider catalog entry also carries `ak`, `sk`,
`base_url` and `custom_config` — the indexer reads a whitelist and those fields never reach the
database.

## 🧪 Testing

```bash
python3 -m unittest discover -s scripts/tests     # Ran 261 tests ... OK
```

The suites are plain `unittest` (`pytest` discovers them too). Two need `textual` installed —
`test_tui.py`, and `test_config.py`, whose wiring cases load the TUI module to prove every
setting reaches a renderer. Each suite builds its own throwaway database **and** its own
throwaway Trae tree in a temp directory: your real `usage.db` and your real `~/.trae-cn` are
never opened, and no code path in this repository reaches the network (`test_privacy.py` holds
the import allowlist that keeps it that way).

| Suite | Tests | Covers |
|---|---:|---|
| `test_sync.py` | 55 | the source readers (session memory JSONL, topic lines, memory prose, snapshot git tags, the agent `state.vscdb`, the inventory trees, the renderer log), incremental vs `--full` re-sync, the `models` composite key, credential-sentinel proof, unparsed accounting |
| `test_tui.py` | 33 | tab wiring and report shapes through Textual's own `run_test` harness, per-tab ranges, the column plan, empty states, the responsive layout, the status line as it is actually rendered, and the Tokens route table's `3P` / token / estimate cells with their drill-down |
| `test_stats.py` | 38 | the headless CLI end to end: a real `main([...])` per subcommand, `--db` before and after, `export` / `inventory` / `show` / `health`, `backup`→`restore`, the generated `format` surface, and the empty-state notices |
| `test_config.py` | 21 | the settings layer: defaults against the TUI's own constants, file, environment precedence and bounds, a broken file that names its path, and every knob a renderer actually reads |
| `test_maintenance_docs.py` | 20 | the generated format doc cannot drift from the code, every maintenance asset is reachable from the router, and no document may state a CI version the workflow does not run |
| `test_usage.py` | 19 | the per-session tool-call aggregation and its window, the Usage summary panels' totals, the credit series' `spent ≥` lower bound, and the v5 decode: built-in vs 3P, per-route credit allocation, and one Usage row per model selection |
| `test_snapshots.py` | 14 | automatic snapshots before destructive steps, listing, restore, retention |
| `test_privacy.py` | 11 | the import allowlist plus the calls that bypass it (`__import__` / `eval` / `import_module`), a fingerprint proving Trae's own tree is untouched, the `store_content` sentinel scan across every text column, and the model-credential scan |
| `test_format_registry.py` | 10 | the Trae CN format registry and the parser agree, both directions |
| `test_hermetic.py` | 13 | a runtime tripwire: the suite never opens the real `usage.db` or reads the real Trae host dirs, in-process or through a child |
| `test_record_coverage.py` | 6 | every covered commit is recorded in `CHANGELOG.md` |
| `test_dispatcher.py` | 6 | `bin/tcut`: subcommand routing, venv resolution, help without a resolvable install |
| `test_readme_bilingual.py` | 4 | the two READMEs stay one document in two languages, and every table-of-contents link has a heading to land on |
| `test_readme_counts.py` | 2 | every suite total in either README equals what `unittest discover` counts, and both pages document every setting the loader knows |
| `test_conventions.py` | 9 | the dimension-A root layer is present at the root, AGENTS.md names its dimension in one line instead of quoting the standard's body, and no runtime state the ignore list covers is tracked |

`test_readme_counts.py` is what keeps the two numbers above honest: a total that drifts fails the
suite. The suites are read off the syntax trees, so a suite added without a row here is a count
that will be wrong rather than a table that looks stale.

## 📁 Repository layout

| Path | What it is |
|---|---|
| `bin/tcut` | bash entry point. Bash on purpose: it must still print a useful error when the TUI venv is missing or broken, so it cannot depend on Python. Prefers `./.venv/bin/python`, falls back to `python3` |
| `install.sh` | creates the venv (`uv` when available) and symlinks `~/.local/bin/tcut` |
| `scripts/tcut_db.py` | SQLite schema and the query helpers every entry point shares |
| `scripts/tcut-sync.py` | the source readers and the incremental indexer (`--full`, `--quiet`) |
| `scripts/tcut-stats.py` | headless reports: `stats` · `sessions` · `recent` · `show` · `projects` · `prompts` · `agents` · `models` · `credits` · `skills` · `plugins` · `mcp` · `memory` · `inventory` · `export` · `health` · `backup` · `restore` · `format` |
| `scripts/tcut-tui.py` | the eight-tab Textual UI |
| `scripts/tests/` | the tests above |
| `docs/maintenance/` | what to re-check when Trae changes: the generated format-dependency surface, the compatibility matrix, and the measurement baseline with the commands that produced it |
| `systemd/` | optional daily sync service + timer |
| `requirements.txt` | `textual>=8.2,<9` — TUI only; everything else is stdlib |

Both paths are overridable for a sandboxed install: `TCUT_SCRIPTS` and `TCUT_VENV` for the
launcher, `TCUT_DB`, `TCUT_TRAE_CN_HOME` and `TCUT_TRAE_CN_DATA` for the data.

## 📚 Maintenance notes

See [`docs/maintenance/`](docs/maintenance/README.md). The format note records what is observed,
what is encrypted, and what the indexer intentionally does not claim; the compatibility matrix
states what is supported; the measurement note carries the baseline and the commands that
produced it. The parser's format surface is generated — `tcut format` prints it,
`tcut format --write` refreshes the block, and `test_maintenance_docs.py` fails if the two ever
disagree.

## ⚠️ Limitations & roadmap

- 🔢 **No tokens, ever, from this source.** Not a gap in the reader: see [Credits vs
  tokens](#-credits-vs-tokens). The Tokens tab keeps a token column for the `cbut`-shaped layout
  and leaves it blank on purpose; the note above the table says why, and what the
  credit estimate beside it does and does not measure.
- 🧰 **Tools cannot be ranked by name.** Only the per-session count is real; a per-tool table
  would require reading the encrypted agent database.
- 🎯 **Skills, Plugins and MCP are inventory, not usage.** Trae records no per-entity
  invocation, so those three tabs show what is installed and the Agents tab is the only one that
  can count. A sparse panel is honest; a fabricated ranking is not.
- 📊 **The Usage page is per session, not per request.** There is no request log to read.
- 🔌 **Session views have no TUI tab.** `tcut sessions`, `tcut projects`, `tcut prompts` and
  `tcut memory` still print them; they were dropped from the TUI to keep the tab set aligned
  with `cbut`'s.
- 🔄 Sync is manual (or via the optional systemd timer); there is no live hook.

## 🧹 Uninstall

`tcut` touches exactly three places outside the repository, and removing them leaves
nothing behind:

```bash
systemctl --user disable --now tcut-sync.timer 2>/dev/null          # only if installed
rm -f ~/.config/systemd/user/tcut-sync.service ~/.config/systemd/user/tcut-sync.timer
systemctl --user daemon-reload
rm -f ~/.local/bin/tcut                                            # the symlink install.sh made
rm -rf ~/.local/share/trae-cn-usage-tracker                        # the SQLite index
```

Deleting the repository directory (with its `.venv`) finishes it. Trae's own files were only
ever read, so there is nothing to restore there. 🗑️

## 🙏 Attribution

Built in the spirit of
[`codebuddy-usage-tracker`](https://github.com/SHADE-glitch/codebuddy-usage-tracker), which
tracks the same categories for CodeBuddy Code and whose eight-tab layout this one mirrors. The
architecture is the same — read what the host already writes — but the schema is Trae CN's own:
credits instead of provider-reported tokens, tool calls identified by a git tag rather than a
name, session-level rather than request-level usage, and stored prose behind an explicit
`store_content` switch.

## 📄 License

MIT — see [LICENSE](LICENSE). © 2026 SHADE-glitch
