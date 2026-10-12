<p align="right"><a href="README.md">English</a> | <a href="README.zh-CN.md"><b>简体中文</b></a></p>

# 🐾 Trae CN 用量追踪器（`tcut`）

![Trae CN](https://img.shields.io/badge/Trae%20CN-reads%20local%20files-blue?logo=robotframework&logoColor=white)
![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Textual](https://img.shields.io/badge/TUI-Textual-ff69b4?logo=terminal&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey?logo=linux&logoColor=black)
[![Repository](https://img.shields.io/badge/repository-GitHub-black?logo=github)](https://github.com/SHADE-glitch/trae-cn-usage-tracker)

面向 **Trae CN** 的被动、本地用量追踪器。它读取 Trae 写入 `~/.trae-cn` 与 `~/.config/Trae CN` 的明文
文件，写入一个 SQLite 数据库，并通过 Textual TUI 或无第三方依赖的 CLI 展示结果。

## 记录了什么，以及没有记录什么

Trae CN 的 agent 存储是加密的，所以本工具记录盘上真实存在、保真度最高的东西：会话、摘要、主题行、
提示词、记忆段落、快照里的 turn/tool-call ID、已安装清单，以及带账号和分组的模型目录、每个会话选中的
模型、Trae 在启动时写下的 credit 余额采样。

token 数在这台机器上不存在，这是实测结论而不是推测：`~/.trae-cn` 与 `~/.config/Trae CN` 下 11,837 个
文件按带引号的 token 键（`prompt_tokens`、`rawUsage` 等）搜过，零命中，而同样的搜法在 CodeBuddy 转录
里能命中；agent 库首 1 MB 熵 8.000 bit/byte、零关键字，WAL 帧也是密文，日志里的 usage 接口只有 URL 和
状态码、没有响应体。所以所有 token 位置显示 `-`，工具**名称**同样不会被臆造。证据见
[`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md)。

## 安装

```sh
./install.sh
```

该脚本会创建本地 TUI Python 环境，并把 `tcut` 安装到 `~/.local/bin/tcut`。无头命令只需要
Python 3.11+ 标准库；TUI 需要 `textual>=8.2,<9`。

## 命令

```sh
tcut                         # 打开五 tab 的 TUI
tcut sync                    # 增量索引
tcut sync --full             # 先快照，再重建
tcut stats                   # 概览
tcut sessions                # 会话表，附每个会话选中的模型
tcut recent                  # 最近的会话，只给计数
tcut show SESSION_ID         # 会话详情
tcut projects                # 项目计数
tcut prompts                 # 本地输入历史
tcut agents                  # agent 及其会话数
tcut credits                 # credit 余额采样与消耗下界
tcut models                  # 模型目录：账号、分组、计价倍率、上下文窗口
tcut inventory               # 所有已安装行合并成一张表
tcut skills | plugins | mcp # 已安装清单
tcut memory                  # 已存储的记忆段落
tcut export                  # JSON 导出
tcut health                  # 路径、设置、schema、未认领记录
tcut backup                  # 生成一份受管 SQLite 快照
tcut restore                 # 列出快照；加名字则恢复
tcut format                  # 打印 Trae CN 的格式依赖面
tcut format --write          # 刷新 docs/maintenance/ 里由代码生成的块
```

```sh
# 所有命令都支持将 --db 放在子命令前或后。
tcut --db /tmp/tcut.db sync
tcut stats --db /tmp/tcut.db
```

默认数据库是 `~/.local/share/trae-cn-usage-tracker/usage.db`。

## TUI 标签页

Dashboard · Skills · Agents · Plugins · MCP（共五个 tab）。

tab 集合与 cbut 一致，只少 **Tools**、**Tokens**、**Usage** 三页：它们要读的数据 Trae CN 不以明文写在
盘上——快照 git tag 只用 id 标记一次工具调用、从不写工具名，agent 库是加密的所以 token 数在盘上不
存在，也没有任何逐请求记录（已实测，见 `tcut format`）。这三页一律不做：空白的 token 面板会被读成
"用了 0"或"widget 坏了"，两者都不是事实。两边同名的 tab 在 cbut 那边是调用计数，在这里只能装安装
清单，因为 Trae 不记录 skill / plugin / MCP server 的使用次数。

会话、项目、输入历史、记忆文档这四个 cbut 没有位置放下的视图，按同一条规则从 TUI 移除。数据仍然索引、
仍然可打印：`tcut sessions`、`tcut projects`、`tcut prompts`、`tcut memory`。会话详情（intent、
actions、learned、topic、所选模型）从 agent 行进入。Dashboard 与 Agents 各自保留独立时间范围；
Skills、Plugins、MCP 没有可用时间戳，因此为 all-time 并隐藏范围选择器。

本机 49 个会话里有 25 个在明文里根本没有实测时间戳，但会话 id 的头四个十六进制字节就是它的创建秒，
索引把这个秒存成 `created_ts`，窗口因此仍能定位这一行——来自 id 的时间前面带一个 `~`，因为推导不能
长得像实测，Dashboard 下方的说明行会报出这种行有多少。计数只在对既无实测时间、又无推导时间的会话上
显示 `-`（本机 0 个），而真正的 `0` 仍然表示这个实体在该范围内不拥有任何会话。Dashboard 的
**Top projects** 与 **Top agents** 不再丢掉 `-` 行；空白面板会说明自己空在哪：`no agents installed`
（什么都没索引）、`no session in this range names an installed agent`（会话在，标签不在——本机 49 个
会话有 24 个根本没有 agent，当前这一周的会话全是这种），或 `none dated in 7 days`（这个范围一个会话
都没放下）。三种里只有最后一种该靠放宽范围来解决。Trae 真的写了的 credit 余额放在 Dashboard 的
`Credits · sync` 面板里。

## 存储与隐私

索引只写本地 SQLite，不上传任何内容；生产脚本不导入网络或进程启动模块，Trae 自己的目录只作为只读
输入。

本项目有意不同于 CodeBuddy tracker 的"仅元数据"策略：默认 `store_content = true`，把会话
`intent`/`outcome`、actions、learned、主题摘要、prompt history 和 memory 段落**仅存入本地
SQLite**。设置 `store_content = false` 后保留元数据并删除全部这些 prose；下一次 sync 还会清理数据库
中已经存在的 prose。

模型数据属于元数据：模型目录（账号、分组、名字、provider、计价倍率、上下文窗口）和每个会话选中的
模型不受 `store_content` 影响，因为它们不是散文。自定义端点的目录条目里同时带着
`ak`/`sk`/`base_url`/`custom_config`，解析器按白名单取字段，这些一个都不会进库。

## 设置

配置文件是 `~/.config/tcut/config.toml`（可用 `TCUT_CONFIG` 改路径），环境变量优先于配置文件。

| 键 | 默认值 | 环境变量 |
| --- | ---: | --- |
| `top_n` | `5` | `TCUT_TOP_N` |
| `log_limit` | `100` | `TCUT_LOG_LIMIT` |
| `detail_limit` | `200` | `TCUT_DETAIL_LIMIT` |
| `name_cap` | `28` | `TCUT_NAME_CAP` |
| `refresh_secs` | `5` | `TCUT_REFRESH_SECS` |
| `sync_secs` | `30` | `TCUT_SYNC_SECS` |
| `store_content` | `true` | `TCUT_STORE_CONTENT` |

`tcut health` 会报告实际生效的值。

## 测试

当前测试套件使用标准库 `unittest` 与 Textual 的 `run_test()`。测试构造临时 Trae fixture，从不打开真实
usage database，并覆盖 import/privacy 守卫、增量解析、快照、CLI 输出、TUI 交互和内容存储边界。

最近一次本地运行：`Ran 220 tests ... OK`。

## 维护说明

见 [`docs/maintenance/`](docs/maintenance/README.md)：format 文档区分已观察事实、加密数据，以及索引器
有意不声称的内容；compatibility 矩阵说明支持范围；measurement 文档记录基线。解析器依赖的格式面是
生成的——`tcut format` 打印它，`tcut format --write` 刷新文档里那个块。

## 许可证

MIT。版权所有 (c) 2026 SHADE-glitch。
