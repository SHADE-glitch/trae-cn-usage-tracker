# Changelog

## 0.5.0 — 2026-10-12

- Cut the TUI back to cbut's tab set. The tenth **Usage** tab added in 0.4.0 is gone, and with
  it **Sessions**, **Projects**, **Prompts** and **Memory**, the views cbut has no room for.
  Five tabs remain: Dashboard · Skills · Agents · Plugins · MCP.
- Recorded why **Tools**, **Tokens** and **Usage** are not implemented, with a fresh
  measurement rather than an assumption: a snapshot tag identifies a tool call by id only —
  walking every one of a snapshot repo's 108 blobs yields a single `"name"` value, the literal
  `"toolcall"` — the agent store is encrypted, so no token count exists on disk, and there is
  no per-request record at all. None of the three is replaced by an empty panel.
- The removed rows stay indexed and stay printed: `tcut sessions`, `tcut projects`,
  `tcut prompts`, `tcut memory`. A session's detail (intent, actions, learned items, topics,
  selected model) is now reached `Agents → its sessions → detail`.
- `log_limit` became a CLI-only setting — it caps `tcut prompts`. The four assertions that
  checked it reached the TUI were replaced by one case proving the CLI honours it and that
  `--limit` overrides it, so the setting did not quietly lose its only coverage.
- Two guards that compared a document with a document now read the product: `bin/tcut`'s
  advertised tab count is checked against the `TabPane`s the app composes, and the README's
  `Ran N tests` line is checked against `unittest` discovery. Both failed on the stale claims
  they used to bless, which is the evidence that they now check something.
- Fixed a parser that was losing **every** snapshot timestamp. The refs name annotated
  tag objects, and `_commit_time` recognised only a `commit ` header, so all 89 turn rows and
  139 toolcall rows stored `ts = NULL` on this machine — while the suite stayed green, because
  the fixtures wrote lightweight refs (ref → commit), a shape the real app never produces. The
  tag is now peeled to its `object` commit; the `tagger` line (measured ~10 s behind the
  commit) is used only when the commit cannot be read; an unreadable object is counted as
  `unparsed = snapshot:time_unreadable` instead of going quietly undated. Real footprint after
  the fix: turns 89/89 and toolcalls 139/139 dated, sessions 24/49 with a **measured** time —
  the other 25 have no timestamp of their own anywhere in plaintext, which is what the next
  three entries are about.
- A windowed count that the range cannot see now renders `-`, never `0` (`db.window_count`),
  and the Agents drill-down inherits the window of the row it was opened from and names that
  range in its heading. Before this, a row printed `0 sessions` and Enter on it opened a list
  of 22 — the same row, two numbers, one screen.
- Schema **v4**: `sessions.created_ts`, filled from the session id's first four hex bytes.
  Re-measured 2026-10-12 against the 24 sessions that also have a dated turn: median delta
  0.0 s, worst 144 s, and **no turn anywhere predates it** — a floor, not a guess at the
  middle. It lives in its own column and reaches a window only through
  `COALESCE(last_ts, created_ts)` (`db.SESSION_TIME`), now the single time expression behind
  every windowed view; `first_ts`/`last_ts` still mean measured activity and no row is
  rewritten, so an upgraded index keeps everything it had measured. The 25 sessions no range
  could place are placeable now.
- A position that came from the id prints as `~10-07 10:45` (`db.derived_mark`) in both the
  TUI and `tcut sessions`/`tcut recent`, and the Dashboard's note line says how many rows are
  in that state (`q_kpi["unmeasured"]` — 25 of 49 here). A table where a derivation looks
  exactly like a measurement is how a derivation quietly becomes a fact.
- The Dashboard's two leaderboards stopped dropping the rows they could not date.
  `q_projects` reports `undated` beside `sessions` the way `q_agents` already did, and both
  rank it above a plain zero, so on a capped list a hidden entity keeps its slot and prints
  `-`. The empty panels are two sentences now, because they are two problems: `no agents
  installed` asks for a sync, `none dated in 7 days` asks for a wider range. **Top models**
  had been blaming the indexer for its window — "no model selection recorded" when the
  selections exist and only fall outside the span.
- Found by rendering that fix against the real index: **Top agents was blank next to a
  Sessions panel reading 20**, and the panel's sentence blamed the dates. It was the label.
  Measured 2026-10-12: 24 of 49 sessions carry no `agent` at all, and all 20 sessions in the
  current 7d window are among them — `agent` comes only from the memory records, while
  `agents` is the installed inventory, so the join has nothing to match on. A blank panel
  names its own cause now: `none dated in <range>` (the range placed no session), `no session
  in this range names an installed agent` (it placed sessions with no label), `no agents
  installed` (the inventory is empty). Three sentences, three fixes — the old single sentence
  sent the reader to the range picker for two of them, where widening it changes nothing.
- Six new cases, each proved red by reverting its own fix in a throwaway copy (no peel, no
  tagger fallback, no `unparsed` note, dash off, bounds not passed) against a green control run
  of the unmutated copy first.
- Every rule added since then was provoked the same way — **thirteen rules, sixteen runs**,
  each against a green control: `undated` removed from the query, its tie-break removed from
  the ordering, the agent `undated` subquery left uncorrelated, `window_count`'s unit
  ignored, the leaderboard back to dropping zero rows, the two empties collapsed into one
  sentence, Top models back to blaming the indexer, the disclosure line deleted, `unmeasured`
  removed from the KPI, the v4 migration's backfill and its plausibility bound removed,
  the `~` deleted, and the `COALESCE` fallback stripped from one time expression and then
  from both. **Two survived the first sweep**, and both survivals were the fixture's fault,
  not the rule's: the ordering tie-break passed because the project keys happened to sort the
  hidden row into its slot anyway, and the fallback passed because only the un-aliased
  expression had been mutated while the tab under test reads the aliased one. The fixture
  was rebuilt so `-z` is the hidden key and `-b` the idle one, and a new case covers the
  three windowed views the fallback feeds — both then went red on their own.
- `window_bounds("all")` also dropped its upper bound. With `last_ts < now` it excluded every
  row that has no timestamp, so "All time" showed the 25 undated sessions nowhere — the one
  range that is supposed to be the escape hatch was the second place they went missing. No
  test had ever exercised `window_bounds`; two now do.
- Fixed the manifest: `pyproject.toml` still declared `0.3.0` while the changelog said `0.4.0`.
- The suite is **192** tests (171 before the cut: two tab-driven cases removed, one CLI case
  added for `log_limit`, eight for the timestamp and window rules, four for the derived
  creation time, ten for the leaderboards and the fallback that feeds them).

## 0.5.0 — 2026-10-12（中文）

- TUI 收回 cbut 的 tab 集合。0.4.0 加的第十个 **Usage** tab 删掉，cbut 没位置放下的 **Sessions**、**Projects**、**Prompts**、**Memory** 一并删掉。剩五个：Dashboard · Skills · Agents · Plugins · MCP。
- **Tools**、**Tokens**、**Usage** 不做的理由用新实测写下，而不是靠假设：快照 tag 只用 id 标记一次工具调用——走查一个快照仓的 108 个 blob，唯一的 `"name"` 值是字面量 `"toolcall"`；agent 库加密，盘上不存在 token 数；也没有任何逐请求记录。三者都不拿空面板顶替。
- 被删的视图仍然索引、仍可打印：`tcut sessions`、`tcut projects`、`tcut prompts`、`tcut memory`。会话详情（intent、actions、learned、topic、所选模型）现在按 `Agents → 该 agent 的会话 → 详情` 进入。
- `log_limit` 变成 CLI 专属设置——它管 `tcut prompts` 的行数。原先四条"这个值到达了 TUI"的断言被换成一条证明 CLI 真的按它截断、且 `--limit` 能覆盖它的用例，这个设置没有悄悄失去唯一覆盖。
- 两张"文档对文档"的守卡改为读产品：`bin/tcut` 声称的 tab 数与 app 实际组合的 `TabPane` 数比对，README 的 `Ran N tests` 与 `unittest` discovery 的计数比对。两张卡都在它们曾放过的过期说法上失败了一次，这就是它们现在真在检查东西的证据。
- 修掉一个把所有 snapshot 时间都弄丢的解析器。snapshot 的 ref 指向**附注 tag 对象**，而 `_commit_time` 只认 `commit ` 头，于是本机 89 条 turn、139 条 toolcall 全部存成 `ts = NULL`——测试却还是绿的，因为 fixture 写的是轻量 ref（ref 直指 commit），那正是真实程序不会产生的形状。现在会把 tag 剥到它的 `object` commit；只有在 commit 读不到时才用 `tagger` 行（实测比 commit 晚约十秒）；读不到的对象计入 `unparsed = snapshot:time_unreadable`，不再无声地变成无时间戳。修好后真机读数：turn 89/89、toolcall 139/139 带时间，sessions 24/49 带**实测**时间——剩下 25 个在明文里没有属于自己的时间，下面三条说的就是它们。
- 窗口看不到的行不再报成 `0`，改报 `-`（`db.window_count`）；Agents 的下钻继承它来自那一行的时间窗，标题里写明是哪个范围。修之前：行上写着 `0 sessions`，按 Enter 进去是 22 条——同一行、两个数字、同一个屏幕。
- 数据库升到 **v4**：新增 `sessions.created_ts`，值取自会话 id 的前四个十六进制字节。2026-10-12 就着 24 个"同时带有时间戳 turn"的会话重测：中位差 0.0 秒、最差 144 秒，而且**没有任何 turn 早于它**——它是下界，不是对中间的猜测。它待在自己的列里，只通过 `COALESCE(last_ts, created_ts)`（`db.SESSION_TIME`）进入窗口，这个表达式现在就是所有窗口视图共用的那一个；`first_ts`/`last_ts` 的含义不变，仍是实测活动，升级不重写任何一行，旧库实测到的东西一条不少。此前任何窗口都放不下的那 25 个会话，现在放得下了。
- 来自 id 的位置在 TUI 与 `tcut sessions`/`tcut recent` 里都打成 `~10-07 10:45`（`db.derived_mark`），Dashboard 下方的说明行报出这种行有多少（`q_kpi["unmeasured"]`，本机 49 个里 25 个）。一张推导与实测长得一模一样的表，就是推导被悄悄当成事实的地方。
- Dashboard 的两个排行不再丢掉"自己无法定位"的行。`q_projects` 现在和 `q_agents` 一样在 `sessions` 旁边报 `undated`，两边都把它排在真正的 0 之前，所以在有条数上限的排行里，被挡住的对象保住位置并显示 `-`。空白面板从一句话变成两句，因为它们本来就是两个问题：`no agents installed` 要的是 sync，`none dated in 7 days` 要的是更宽的范围。**Top models** 此前把窗口的锅甩给索引器——选中记录明明在库里，只是落在区间外，面板却说"no model selection recorded"。
- 新增六个用例，每个都在一次性副本里把自己对应的修复撤掉来逼红（不 peel、不用 tagger 回退、不记 `unparsed`、去掉 `-`、不传时间窗），并且先跑未改副本作对照（对照必须绿，否则是仪器错）。
- 此后每条新规则都用同一个办法逼红——**十三条规则、十六次跑**，每次都先跑未改副本作对照：从查询里删掉 `undated`、从排序里删掉它的并列优先、把 agent 的 `undated` 子查询去掉关联、让 `window_count` 忽略单位、排行改回丢掉 0 行、两种空白并成一句、Top models 改回把窗口的锅甩给索引器、删掉说明行、从 KPI 里删掉 `unmeasured`、撤掉 v4 迁移的回填与合理性上下界、删掉 `~`、把 `COALESCE` 兜底从一个时间表达式剥掉再从两个都剥掉。**第一轮有两条活了下来**，而且两条都是 fixture 的错、不是规则的错：排序那条是因为项目键本身就把隐藏行排进了名额（换了键名才暴露），兜底那条是因为只改了不带别名的表达式、而被测的那个 tab 读的是带别名的另一个。fixture 重建成 `-z` 是隐藏行、`-b` 是实测 0 行，另加一条用例盯住兜底喂给的三个窗口视图——两条随后各自独立变红。
- `window_bounds("all")` 同时去掉了上界。带着 `last_ts < now` 时，它把每一行"没有时间戳"的记录都排除在外，于是 All time 也照样看不见那 25 个无日期会话——本该是逃生口的那个范围，成了它们第二次消失的地方。`window_bounds` 此前没有任何测试碰过，现在有两个用例盯着它。
- 修掉清单错误：`pyproject.toml` 还写着 `0.3.0`，而 CHANGELOG 已到 `0.4.0`。
- 测试套件 **192** 个（删 tab 前 171：删掉两个由 tab 驱动的用例，`log_limit` 新增一个 CLI 用例，时间与窗口规则新增八个，推导创建时间新增四个，排行榜与喂给它们的兜底新增十个）。

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
