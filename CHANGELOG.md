# Changelog

## 0.4.0 — 2026-10-12

- The TUI now mirrors cbut's shape: a tenth **Usage** tab, a **Top models** panel and a
  **Credits · sync** panel on the Dashboard, and `models`/`credits` on the status bar.
- The Usage tab deliberately does not copy cbut's contents. Token, cost, request-count and
  cache panels are **not implemented** — Trae CN writes none of them — and the tab says so in
  one line above the table rather than shipping empty panels that would read as zeros.
- Fixed dead drill-downs: seven of the eight tables stamped a `key_kind` on their rows while
  the app understood only `session`, so Enter did nothing on Projects, Agents, Skills, Plugins,
  MCP, Prompts and Memory. A new `EntityScreen` lists the sessions behind a project, agent or
  model (and a session row inside it still opens its detail); the kinds Trae cannot support
  now say why instead of ignoring the key press.
- Fixed a panel that lied by omission: a sync that indexed nothing took the light-refresh path
  and left "Session sync not yet" on screen after a completed sync. The two sync lines are now
  redrawn from app state on every completion and every toggle.
- Ported cbut's two enumeration guards. The table-registry guard was written with a pattern that
  matched **zero** tables and passed on the empty set; it now checks both directions (a table the
  plan does not know, and a registry entry nothing mounts). The cap guard fails on any pushed
  wide screen that ignores the configured `name_cap`.
- Moved the credit formatting and pluralisation rules into the shared data layer, after a
  CLI-local copy shipped "2 fetchs skipped" on real data.
- The suite grew to **171** tests (134 at the start of this round).
- Known gap against cbut: tcut does not index on mount, so a freshly opened TUI waits for the
  30 s auto-sync tick or `r`. Adding it means pinning every TUI test's Trae fixture roots first —
  cbut's own history shows why (a dispatcher test once ran a real `--full` against the live DB).

## 0.4.0 — 2026-10-12（中文）

- TUI 对齐 cbut 形状：多出第十个 **Usage** tab、Dashboard 上多出 **Top models** 与 **Credits · sync** 两个面板，状态栏加上 models/credits。
- Usage tab 有意不抄 cbut 的内容：token、成本、请求数、缓存面板**不做**（Trae CN 一个都不写），改为在表格上方一句话点名缺席，而不是留空面板让人读成 0。
- 修好失效的下钻：八个表里有七个给行打了 `key_kind`，而 app 只认 `session`，于是 Projects、Agents、Skills、Plugins、MCP、Prompts、Memory 上按 Enter 毫无反应。新增 `EntityScreen` 列出某个项目/agent/模型下的会话（其中的会话行仍可再开会话详情）；Trae 支撑不了的类型改为明确说原因，不再吞掉按键。
- 修好一处"漏报"型假象：一次没索引到新数据的 sync 会走轻量刷新路径，导致 sync 完成后面板仍写着 "Session sync not yet"。现在两条 sync 行在任何一次完成或开关切换时都按 app 状态重绘。
- 移植 cbut 的两条枚举守卡。表格注册卡的旧写法匹配到**零个**表、靠空集合通过；现在双向检查（计划不知道的表、以及注册了却没人挂载的 id）。上限卡则会让任何忽略配置 `name_cap` 的压入式宽表屏失败。
- 把 credits 的数字格式与复数规则收进共享数据层：CLI 本地那份副本在真实数据上写出了 "2 fetchs skipped"。
- 测试套件增至 **171 个**（本轮起点 134 个）。
- 对 cbut 仍知缺一处：tcut 不在挂载时索引，新开的 TUI 要等 30 秒自动同步或按 `r`。补它必须先把每个 TUI 测试的 Trae fixture 根钉住——cbut 自己的历史就是原因（曾有分发器测试对真库跑过真 `--full`）。

## 0.3.0 — 2026-10-12

- Added the credit balance source (schema v3): `credit_events` stores the `[ICubeUsageService]`
  balance lines Trae writes to `logs/<session>/window*/renderer.log` and `main.log`, one row per
  sample with its timestamp and generation, read through a byte-offset cursor.
- Added `tcut credits`: the balance series, the newest balance, and a spend figure labelled
  `spent >=` because a fall between two samples is only a **lower bound** — grants land between
  them. The bound is derived at query time and never stored as a measurement.
- A balance sample whose fetch was declined is kept as `kind='skipped'` so an empty panel can be
  told apart from a declined fetch, and it stays out of the series instead of becoming a `0`.
- Only the four fields are stored; the log line around them is Trae's prose, proved by scanning
  every value of every table for a sentinel planted in it.
- Added a sweep that runs **every** headless command and requires exit zero plus non-empty output
  — the class of check that `format` had been passing without.
- Real-footprint baseline: 10 balance samples plus 2 declined fetches, ≥1700 credits spent across
  the series; `unparsed=0`.
- The suite grew to 162 tests.

## 0.3.0 — 2026-10-12（中文）

- 新增 credits 余额来源（schema v3）：`credit_events` 保存 Trae 写在 `logs/<session>/window*/renderer.log`
  与 `main.log` 的 `[ICubeUsageService]` 余额行，一条采样一行（时间戳与 generation），按字节偏移增量读取。
- 新增 `tcut credits`：余额序列、最新余额，以及一个标成 `spent >=` 的消耗值——两次采样之间的下降只是**下界**，
  中间还有发放。该下界在查询时算出，绝不作为测量结果入库。
- 取数被拒绝的采样存为 `kind='skipped'`，让"面板空"与"取数被拒"可区分，且不会变成序列里的 `0`。
- 只存那四个字段；周围的日志正文是 Trae 的散文，用扫描全库每个值来证明。
- 新增一条会跑**每个**无头命令的巡检，要求退出码 0 且输出非空——`format` 当初正是缺这类检查才一路绿着失败。
- 真实 footprint 基线：10 条余额采样 + 2 条被拒取数，全序列至少 1700 credits，`unparsed=0`。
- 测试套件增至 162 个。

## 0.2.0 — 2026-10-12

- Renamed every internal identifier to the `trae-cn` scope: the data directory is `~/.local/share/trae-cn-usage-tracker/`, `pyproject` is `trae-cn-usage-tracker`, the source locations are `TCUT_TRAE_CN_HOME` / `TCUT_TRAE_CN_DATA` (`TRAE_CN_HOME` / `TRAE_CN_DATA`), and the format note is `docs/maintenance/trae-cn-format.md`. Trae's own on-disk names (`.trae-cn`, `Trae CN`, `.trae-plugin`) are untouched, because they are not ours to rename.
- Added the model axis (schema v2): `models` is now keyed by (account, group_name, name) and carries provider, model type, fee level, consumption rate, context window and prompt limit; a new `session_models` table records the model selected for each session, one row per agent label.
- Fixed a silent data loss: keyed on name alone, `models` held 42 of the 284 catalog entries in a real footprint and the sync still reported `unparsed=0`. The v1→v2 migration rebuilds the table and resets only the `state.vscdb` cursors.
- Added the `model` column to `tcut sessions`, `tcut show` and the TUI Sessions tab and detail screen; `tcut models` now lists account, group, rate and context window.
- Recorded, with measurements, that token counts are not recoverable from disk — the agent store is encrypted (8.000 bits/byte, zero keywords, encrypted WAL frames), the usage endpoints log only URL and status, and 11,837 walked files contain no token-bearing record. Every token position renders `-`.
- `tcut format` no longer requires a database, so it works before the first `tcut sync`; its guard used to accept any exit code and could not fail.
- Credential fields in a catalog entry (`ak`, `sk`, `base_url`, `custom_config`) are outside the read whitelist, asserted by scanning every value of every table.
- The suite grew from 134 to 149 tests.

## 0.2.0 — 2026-10-12（中文）

- 把所有内部标识统一到 `trae-cn` 范围：数据目录 `~/.local/share/trae-cn-usage-tracker/`、`pyproject` 名、来源环境变量 `TCUT_TRAE_CN_HOME` / `TCUT_TRAE_CN_DATA`（常量 `TRAE_CN_HOME` / `TRAE_CN_DATA`）、格式文档改名 `trae-cn-format.md`。Trae 自己盘上的名字（`.trae-cn`、`Trae CN`、`.trae-plugin`）保持不变，因为那不是我方能改的东西。
- 新增模型轴（schema v2）：`models` 主键改为（账号、分组、名字），并保存 provider、模型类型、计价档位、消费倍率、上下文窗口与 prompt 上限；新表 `session_models` 按 agent 标签记录每个会话选中的模型。
- 修掉一处静默丢数据：只按名字做主键时，真实 footprint 的 284 条目录只剩 42 条，而 sync 仍报 `unparsed=0`。v1→v2 迁移重建该表，且只重置 `state.vscdb` 的游标。
- `tcut sessions`、`tcut show` 与 TUI 的 Sessions tab、会话详情页都加上 model 列；`tcut models` 现在列出账号、分组、倍率与上下文窗口。
- 用实测记录下 token 数在盘上不可恢复：agent 库加密（熵 8.000 bit/byte、零关键字、WAL 帧同为密文），usage 接口只留 URL 与状态码，走查 11,837 个文件无一含 token。所有 token 位置显示 `-`。
- `tcut format` 不再需要数据库，首次 `tcut sync` 之前就能用；它原先的守卫接受任意退出码，等于不可能失败。
- 目录条目里的凭据字段（`ak`、`sk`、`base_url`、`custom_config`）在读取白名单之外，用扫描全库所有值来断言。
- 测试套件由 134 增至 149。

## 0.1.0 — 2026-10-12

- Added the standalone `tcut` tracker for Trae CN.
- Added incremental indexing for session memory, topics, memory documents, snapshot git tags, `state.vscdb`, skills, plugins, and MCP inventory.
- Added the nine-tab Textual TUI and stdlib headless reports.
- Added local SQLite snapshots, restore, health reporting, and configuration validation.
- Documented the deliberate local-content-storage deviation and the encrypted agent database boundary.
- Added hermetic, privacy, parser, snapshot, CLI, and TUI regression coverage.

## 0.1.0 — 2026-10-12（中文）

- 新增独立的 Trae CN `tcut` tracker。
- 新增 session memory、topics、memory 文档、snapshot git tag、`state.vscdb`、skills、plugins 和 MCP 清单的增量索引。
- 新增九个 tab 的 Textual TUI 与标准库无头报告。
- 新增本地 SQLite 快照、恢复、health 报告和配置校验。
- 记录有意的本地内容存储偏离，以及加密 agent 数据库边界。
- 新增 hermetic、隐私、解析器、快照、CLI 和 TUI 回归覆盖。
