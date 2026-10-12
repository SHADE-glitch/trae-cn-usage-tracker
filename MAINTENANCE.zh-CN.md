# MAINTENANCE.zh-CN.md — trae-cn-usage-tracker

流程文件。这是一份**路由表**：长文维护资产放在
[`docs/maintenance/README.md`](docs/maintenance/README.md) 下，仓库内的工作规则放在
[`AGENTS.md`](AGENTS.md)。不要在这里复制它们的表格——被复制的那份事实才是会漂移的东西。

唯一真正要紧的维护风险：**Trae 改了盘上的格式**。字段改名会被读成 `NULL`，来源改名会静默地无人
认领，面板清空，`tcut sync` 照样打印 "done"，CI 照样绿。本工具依赖的格式面登记在
`scripts/tcut-sync.py` 顶部，并由它渲染进
[`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md)——用
`tcut format --write` 重新生成，并且把登记表和处理函数**放在同一个 commit 里**改。

第二个风险是这个工具特有的，而且很容易搞错：agent 存储是**加密**的，所以 Trae 自有接口上报的 token
数并不在盘上。每一个 token 位置都显示 `-`；这个 `-` 是实测结论，不是一个等着被填上的空。永远不要由
credit 采样推算 token 数，也永远不要让一个缺失的数字变成 `0`。实测边界写在
[`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md) § Encrypted boundary。

## 验证档位
- **L0** —— `python3 -m unittest discover -s scripts/tests`（临时数据库，不碰主机）。有两套需要
  `textual`：`test_tui.py` 与 `test_config.py`，所以请用 `.venv/bin/python` 跑。
- **L1** —— 仓库外的一次性库，喂真实 footprint：
  `TCUT_DB=/tmp/tcut-check.db python3 scripts/tcut-sync.py`。解析器的改动在这里证明；同步报告里
  **每张表**的行数，就是让你没动过的那张表的退化保持可见的办法。
- **L2** —— 真实的 `~/.trae-cn` / `~/.config/Trae CN` footprint 与真实的
  `~/.local/share/trae-cn-usage-tracker/usage.db`。需要机主点头；破坏性步骤先快照
  （`tcut sync --full` 会自动做）。

## 产出这些数字的命令
```bash
find ~/.trae-cn ~/.config/Trae\ CN -type f | wc -l    # 源文件数
TCUT_DB=/tmp/tcut-check.db tcut sync --quiet          # 重建索引；打印每表行数
TCUT_DB=/tmp/tcut-check.db tcut health                # 设置、各表计数、未认领原因
TCUT_DB=/tmp/tcut-check.db tcut models                # 模型目录：账号、分组、计价倍率
```

面板空了时第一个要读的是 `tcut health`：`unparsed` 里出现点名某个来源的原因，说明格式动了；某张表
归零而邻居都在涨，说明字段被改名了。

## CI
`.github/workflows/ci.yml` 在 Python 3.11 / 3.14 矩阵上跑离线层——即声明的下限，与本机实测通过的
最高版本。它不是你开发用的解释器（`install.sh` 建的是一个 venv），一次绿的运行对它没跑过的版本
什么都不说明。

## 资产
| 文档 | 什么时候读 |
|---|---|
| [`trae-cn-format.md`](docs/maintenance/trae-cn-format.md) | Trae 发了新版本，或某个面板不再显示它以前显示的东西 |
| [`compatibility.md`](docs/maintenance/compatibility.md) | 要决定声明支持什么，或某个版本号需要更新时 |
| [`measurements.md`](docs/maintenance/measurements.md) | 要重述某个体积、耗时、行数，或模型轴的分布时 |

三份文档里的数字都是**一台机器、某一天**量出来的。Trae 的 footprint 是活的，就在你测量它的这次会话里
继续增长——请重新测量，而不是把一个数字往下抄。
