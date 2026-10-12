<p align="right"><a href="README.md"><b>English</b></a> | <a href="README.zh-CN.md">简体中文</a></p>

# 🐾 Trae CN Usage Tracker (`tcut`)

![Trae CN](https://img.shields.io/badge/Trae%20CN-reads%20local%20files-blue?logo=robotframework&logoColor=white)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-ff69b4?logo=terminal&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey?logo=linux&logoColor=black)
[![Repository](https://img.shields.io/badge/repository-GitHub-black?logo=github)](https://github.com/SHADE-glitch/trae-cn-usage-tracker)

A passive, local usage tracker for **Trae CN**. It reads the plaintext files Trae leaves under
`~/.trae-cn` and `~/.config/Trae CN`, indexes them into one SQLite database, and presents the result
through a Textual TUI or a dependency-free CLI.

## What is recorded, and what is not

Trae CN keeps its per-tool-call agent store encrypted, so this tracker records the highest-fidelity
plaintext that exists: sessions, summaries, topic lines, prompts, memory paragraphs, snapshot
turn/tool-call IDs, the installed inventory, the model catalog with its account and agent group, the
model each session was set to, and the credit balance samples Trae logs at app start.

Token counts are **not** on this machine, and that is a measurement rather than a guess: 11,837 files
under `~/.trae-cn` and `~/.config/Trae CN` were walked for quoted token keys (`prompt_tokens`,
`rawUsage`, …) and none matched, while the identical walk finds them in CodeBuddy's transcripts. The
agent database is at 8.000 bits/byte with zero readable keywords, its WAL frames are ciphertext, and
the usage endpoints appear in `main.log` as URL plus status code with no response body. Every token
position therefore renders `-`; tool **names** are not invented either. The evidence is in
[`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md).

## Install

```sh
./install.sh
```

This creates a local Python environment for the TUI and installs `tcut` at `~/.local/bin/tcut`. The
headless commands use only the Python 3.11+ standard library; the TUI requires `textual>=8.2,<9`.

## Commands

```sh
tcut                         # open the five-tab TUI
tcut sync                    # incremental index
tcut sync --full             # snapshot, then rebuild
tcut stats                   # overview
tcut sessions                # session table, with each session's selected model
tcut recent                  # most recent sessions, counts only
tcut show SESSION_ID         # session detail
tcut projects                # project counts
tcut prompts                 # local prompt history
tcut agents                  # agents and session counts
tcut credits                 # credit balance samples and the spend lower bound
tcut models                  # model catalog: account, group, rate, context window
tcut inventory               # every installed row in one table
tcut skills | plugins | mcp # installed inventory
tcut memory                  # stored memory paragraphs
tcut export                  # JSON export
tcut health                  # paths, settings, schema, unparsed records
tcut backup                  # create a managed SQLite snapshot
tcut restore                 # list snapshots; add a name to restore
tcut format                  # print the Trae CN format-dependency surface
tcut format --write          # refresh the generated block in docs/maintenance/
```

```sh
# Every command accepts --db before or after the subcommand.
tcut --db /tmp/tcut.db sync
tcut stats --db /tmp/tcut.db
```

The default database is `~/.local/share/trae-cn-usage-tracker/usage.db`.

## TUI tabs

Dashboard · Skills · Agents · Plugins · MCP

The tab set is cbut's, minus **Tools**, **Tokens** and **Usage**. Those three would read data Trae CN
does not write in plaintext: snapshot git tags identify a tool call by id and never name the tool, the
agent database is encrypted so no token count exists on disk, and there is no per-request record at
all (measured — see `tcut format`). Nothing is shipped in their place. An empty token panel reads as
"0 tokens" or as a broken widget, and neither is true. The tabs the two apps do share are invocation
counters in cbut and installed inventory here, because Trae records no per-skill, per-plugin or
per-MCP-server use.

The session-level views cbut has no room for — Sessions, Projects, Prompts, Memory — were dropped
from the TUI on that same rule. Their rows are still indexed, and still printed: `tcut sessions`,
`tcut projects`, `tcut prompts`, `tcut memory`. A session's detail (intent, actions, learned items,
topics, the model it selected) is reached by opening an agent row. Dashboard and Agents each keep
their own time range; Skills, Plugins and MCP carry no timestamp, so they are all-time and hide the
range selector.

25 of this machine's 49 sessions have no measured timestamp anywhere in Trae's plaintext, but a
session id opens with its own creation second, so the index stores that as `created_ts` and a range
can still place the row — a time that came from the id prints with a leading `~`, because a
derivation must not read as a measurement, and the line under the Dashboard panels says how many rows
are in that state. A count reads `-` only for a session with no time anywhere (none on this machine),
while a genuine `0` still means the entity owns no sessions in the range. The Dashboard's **Top
projects** and **Top agents** keep the `-` rows instead of dropping them, and a blank panel names the
blank it is showing: `no agents installed` (nothing indexed), `no session in this range names an
installed agent` (the sessions are there, the label is not — 24 of this machine's 49 carry no agent
at all, and every session in the current week is one of them), or `none dated in 7 days` (the range
placed nothing). Widening the picker only helps with the last one. The credit balance Trae does log
lives in the Dashboard's `Credits · sync` panel.

## Storage and privacy

The index is local SQLite. Nothing is uploaded and the production scripts import no network or
process-spawning module. Trae's own directories are read-only inputs.

This project intentionally differs from the CodeBuddy tracker's metadata-only policy:
`store_content = true` by default stores session `intent`/`outcome`, actions, learned items, topic
summaries, prompt history, and memory paragraphs **in the local SQLite only**. Set
`store_content = false` to keep metadata while removing all of that prose; the next sync also purges
prose already present in the database.

Model data is metadata: the catalog (account, agent group, name, provider, price multiplier, context
window) and each session's selected model are stored regardless of `store_content`, because they are
not prose. A custom-provider catalog entry also carries `ak`, `sk`, `base_url` and `custom_config` —
the indexer reads a whitelist and those fields never reach the database.

## Settings

Settings file: `~/.config/tcut/config.toml` (override with `TCUT_CONFIG`). Environment variables take
precedence over the file.

| Key | Default | Environment |
| --- | ---: | --- |
| `top_n` | `5` | `TCUT_TOP_N` |
| `log_limit` | `100` | `TCUT_LOG_LIMIT` |
| `detail_limit` | `200` | `TCUT_DETAIL_LIMIT` |
| `name_cap` | `28` | `TCUT_NAME_CAP` |
| `refresh_secs` | `5` | `TCUT_REFRESH_SECS` |
| `sync_secs` | `30` | `TCUT_SYNC_SECS` |
| `store_content` | `true` | `TCUT_STORE_CONTENT` |

`tcut health` reports the values actually in effect.

## Tests

The suite uses stdlib `unittest` and Textual's `run_test()` harness. It builds throwaway Trae-shaped
fixtures, never opens the real usage database, and checks import/privacy guards, incremental parsing,
snapshots, CLI output, TUI interactions, and content-storage boundaries.

Latest local run: `Ran 215 tests ... OK`.

## Maintenance notes

See [`docs/maintenance/`](docs/maintenance/README.md): the format note records what is observed, what
is encrypted, and what the indexer intentionally does not claim; the compatibility matrix states what
is supported; the measurement note carries the baseline. The parser's format surface is generated —
`tcut format` prints it, `tcut format --write` refreshes the block.

## License

MIT. Copyright (c) 2026 SHADE-glitch.
