# Trae CN format notes

## Observed readable sources

The indexer reads these paths below `TCUT_TRAE_CN_HOME` (`~/.trae-cn`) and `TCUT_TRAE_CN_DATA` (`~/.config/Trae CN`):

| Source | What is indexed | Boundary |
| --- | --- | --- |
| `memory/projects/<project>/<YYYYMMDD>/session_memory_<hex>.jsonl` | session id, project, day, intent, outcome, actions, learned | one JSON object per line; incomplete trailing JSON waits for the next run |
| `memory/projects/<project>/<YYYYMMDD>/topics.md` | session id, local timestamp, project key, summary | lines matching the documented header are used; other lines increment `unparsed` |
| `memory/user_profile.md` and `memory/projects/*/project_memory.md` | blank-line-separated memory paragraphs | prose is governed by `store_content` |
| `ModularData/ai-agent/snapshot/<session>/v2/.git` | `before/after-chat-turn-*`, `toolcall-<message>-<call>` IDs, plus the time of the commit each tag points at | the refs name **annotated tag objects**, not commits: the tag is peeled to its `object` commit and that commit's time is stored. A packed or missing object leaves the row undated and increments `unparsed` as `snapshot:time_unreadable` |
| `User/workspaceStorage/*/state.vscdb` | prompt history, session→agent map, agent definitions, models | read-only SQLite open; workspace folder comes from `workspace.json` |
| `state.vscdb` key `<uid>_AI.agent.model.model_list_map` | the model catalog: account, agent group, name, display name, provider, model type, fee level, consumption rate, context window, prompt limit | one key per account (`undefined` is a real prefix); only the fields listed are read |
| `state.vscdb` key `<uid>:AI.agent.model.session_selected_model` | per-session model selection, one row per agent label (`agent`, `solo_agent`), plus `mode` | Trae stores the *current* selection only — a switch history is not recoverable |
| `logs/<session>/window*/renderer.log`, `logs/<session>/main.log` | the credit balance Trae logs at app start (`[ICubeUsageService] … {"generation":…,"remaining":…}`) | byte-offset cursor; only the number, its timestamp and its generation are stored |
| `skills`, `builtin_skills`, `plugins`, `mcps` | installed inventory | manifests are best-effort |

## Credit balance is a level, not a measurement

Trae writes one balance line per app start, so `credit_events` holds *samples* — sparse,
and interrupted by grants that push the balance up. `q_credits` therefore derives
`spent_at_least = max(0, previous - this)`: a fall is only part of what was consumed
between samples, so it is a **lower bound**, computed at query time and never stored as if
Trae had measured it. A balance sample with no number (`fetchCreditsUsageInfo skipped`) is
kept as `kind='skipped'` so an empty panel can be told apart from a declined fetch, and it
stays out of the series rather than becoming a `0`.

The bound is computed over the whole series *before* a time window filters it, so the
first row inside a window still reports the fall from the last sample before the window;
a windowed view would otherwise show zero spend through a period that plainly contains it.

The log line around the number is Trae's prose; only the four fields are stored. An
`[ICubeUsageService]` line whose payload matches neither shape increments
`credit_log:event_shape` — a change in what the service writes has to be visible.

## Credential fields are never read

A catalog entry is a flat bag of configuration and, for a custom provider, it carries
`ak`, `sk`, `base_url` and `custom_config` beside the fields above. The indexer reads a
whitelist and nothing else, so a credential cannot reach `usage.db` by omission.
`test_sync.py::test_a_model_entrys_credentials_are_never_stored` searches every value of
every table for sentinels planted in those fields.

## Project-key decoding

Trae encodes a workspace path by replacing non-alphanumeric characters with `-` and appending a `--p2-<id>` suffix. Decoding is necessarily lossy when a real path segment contains `-`; `workspace.json` is authoritative when available. The indexer matches the normalized key to the workspace folder and replaces the display path with the real folder.

## Snapshot tag timestamps, measured

The snapshot refs are **annotated tags**: the ref names a `tag` object whose `object`
line points at the commit. One session repo, 87 tag refs — every one of them type `tag`,
none a bare commit. Inside those commits `author` and `committer` agreed on 87/87, and the
`tagger` line sat about ten seconds behind the commit it tagged, so the commit is the time
stored and the tagger line is used only when the commit object cannot be read.

This matters because a parser that recognised only a `commit ` header returned `None` for
**all 89 turn rows and all 139 toolcall rows** on this machine while its test suite stayed
green — the fixtures had written lightweight refs (ref → commit), which is a shape the real
app never produces. `test_sync.py` now builds both shapes and asserts each result.

Coverage on this footprint (49 sessions indexed, re-measured 2026-10-12): 24 carry a
measured timestamp, 25 have none — and 0 have no time anywhere, because the session id
places all 49 (below). A windowed count therefore reads `-` only for a row with neither a
measured `last_ts` nor a derivable `created_ts`; that is a rule with no population on this
machine, which is exactly why it must stay in the code: Trae wrote 25 of 49 rows this way,
and it can stop writing the id prefix tomorrow.

The session id's first four hex bytes are its creation second. Re-measured against each
session's first *dated turn*: median delta 0.0 s, worst 144 s, and no turn anywhere
predates the derived second — the derivation is a floor, not a guess at the middle. It is
stored in its own column, `sessions.created_ts`, and reaches a window only as the fallback
inside `COALESCE(last_ts, created_ts)`. `first_ts` and `last_ts` stay what they always
meant — measured activity — and every surface that prints a position earned this way marks
it with a leading `~` (`db.derived_mark`), because a table where a derivation looks exactly
like a measurement quietly upgrades it into a fact.

## Agent labels are missing on most sessions

`sessions.agent` is written only by the memory records. Measured 2026-10-12 on this
footprint: **24 of 49 sessions carry no agent at all**, and every one of the 20 sessions in
the current 7d window is one of those 24 — the recent sessions are the ones Trae summarizes
least. `agents` is the *installed* inventory (5 names here), so `q_agents` joining
`s.agent = a.name` legitimately has nothing to join for a whole window.

That is a fact about the source, not a bug in the panel, and it is why an empty Top agents
must not be phrased as a date problem. A blank panel names its own cause: `none dated in
<range>` when the range placed no session, `no session in this range names an installed
agent` when it placed sessions with no label, `no agents installed` when the inventory table
is empty. The three have three different fixes, and only the first one is the range picker.

## Encrypted boundary, measured

`ModularData/ai-agent/database.db` is not treated as SQLite. It is encrypted, written by
Trae's native agent library, and this tool does not reverse-engineer it. The claim is a
measurement, not an assumption — re-run it before believing any new token parser:

* the file does not begin with `SQLite format 3\0`; its first 16 bytes are
  `4231e6f7e377d03a0bbaf7ef94d7d270`;
* entropy of the first 1 MB is **8.000 bits/byte** with all 256 byte values present, and
  `SELECT`, `CREATE TABLE`, `token`, `usage`, `model` occur **zero** times there;
* `database.db-wal` *does* have genuine SQLite WAL framing (magic `377f0682`, 1225
  frames), but each frame's payload is encrypted (entropy 7.955, no `SQLite format 3`
  anywhere in the file, zero keyword hits) — it is a page codec over stock WAL, not an
  open book;
* the request bodies that would contain the counts are never written: `main.log` records
  `api.trae.cn/trae/api/v1/pay/query_user_usage_group_by_session` and
  `/v2/pay/ide_user_ent_usage` with a status line and nothing else.

A walk of 11,837 files under `~/.trae-cn` and `~/.config/Trae CN` (plus the three files
over 60 MB individually) found **zero** files containing quoted token keys
(`prompt_tokens`, `completion_tokens`, `total_tokens`, `cached_tokens`, `rawUsage`). The
same search finds them in CodeBuddy's transcripts, so the method works; Trae simply keeps
this data in the encrypted store.

**Consequence: per-request token counts are not recoverable from this machine.** The
tracker records what survives the boundary — the model selected per session and the
catalog's own `consumption_rate` — and says `-` where a token number would go. A future
Trae release can be re-measured the same way; nothing here should be parsed by guessing.

## Incremental semantics

- JSONL summaries use a byte cursor. Complete lines are consumed; a non-parseable trailing segment remains at the cursor for the next run.
- Whole-file sources use `(size, mtime)` and are replaced when changed.
- Snapshot repositories use a tag-store mtime fingerprint.
- `--full` snapshots existing indexed state, resets the index, and scans again.
- A source record that cannot be parsed increments `unparsed`; it is never silently treated as valid.

## 中文说明

索引器读取可读的 session summary、topics、memory、snapshot tag、`state.vscdb` 和安装清单；加密的 agent 数据库不解析。项目路径优先使用 `workspace.json` 的真实路径。JSONL 使用字节 offset 增量读取，未完成的尾行留给下一次 sync；其他整体文件按 size/mtime 变化重新读取。所有无法解析的输入都会进入 `unparsed`。

模型目录以 `<账号>_AI.agent.model.model_list_map` 每账号一个键存着，本机实测 284 条、只有 42 个不同名字，所以主键是（账号、分组、名字）；只按名字存会把 242 条吞掉，而且看起来像一次干净的同步。每个会话当前选的模型在 `<账号>:AI.agent.model.session_selected_model` 里，按 agent 标签一行一条，Trae 只留当前值、不留切换历史。条目里的 `ak`/`sk`/`base_url`/`custom_config` 可能带凭据，解析器按白名单读取，这些字段一个都不进库。

token 数在这台机器上不存在：agent 库是加密的（首 1 MB 熵 8.000 bit/byte、零关键字），WAL 帧同样是密文，日志里只有 usage 接口的 URL 和状态码、没有响应体。全盘 11,837 个文件里没有任何 `prompt_tokens`/`rawUsage` 形态的记录，而同样的搜法在 CodeBuddy 转录里能搜到。所以本工具不显示 token，需要的位置显示 `-`。

snapshot 的 ref 指向的是**附注 tag 对象**，不是 commit：一个会话仓 87 个 tag，全部是 `tag` 类型，要靠 `object` 行剥到 commit 再取时间。实测 commit 里 `author` 与 `committer` 87/87 相同，`tagger` 行只比 commit 晚约十秒，所以入库的是 commit 时间，只有 commit 对象读不到时才退回 tagger 时间。只认 `commit ` 头的解析器曾在这台机器上把 89 条 turn、139 条 toolcall 全部写成无时间戳，而测试当时是绿的——因为 fixture 写的是轻量 ref（ref 直指 commit），那正是真实程序不会产生的形状。本机 49 个会话里 24 个带着实测时间，25 个没有任何实测时间戳；而"任何地方都没有时间"的是 0 个，因为会话 id 能给全部 49 个定位（2026-10-12 重测）。窗口计数因此只对既无 `last_ts` 又无 `created_ts` 的行显示 `-`——这台机器上这个集合是空的，但规则必须留着：Trae 曾把 49 个里的 25 个写成没有时间，它明天就可以不再写 id 前缀。会话 id 前四个十六进制字节是创建秒，与各会话首条带时间戳的 turn 相比中位差 0.0 秒、最大 144 秒，且没有任何 turn 早于这个推导秒——它是下界，不是对中间的猜测。它单独存在 `sessions.created_ts`，只以 `COALESCE(last_ts, created_ts)` 的兜底形式进入窗口；`first_ts`/`last_ts` 的含义不变，仍是实测活动。凡打印这种推导时间的地方都带一个前导 `~`（`db.derived_mark`），因为在一张推导与实测长得一模一样的表里，推导迟早会被当成事实。

`sessions.agent` 只由 memory 记录写入。2026-10-12 实测：49 个会话里 **24 个根本没有 agent 标签**，而当前 7d 窗口里那 20 个全是这 24 个之一——越新的会话越不容易被写进 memory。`agents` 是**安装清单**（本机 5 个名字），`q_agents` 靠 `s.agent = a.name` 连接，所以整个窗口一行都连不上是数据本身决定的，不是面板坏了。空面板因此必须说清自己空在哪：范围里没放下任何会话是 `none dated in <范围>`，放下了但缺那个字段是 `no session in this range names an installed agent`，清单表本身为空才是 `no agents installed`。三种空对应三种修法，只有第一种该去动范围选择器。
