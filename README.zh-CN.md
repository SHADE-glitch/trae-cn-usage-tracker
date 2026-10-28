<p align="right"><a href="README.md">English</a> | <a href="README.zh-CN.md"><b>简体中文</b></a></p>

# 🐾 Trae CN 用量追踪器（`tcut`）

![Trae CN](https://img.shields.io/badge/Trae%20CN-reads%20local%20files-blue?logo=robotframework&logoColor=white)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-ff69b4?logo=terminal&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey?logo=linux&logoColor=black)
[![Repository](https://img.shields.io/badge/repository-GitHub-black?logo=github)](https://github.com/SHADE-glitch/trae-cn-usage-tracker)

**是什么** —— 一个针对 Trae CN 的被动只读追踪器：八 tab 的 TUI 与无头报告，覆盖已安装的 skill、agent、插件与 MCP server、发生过的工具调用，以及账户最后的 credit 余额。

**解决什么** —— Trae CN 几乎不留可读数据；`tcut` 把能读到的索引进一个本地 SQLite 文件，并如实标出它填不上的空白。

**怎么跑** —— `./install.sh`，然后 `tcut sync`。

**去哪看** —— 见 [AGENTS.md](AGENTS.md) 与 [MAINTENANCE.md](MAINTENANCE.md)。

> ⚠️ **只读 Trae CN，就停在这里。** 它本来要和另外三个追踪器并排，但一直没能并排起来：Trae CN
> 落盘的文件和那三家读的东西对不上，所以家族的合并视图始终没法把它算进去。作者**已不再开发**，
> 只把它作为一次尝试的记录保留——填得上的面板是诚实的，填不上的都标成了空白。下面请当作快照读，
> 而不是路线图。

> 🔭 看看你**实际**怎么用 Trae CN —— 装了哪些 🎯 skill、🤖 agent、🧩 plugin、🔌 MCP server，
> 发生过多少次 🧰 工具调用，以及账户最后被扣到多少 💳 credits。

---

## 📖 目录

- [✨ 特性](#-特性)
- [🤔 为什么做这个](#-为什么做这个)
- [📝 记录了什么，以及没有记录什么](#-记录了什么以及没有记录什么)
- [🏗️ 工作原理](#️-工作原理)
- [📊 八个 tab](#-八个-tab)
- [💳 Credits 与 tokens](#-credits-与-tokens)
- [📋 环境要求](#-环境要求)
- [🚀 安装](#-安装)
- [🧭 用法](#-用法)
- [⚙️ 配置](#️-配置)
- [🔒 存储与隐私](#-存储与隐私)
- [🧪 测试](#-测试)
- [📁 仓库结构](#-仓库结构)
- [📚 维护说明](#-维护说明)
- [⚠️ 限制与路线图](#️-限制与路线图)
- [🧹 卸载](#-卸载)
- [🙏 致谢与来源](#-致谢与来源)
- [📄 许可](#-许可)

## ✨ 特性

- 🧰 **八个视图，一条命令** —— dashboard、tools、skills、agents、plugins、MCP、tokens、usage。
- 📜 **全量历史，一次建好** —— 把盘上已有的每个会话都回填进来，之后只索引新增字节。
- 🪶 **被动且只读** —— 不装 hook、不装插件、不改 Trae 源文件。Trae 自己的目录只被读取，索引跑完后逐字节哈希一致。
- 🗃️ **一个本地 SQLite 文件** —— 不联网、不上传、无遥测。
- 💳 **对两处空白如实说明** —— 别的工具用模型 token 填的那个槽位，这里用**按模型路由分摊的 credit 估算**填，并明确标 `est.` 与 `3P`；token 列留白并说明原因，没有数据源的面板用文字说明，而不是画一排零。
- 🧰 **工具调用按会话计数** —— Trae 的快照仓库只用 id 标记一次调用，从不写工具名，所以 Tools 页把 id 聚合成会话，而不是编造一个读不到的工具名。
- 📅 **按自然日分窗，按 tab 独立** —— 顶栏范围（今天 / 2 天 / 3 天 / 7 天 / 14 天 / 30 天 / 全部）是**按 tab 保存**的，改一个不会动另一个。实体页默认 **7 天**，Dashboard 与 Tokens / Usage 页默认 **7 天**，Skills、Plugins、MCP 恒为全量。窗口是本地自然日（00:00 → 现在），不是"现在往前 N 小时"。
- 🔎 **两级下钻** —— 在 Tools 或 Usage 的会话行、Agents 的 agent 行上按 <kbd>Enter</kbd> 或双击，打开该会话的详情屏：intent、actions、学到的东西、topics、选中的模型与它的 credit 区间。
- 📝 **散文照存，但由开关控制** —— 会话摘要、输入历史、记忆段落默认存在本地库里，因为 Trae CN 除此之外什么都不留明文。`store_content = false` 会清掉它们、保留元数据。这是相对同族工具"仅元数据"规则的**明示偏离**，并且只差一个开关就能关掉。
- 🔐 **推导出的时间不会长得像实测** —— 本机 49 个会话里有 25 个在明文里没有任何时间戳，于是改用会话 id 的创建秒，并在前面打一个 `~`，面板同时报出这样的行有多少。

## 🤔 为什么做这个

Trae CN **写**了原始数据，只是从不**展示**它。它保留了：

- 📜 `~/.trae-cn/memory/` 下**逐会话摘要、主题行和记忆散文**；
- 🏷️ 每个会话一个 git 仓库里的**附注快照 tag**，一个 turn 一个、一次工具调用一个；
- 🗃️ 一个 `state.vscdb` SQLite 里的**输入历史、模型目录和 agent 清单**；
- 📦 以普通目录形式存在的**已安装 skills、plugins 和 MCP servers**；
- 💳 它启动时追加到 renderer log 里的 **credit 余额行**；

……但应用本身只给一个上下文计量条。**没有**任何跨会话的"到底用了什么"分解，也完全看不到 credits 去了哪儿。
`tcut` 填的就是这个缺口。

## 📝 记录了什么，以及没有记录什么

盘上真实存在的、保真度最高的明文，就是本工具记录的东西：会话及其项目、agent、turn 与工具调用计数，
每个会话选中的模型，带账号与分组的完整模型目录，已安装清单，主题行，输入历史，记忆段落，以及 Trae
启动时写下的 credit 余额采样。

有三样它**不**记录，每一样都是实测说它不在那里：

| 缺失 | 原因 |
|---|---|
| 🔢 **token 数** | `~/.trae-cn` 与 `~/.config/Trae CN` 下 11,837 个文件按带引号的 token 键（`prompt_tokens`、`rawUsage` 等）搜过，零命中，而同样的搜法在 CodeBuddy 转录里能命中。agent 库读出来是 8.000 bits/byte、零可读关键字，WAL 帧是密文；日志里的 usage 接口只有 URL 加状态码，没有响应体。所有 token 位置因此渲染 `-`。 |
| 🧰 **工具名** | 快照 tag 是 `toolcall-<messageId>-<toolcallId>` —— 只有这对 id，没有别的。`toolcall_events` 存的就是这些 id，所以 Tools 页是**按会话的计数**，不是按工具的排名。工具名只能靠编造。 |
| 📊 **逐请求记录** | Trae 根本不写请求日志，所以 Usage 页按**会话**聚合，并在自己的说明行里讲清楚，而不是渲染一张永远没有请求的请求表。 |

证据见 [`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md)。

## 🏗️ 工作原理

```text
   ~/.trae-cn/                 tcut                    ~/.local/share/
   ~/.config/Trae CN/                              trae-cn-usage-tracker/
 ┌──────────────────┐        ┌─────────────────────┐        ┌────────────────────────┐
 │ memory/projects/ │        │  tcut-sync.py       │        │  usage.db               │
 │   **/*.jsonl  ───┼─ 只读 ─▶  解析 + 分类        │  写入  │  SQLite（sessions ·    │
 │                  │        │  增量、幂等          ├───────▶│  tools · skills ·      │
 │ ModularData/     │        └─────────────────────┘        │  agents · plugins ·    │
 │   ai-agent/      │                  ▲                   │  mcp · credits）       │
 │   snapshot/**/.git               │                   └───────────┬────────────┘
 │ skills/ plugins/ mcps/  ┌─────────┴───────────┐                 │
 │ User/**/state.vscdb    │  tcut-tui.py（TUI） │◀─── 查询 ───────┘
 │ logs/**/renderer.log   │  tcut-stats.py（CLI）│
 └──────────────────┘     └─────────────────────┘
       从不被写入
```

`tcut` 是**被动读取器**：它解析 Trae 已经写下的文件并建立索引，从不改动 Trae 的文件、不装 hook、
不给宿主增加任何运行时开销。

## 📊 八个 tab

**Dashboard** 首先打开：先看一眼关键数字，再决定往哪儿钻。tab 上方有一条共享顶栏承载范围选择器，
而**每个 tab 各存各的范围** —— 改一个 tab 的窗口不会动另一个。Dashboard、Tools、Agents、Tokens、
Usage 默认 **7 天**；Skills、Plugins、MCP 完全没有可用时间戳，因此是全量并隐藏范围选择器。窗口只改
**计数**，从不删行。

| | Tab | 展示什么 |
|---|-----|---------|
| 🧭 | **Dashboard** | 用量 KPI（会话、项目、turn、工具调用、输入、agent、skills、plugins、MCP）、已安装清单计数、Top 5 项目 / agent / 模型（3P 带标记）、按天的活动曲线，以及 `Credits · routes · sync` 面板（余额、消耗下界、估算中的已分配 / 未分配、3P 会话） |
| 🧰 | **Tools** | **按会话**的工具调用 —— 从 id 推出来的计数，附该会话首次与末次调用。是计数，不是工具名：见 [Credits 与 tokens](#-credits-与-tokens) |
| 🎯 | **Skills** | 已安装 skill 清单。全量：Trae 不记录逐 skill 的调用 |
| 🤖 | **Agents** | 已安装的 agent，以及窗口内有多少会话点名了它 |
| 🧩 | **Plugins** | 已安装 plugin 清单，带版本号。全量 |
| 🔌 | **MCP** | 已安装 MCP server 清单。全量 |
| 🔢 | **Tokens** | **按模型路由**的 credit 估算榜：模型、渠道、`Built-in` / `3P`、`credits est.`、份额、会话数与最后使用。token 列如实留 `-`，因为 Trae 不写 token（第三方路由也不写） |
| 📊 | **Usage** | 摘要面板 + 每 **（会话, 模型选择）** 一行的日志 —— 时间、会话、模型、路由、credits 估算、项目、turn、调用 |

在 Tools / Usage 的会话行、Agents 的 agent 行或 Tokens 的模型路由行上按 <kbd>Enter</kbd>（或双击）进入
**下钻**。三个清单页没有下钻内容，会弹一条通知说明，而不是打开一个空屏。

三条规则贯穿所有表格，它们存在是因为反面会被读成事实：

- **窗口不会为看不见的行报 0。** 带窗口的计数只在某行既无实测 `last_ts`、又无推导 `created_ts` 时
  渲染 `-`（`db.window_count`）。`0` 保留给"实测的没有"。
- **推导的时间打 `~`。** 本机 49 个会话有 25 个没有任何实测时间戳；创建秒从会话 id 解出（对 24 个
  有时间的会话，中位偏差 0.0 秒），面板同时披露这样的行有多少。
- **对从未带过该字段的行求和，打印 `-` 而不是 `0`。** 49 个会话里有 28 个既没有解出的项目名也没有
  原始项目键，所以一个窗口确实可能一个项目键都没有。

表格永远不会显示半截列：每张表保留能放下的最长**前缀**列集，并把丢掉的列名写在表格上方的说明行里，
于是窄终端换来的是少列而不是可读性。长单元格按 `name_cap` 截断，说明行会打印当前生效的数字。

## 💳 Credits 与 tokens

这是读数字之前值得先理解的一条 Trae 专属事实，它是本机实测出来的，不是假设的：

| 轴 | Trae CN 报告什么 | 不报告什么 |
|---|---|---|
| 💳 **credits** | renderer log 里启动时采到的**余额档位** | 任何逐请求消耗 —— 采样是档位不是增量，而 Trae 拒绝应答的那次抓取在库里根本没有数字 |
| 🔢 **tokens** | 盘上什么都没有（第三方路由也一样） | —— |

Tokens 页因此不列原始余额，而是列**按模型路由的估算**：两次余额采样之间的落差是唯一实测的消耗量，
索引器把它按该区间内新建会话的 turn 数分摊给这些会话选中的模型；一个会话选了两个模型就均分。每一行
都标 `est.`，各行之和对得上落差，对不上任何选择的部分单独记成 `Unallocated`，绝不摊到某个模型头上。
`share` 是**已分配**估算里的占比，不是全部消耗的占比 —— 否则 92% 会被读成"花了九成 credit"。

- **路由来自 id 的形状，不是猜的。** `...__Model_null` 是 Trae 自己的路由；带渠道与尾部 id 的
  （如 `solo_agent_3_volcengine-plan_..._2837387906`）是第三方。`Route` 列写 `Built-in` / `3P`，
  `Provider` 列只在 3P 时给渠道名。模型目录只负责把名字解出来，不能把一个 `_null` 选择变成 3P。
- **`spent ≥` 仍然是下界。** 它等于本次余额采样与上一次之间的落差；两次采样之间可能正好落了一笔
  每日赠送，真实消耗只会更高。
- **被拒绝的抓取不是 `0`。** 这里十二次采样里有两次 Trae 没有应答；它们存成"无数值"并被排除在
  序列之外，而不是把一次缺失的余额变成一次落差。
- **token 列不填，是因为没有源。** `~/.trae-cn` 与 `~/.config/Trae CN` 下按带引号的 token 键搜过，
  零命中；agent 库是加密的，日志里的 usage 接口只有 URL 加状态码。第三方路由走的是同一个宿主，
  同样不落 token。
- **工具调用 id 是计数，不是名字。** `toolcall-<messageId>-<toolcallId>` 就是 tag 的全部内容。
  Tools 页按会话聚合，这是这个 tag 能支撑的上限。

整数都是每日赠送；唯一的分数余额（154.0244，落在 1400…1800 之间）是唯一能证明发生过消耗的采样，
而那个区间里同时也落了一笔赠送。

## 📋 环境要求

| | |
|---|---|
| 🐧 操作系统 | Linux —— 在 Ubuntu 上开发并验证；其他发行版**未验证** |
| 🐾 Trae CN | 桌面应用；schema 是对着**本机的文件**验证的，不是对着版本号。国际版 Trae 不在范围内 —— 见 [`docs/maintenance/compatibility.md`](docs/maintenance/compatibility.md) |
| 🐍 Python | 3.11 — 3.14，两端实测全绿（CI 跑这两端）。无头命令只需标准库；TUI 需要 `textual` |
| 🖥️ `textual` | 仅交互式 TUI 需要（由 `install.sh` 安装） |

## 🚀 安装

```bash
cd trae-cn-usage-tracker
./install.sh          # 创建带 textual 的 .venv，并把 tcut 链到 ~/.local/bin
tcut sync             # 从你已有的 Trae CN 文件建立索引
tcut                  # 启动 TUI
```

不想用 venv？无头报告用系统 `python3` 就能跑：

```bash
python3 scripts/tcut-sync.py
python3 scripts/tcut-stats.py stats
```

### 🔄 可选：不打开 TUI 也让索引保持新鲜

[`systemd/`](systemd) 里带了两个 user unit。装上之后它们每天跑一次 `tcut sync --quiet`：

```bash
mkdir -p ~/.config/systemd/user
cp systemd/tcut-sync.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tcut-sync.timer
```

`Persistent=true` 会补上关机期间错过的运行，唤醒时间最多抖 15 分钟，服务以 `Nice=10` 运行。

## 🧭 用法

```bash
tcut                     # 🖥️  交互式 TUI（八个 tab）
tcut sync                # 🔄  增量索引新增的 Trae 数据
tcut sync --full         # ♻️  从零重建数据库
tcut stats               # 📊  各类别概览
tcut sessions            # 📋  会话表，附每个会话选中的模型
tcut recent              # 🕒  最近的会话，只给计数
tcut show SESSION_ID     # 🔍  会话详情
tcut projects            # 📁  项目计数
tcut prompts             # 💬  本地输入历史
tcut agents              # 🤖  agent 及其会话数
tcut credits             # 💳  credit 余额采样与消耗下界
tcut models              # 🔢  模型目录：账号、分组、计价倍率、上下文窗口
tcut inventory           # 📦  所有已安装行合并成一张表
tcut skills|plugins|mcp  # 🎯 已安装清单
tcut memory              # 🧠  已存储的记忆段落
tcut export              # 💾  每张表原样导出为 JSON
tcut health              # 🩺  数据库 + 数据源体检
tcut backup              # 💾  在危险步骤前做快照
tcut restore             # ⏪  列出快照；`tcut restore NAME` 回滚其中一个
tcut format              # 🧾  本工具依赖的 Trae CN 字段与路径
```

Tools、Tokens、Usage 三个面只有 TUI 版本：它们的聚合是按窗口的摘要，而这正是顶栏的用途；三者都没有
对应的无头报告。

| 变量 | 默认值 | 用途 |
|---|---|---|
| `TCUT_DB` | `~/.local/share/trae-cn-usage-tracker/usage.db` | 数据库位置 |
| `TCUT_TRAE_CN_HOME` | `~/.trae-cn` | 源目录（memory、快照） |
| `TCUT_TRAE_CN_DATA` | `~/.config/Trae CN` | 源目录（agent 库、清单、日志） |

所有命令都支持把 `--db` 放在子命令前或后。

## ⚙️ 配置

每个开关都等于程序发布时的取值，配置文件是可选的：不加它，`tcut` 的行为就与此处写的一致。

配置文件是 `~/.config/tcut/config.toml` —— 或用 `TCUT_CONFIG` 指向别处。环境变量优先于配置文件。

| 键 | 默认值 | 环境变量 | 限制什么 |
| --- | ---: | --- | --- |
| `top_n` | `5` | `TCUT_TOP_N` | Dashboard 的 Top 项目 / Top agent 行数 |
| `log_limit` | `100` | `TCUT_LOG_LIMIT` | Usage 页的会话日志行数，以及 `tcut prompts` 的行数 |
| `detail_limit` | `200` | `TCUT_DETAIL_LIMIT` | 详情屏行数 |
| `name_cap` | `28` | `TCUT_NAME_CAP` | 表格渲染的单元格最大宽度，超出即截断 |
| `refresh_secs` | `5` | `TCUT_REFRESH_SECS` | TUI 重绘计时器 |
| `sync_secs` | `30` | `TCUT_SYNC_SECS` | TUI 自动同步计时器 |
| `store_content` | `true` | `TCUT_STORE_CONTENT` | 是否存储散文内容 |

- **配置文件坏了就让 TUI 停下来**，并报出路径和原因，而不是悄悄按默认值启动。`tcut health`
  给出同样的结论，包括它读的是哪个文件。
- **未知键会被拒绝**，取值也做类型和范围校验（`top_n = 0` 是一片空白面板，不是一个偏好）。
- 由标准库的 `tomllib` 解析，因此**不增加任何依赖**、也不增加任何网络路径。没有任何代码会写这个
  文件，数据库里也不存任何设置。

## 🔒 存储与隐私

索引只写本地 SQLite，不上传任何内容；生产脚本不导入网络或进程启动模块。Trae 自己的目录只作为只读
输入。

本项目有意不同于 CodeBuddy tracker 的"仅元数据"策略：默认 `store_content = true`，把会话
`intent`/`outcome`、actions、learned、主题摘要、prompt history 和 memory 段落**仅存入本地
SQLite**。设置 `store_content = false` 后保留元数据并删除全部这些 prose；下一次 sync 还会清理数据库
中已经存在的 prose。两个方向都有检查支撑，而不只是意图 —— 见
[`AGENTS.md`](AGENTS.md#invariants-and-how-to-check-them)。

模型数据属于元数据：模型目录（账号、分组、名字、provider、计价倍率、上下文窗口）和每个会话选中的
模型不受 `store_content` 影响，因为它们不是散文。自定义端点的目录条目里同时带着
`ak`、`sk`、`base_url` 和 `custom_config`，索引器按白名单取字段，这些一个都不会进库。

## 🧪 测试

```bash
python3 -m unittest discover -s scripts/tests     # Ran 292 tests ... OK
```

测试套件是纯 `unittest`（`pytest` 也能发现它们）。其中两个需要装 `textual`：`test_tui.py`，以及
`test_config.py` —— 后者的接线用例会加载 TUI 模块，证明每个设置都真的被某个渲染器读到。每个套件
都在临时目录里自建一份一次性数据库**和**一棵一次性 Trae 目录树：你的真实 `usage.db` 与真实的
`~/.trae-cn` 从不被打开，本仓库里也没有任何代码路径能联网（`test_privacy.py` 持有那份 import
白名单，正是它保证这一点）。

| 套件 | 用例 | 覆盖什么 |
|---|---:|---|
| `test_sync.py` | 64 | 各个源读取器（会话 memory JSONL、主题行、记忆散文、快照 git tag、agent 的 `state.vscdb`、清单目录树、renderer log）、增量与 `--full` 重建、`models` 复合主键、凭证哨兵证明、unparsed 记账 |
| `test_stats.py` | 45 | 无头 CLI 端到端：每个子命令真实 `main([...])`、`--db` 放前后、`export` / `inventory` / `show` / `health`、`backup`→`restore`、生成的 `format` 面、空态提示 |
| `test_tui.py` | 41 | 通过 Textual 自己的 `run_test` 测试 tab 接线与报表形状、按 tab 的范围、列计划、空态、响应式布局、状态行**实际渲染**出来的样子，以及 Tokens 路由表的 `3P` / token / 估算单元格与下钻 |
| `test_config.py` | 21 | 设置层：默认值与 TUI 自身常量对齐、文件、环境变量优先级与边界、坏掉的配置文件报出路径，以及每个旋钮真的被某个渲染器读到 |
| `test_maintenance_docs.py` | 20 | 生成的 format 文档不能与代码漂移、维护资产都能从路由页到达、任何文档都不得声称 workflow 没跑的 CI 版本 |
| `test_usage.py` | 19 | 按会话的工具调用聚合及其窗口、Usage 摘要面板的合计、credit 序列的 `spent ≥` 下界，以及 v5 解码：内置 / 3P、按路由分摊 credit、每个模型选择一行 Usage |
| `test_snapshots.py` | 16 | 破坏性步骤前的自动快照、列出、恢复、保留策略 |
| `test_privacy.py` | 11 | import 白名单以及绕过它的调用（`__import__` / `eval` / `import_module`）、证明 Trae 自己的目录树未被写入的指纹、`store_content` 哨兵扫描每一列文本、模型凭证扫描 |
| `test_format_registry.py` | 10 | Trae CN 格式登记表与解析器双向一致 |
| `test_hermetic.py` | 13 | 运行时绊线：本套件从不打开真实的 `usage.db`，也不读取真实 Trae 主机目录，进程内和子进程都受守卫 |
| `test_record_coverage.py` | 6 | 每条被覆盖的提交都在 `CHANGELOG.md` 里有记录 |
| `test_dispatcher.py` | 6 | `bin/tcut`：子命令路由、venv 解析、装不上时仍能给出帮助 |
| `test_readme_bilingual.py` | 3 | 两份 README 始终是同一份文档的两种语言：同样的分节、同样的语言开关 |
| `test_doc_anchors.py` | 6 | 每份入库文档里的每个相对链接都指向真实存在的文件，每个 `#片段` 都落得到真实标题——页内与跨文件都算，按 GitHub 的解析方式；并且每份目录都把它描述的每个分节列全 |
| `test_readme_counts.py` | 2 | 两份 README 里的每个用例总数都等于 `unittest discover` 数出来的数，且两页都写全了加载器知道的每个设置 |
| `test_conventions.py` | 9 | A 档根文件层是否在根目录齐备、AGENTS.md 是否用一行指明档位而不是抄规范正文，以及忽略清单覆盖的运行态是否真的没有被跟踪 |

上面两个数字由 `test_readme_counts.py` 保证诚实：总数漂了就会挂测试。套件用例数是从语法树读出来的，
所以新增一个套件却忘了在这张表里加一行，会体现为总数不对，而不是"表格看起来旧了"。

## 📁 仓库结构

| 路径 | 是什么 |
|---|---|
| `bin/tcut` | bash 入口。刻意用 bash：当 TUI 的 venv 缺失或损坏时它仍要能给出有用的报错，因此不能依赖 Python。优先 `./.venv/bin/python`，回退 `python3` |
| `install.sh` | 创建 venv（有 `uv` 就用 `uv`）并把 `~/.local/bin/tcut` 链成符号链接 |
| `scripts/tcut_db.py` | SQLite schema 与所有入口共用的查询helper |
| `scripts/tcut-sync.py` | 各源读取器与增量索引器（`--full`、`--quiet`） |
| `scripts/tcut-stats.py` | 无头报告：`stats` · `sessions` · `recent` · `show` · `projects` · `prompts` · `agents` · `models` · `credits` · `skills` · `plugins` · `mcp` · `memory` · `inventory` · `export` · `health` · `backup` · `restore` · `format` |
| `scripts/tcut-tui.py` | 八 tab 的 Textual UI |
| `scripts/tests/` | 上表那些用例 |
| `docs/maintenance/` | Trae 变化时要重新核对的东西：生成的格式依赖面、兼容性矩阵，以及带产出命令的测量基线 |
| `systemd/` | 可选的每日同步 service + timer |
| `requirements.txt` | `textual>=8.2,<9` —— 仅 TUI；其余全是标准库 |

两条路径都可覆盖以做沙箱安装：启动器看 `TCUT_SCRIPTS` 和 `TCUT_VENV`，数据看 `TCUT_DB`、
`TCUT_TRAE_CN_HOME` 和 `TCUT_TRAE_CN_DATA`。

## 📚 维护说明

见 [`docs/maintenance/`](docs/maintenance/README.md)：format 文档区分已观察事实、加密数据，以及索引器
有意不声称的内容；compatibility 矩阵说明支持范围；measurement 文档记录基线和产出它的命令。解析器
依赖的格式面是生成的 —— `tcut format` 打印它，`tcut format --write` 刷新文档里那个块，两者一旦不一致，
`test_maintenance_docs.py` 就会失败。

## ⚠️ 限制与路线图

- 🔢 **这个源永远给不出 token。** 不是读取器的缺口：见 [Credits 与 tokens](#-credits-与-tokens)。
  Tokens 页保留 token 列是为了和 `cbut` 对齐，但只能留白；页顶说明讲清原因。
- 🧰 **工具无法按名字排名。** 只有"按会话的计数"是真的；一张按工具分的表需要读那个加密的 agent 库。
- 🎯 **Skills、Plugins、MCP 是清单而不是用量。** Trae 不记录逐实体的调用，所以这三页展示已安装的
  内容，而 Agents 页是唯一能计数的一页。面板稀疏是诚实的，编出来的排名不是。
- 📊 **Usage 页按会话，不按请求。** 没有请求日志可读。
- 🔌 **会话类视图没有 TUI tab。** `tcut sessions`、`tcut projects`、`tcut prompts`、`tcut memory`
  仍然能打印它们；它们从 TUI 移除是为了让 tab 集合与 `cbut` 保持一致。
- 🔄 同步是手动的（或靠可选的 systemd timer）；没有实时 hook。

## 🧹 卸载

`tcut` 在仓库之外只碰三个地方，删掉它们就什么都不剩：

```bash
systemctl --user disable --now tcut-sync.timer 2>/dev/null          # 仅当你装过
rm -f ~/.config/systemd/user/tcut-sync.service ~/.config/systemd/user/tcut-sync.timer
systemctl --user daemon-reload
rm -f ~/.local/bin/tcut                                            # install.sh 建的符号链接
rm -rf ~/.local/share/trae-cn-usage-tracker                        # SQLite 索引
```

删掉仓库目录（连同它的 `.venv`）就彻底结束了。Trae 自己的文件从头到尾只被读取，那里没有东西需要
还原。🗑️

## 🙏 致谢与来源

本项目参照
[`codebuddy-usage-tracker`](https://github.com/SHADE-glitch/codebuddy-usage-tracker) 的思路而建 ——
它为 CodeBuddy Code 追踪同样的类别，它的八 tab 布局也是本项目对齐的对象。架构是同一个 —— 读宿主已经
写下的东西 —— 但 schema 是 Trae CN 自己的：用 credits 代替 provider 上报的 token，用 git tag 而不是
名字标记工具调用，按会话而不是按请求聚合用量，以及把散文存放放在一个显式的 `store_content` 开关后面。

## 📄 许可

MIT —— 见 [LICENSE](LICENSE)。© 2026 SHADE-glitch
