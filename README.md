# Trae CN Usage Tracker

A passive, local usage tracker for **Trae CN**. It reads the plaintext files Trae leaves under `~/.trae-cn` and `~/.config/Trae CN`, indexes them into one SQLite database, and presents the result through a Textual TUI or a dependency-free CLI.

面向 **Trae CN** 的被动、本地用量追踪器。它读取 Trae 写入 `~/.trae-cn` 与 `~/.config/Trae CN` 的明文文件，写入一个 SQLite 数据库，并通过 Textual TUI 或无第三方依赖的 CLI 展示结果。

## What is recorded, and what is not

Trae CN keeps its per-tool-call agent store encrypted, so this tracker records the
highest-fidelity plaintext that exists: sessions, summaries, topic lines, prompts, memory
paragraphs, snapshot turn/tool-call IDs, the installed inventory, **the model catalog with
its account and agent group, the model each session was set to, and the **credit balance
samples Trae logs at app start**.

Token counts are **not** on this machine, and that is a measurement rather than a guess:
11,837 files under `~/.trae-cn` and `~/.config/Trae CN` were walked for quoted token keys
(`prompt_tokens`, `rawUsage`, …) and none matched, while the identical walk finds them in
CodeBuddy's transcripts. The agent database is at 8.000 bits/byte with zero readable
keywords, its WAL frames are ciphertext, and the usage endpoints appear in `main.log` as
URL plus status code with no response body. Every token position therefore renders `-`;
tool **names** are not invented either. The evidence is in
[`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md).

Trae CN 的 agent 存储是加密的，所以本工具记录盘上真实存在最高保真度的东西：会话、摘要、主题行、提示词、记忆段落、快照里的 turn/tool-call ID、已安装清单，**以及带账号和分组的模型目录、每个会话选中的模型**。

token 数在这台机器上不存在，这是实测结论而不是推测：`~/.trae-cn` 与 `~/.config/Trae CN` 下 11,837 个文件按带引号的 token 键搜过，零命中，而同样的搜法在 CodeBuddy 转录里能命中；agent 库首 1 MB 熵 8.000 bit/byte、零关键字，WAL 帧也是密文，日志里的 usage 接口只有 URL 和状态码、没有响应体。所以所有 token 位置显示 `-`，工具**名称**同样不会被臆造。

## Install

```sh
./install.sh
```

This creates a local Python environment for the TUI and installs `tcut` at `~/.local/bin/tcut`. The headless commands use only the Python 3.11+ standard library; the TUI requires `textual>=8.2,<9`.

该脚本会创建本地 TUI Python 环境，并把 `tcut` 安装到 `~/.local/bin/tcut`。无头命令只需要 Python 3.11+ 标准库；TUI 需要 `textual>=8.2,<9`。

## Commands

```sh
tcut                         # open the ten-tab TUI
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
tcut format                  # show the Trae format notes
```

```sh
# Every command accepts --db before or after the subcommand.
tcut --db /tmp/tcut.db sync
tcut stats --db /tmp/tcut.db
```

所有命令都支持将 `--db` 放在子命令前或后。默认数据库是 `~/.local/share/trae-cn-usage-tracker/usage.db`。

## TUI tabs

Dashboard · Sessions · Projects · Prompts · Agents · Skills · Plugins · MCP · Memory · Usage

The Usage tab is **not** cbut's Usage tab. Token, cost, request-count and cache panels do not exist here, because Trae CN never writes them to disk (measured — see `tcut format`). The tab holds the one consumption-derived number Trae does write: its credit balance, sampled once per app start, with the spend column labelled `spent ≥` because a fall between two samples is only a lower bound. Leaving the panels out rather than shipping them empty is deliberate: an empty token panel reads as "0 tokens" or as a broken widget, and neither is true.

Dashboard · Sessions · Projects · Prompts · Agents · Skills · Plugins · MCP · Memory · Usage（共十个 tab）。Dashboard、Sessions、Projects、Agents、Usage 各自保留独立的时间范围；Prompts、Skills、Plugins、MCP、Memory 没有可用时间戳，因此为 all-time。

Usage tab 不等于 cbut 的 Usage tab：token、成本、请求数、缓存这些面板**不存在**，因为 Trae CN 从不把它们写到盘上（已实测，见 `tcut format`）。这一页装的是 Trae 真的写了的 credit 余额（每次启动一条采样），消耗列标成 `spend ≥`，因为两次采样之间的下降只是下界。

## Storage and privacy

The index is local SQLite. Nothing is uploaded and the production scripts import no network or process-spawning module. Trae's own directories are read-only inputs.

This project intentionally differs from the CodeBuddy tracker's metadata-only policy: `store_content = true` by default stores session `intent`/`outcome`, actions, learned items, topic summaries, prompt history, and memory paragraphs **in the local SQLite only**. Set `store_content = false` to keep metadata while removing all of that prose; the next sync also purges prose already present in the database.

Model data is metadata: the catalog (account, agent group, name, provider, price
multiplier, context window) and each session's selected model are stored regardless of
`store_content`, because they are not prose. A custom-provider catalog entry also carries
`ak`, `sk`, `base_url` and `custom_config` — the indexer reads a whitelist and those
fields never reach the database.

索引只写本地 SQLite，不上传任何内容；生产脚本不导入网络或进程启动模块，Trae 自己的目录只作为只读输入。

本项目有意不同于 CodeBuddy tracker 的“仅元数据”策略：默认 `store_content = true`，把会话 `intent`/`outcome`、actions、learned、主题摘要、prompt history 和 memory 段落**仅存入本地 SQLite**。设置 `store_content = false` 后保留元数据并删除全部这些 prose；下一次 sync 还会清理数据库中已经存在的 prose。

模型数据属于元数据：模型目录（账号、分组、名字、provider、计价倍率、上下文窗口）和每个会话选中的模型不受 `store_content` 影响，因为它们不是散文。自定义端点的目录条目里同时带着 `ak`/`sk`/`base_url`/`custom_config`，解析器按白名单取字段，这些一个都不会进库。

## Settings

Settings file: `~/.config/tcut/config.toml` (override with `TCUT_CONFIG`). Environment variables take precedence over the file.

| Key | Default | Environment |
| --- | ---: | --- |
| `top_n` | `5` | `TCUT_TOP_N` |
| `log_limit` | `100` | `TCUT_LOG_LIMIT` |
| `detail_limit` | `200` | `TCUT_DETAIL_LIMIT` |
| `name_cap` | `28` | `TCUT_NAME_CAP` |
| `refresh_secs` | `5` | `TCUT_REFRESH_SECS` |
| `sync_secs` | `30` | `TCUT_SYNC_SECS` |
| `store_content` | `true` | `TCUT_STORE_CONTENT` |

配置文件是 `~/.config/tcut/config.toml`（可用 `TCUT_CONFIG` 改路径），环境变量优先于配置文件。上表是完整设置面；`tcut health` 会报告实际生效的值。

## Tests

The suite uses stdlib `unittest` and Textual's `run_test()` harness. It builds throwaway Trae-shaped fixtures, never opens the real usage database, and checks import/privacy guards, incremental parsing, snapshots, CLI output, TUI interactions, and content-storage boundaries.

当前测试套件使用标准库 `unittest` 与 Textual 的 `run_test()`。测试构造临时 Trae fixture，从不打开真实 usage database，并覆盖 import/privacy 守卫、增量解析、快照、CLI 输出、TUI 交互和内容存储边界。

Latest local run: `Ran 171 tests ... OK`.

最近一次本地运行：`Ran 171 tests ... OK`。

## Maintenance notes

See [`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md), [`compatibility.md`](docs/maintenance/compatibility.md), and [`measurements.md`](docs/maintenance/measurements.md). The format note records what is observed, what is encrypted, and what the indexer intentionally does not claim.

维护说明见上述三个文档；format 文档区分已观察事实、加密数据，以及索引器有意不声称的内容。

## License

MIT. Copyright (c) 2026 SHADE-glitch.

MIT。版权所有 (c) 2026 SHADE-glitch。
