# Measurements

The first real-footprint read was performed with a separate database path and did not touch the default store:

```text
sessions=49 projects=2 turns=89 toolcalls=139 prompts=293 agents=5 skills=31 plugins=1 mcp=1
unparsed=0
```

The second incremental run reported zero new records for every file-backed source. This is the baseline for the initial Trae CN footprint; it is not a promise about future Trae versions or future local usage.

## Model axis, measured 2026-10-12

```text
models          284 rows — 7 accounts × 9 agent groups, only 42 distinct names
                251 carry a consumption_rate (0.06 … 1.83)
                258 carry a fee level, 228 a context window
session_models  21 rows over 11 of the 49 sessions (agent 10, solo_agent 11)
tokens          0 — no file on this machine carries a token count
```

Before this change `models` held **42 rows**, because it was keyed on the name and Trae
offers the same name under many accounts and groups. 242 catalog entries were being
discarded by a sync that reported `unparsed=0`.

The token line is a negative measurement, not a gap in the parser: 11,837 files under
`~/.trae-cn` and `~/.config/Trae CN` were walked for quoted token keys and none matched,
while the same walk finds them in CodeBuddy's transcripts. See
[`trae-cn-format.md`](trae-cn-format.md) for the encrypted-store evidence.

## Credit balance samples, measured 2026-10-12

```text
credit_events  10 balance samples + 2 declined fetches, 2026-10-02 … 2026-10-12
balances       1400, 1500, 1600, 1700, 1800, 154.0244, 100, 200, 300, 400
spent          at least 1700 credits (lower bound over the whole series)
```

The integers are daily grants; `154.0244` is the only fractional balance and the only one
that proves consumption happened. Between 1800 and 154.0244 a grant also landed, so the
bound for that interval (1645.9756) is below the real spend by roughly that grant. This is
why the column is called `spent >=` and why no per-request number is shown.

## Reproduce safely

```sh
TCUT_DB=/tmp/tcut-measurement.db tcut sync --full
TCUT_DB=/tmp/tcut-measurement.db tcut stats
TCUT_DB=/tmp/tcut-measurement.db tcut health
```

The explicit path is intentional. Do not run a verification sync against the default database when a throwaway measurement is sufficient.

## 中文说明

首次真实 footprint 读取使用了独立数据库，基线为 49 个 session、2 个 project、89 个 turn、139 个 tool-call ID、293 个 prompt、5 个 agent、31 个 skill、1 个 plugin、1 个 MCP，`unparsed=0`。第二次增量读取所有文件型 source 都是 0 条新增。该数字只是当前本地数据的基线，不是未来版本或未来使用量的承诺。

2026-10-12 的模型轴实测：模型目录 284 条（只有 42 个不同名字，分属 7 个账号、9 个分组），其中 251 条带 `consumption_rate`；会话模型选择 21 条，覆盖 49 个会话里的 11 个。改动前 `models` 只有 42 行——按名字做主键吞掉了 242 条，而 `unparsed` 仍是 0。token 一行都没有：全盘 11,837 个文件按带引号的 token 键搜过，零命中，同样的搜法在 CodeBuddy 转录里能命中。
