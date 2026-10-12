# Trae CN format notes

## Observed readable sources

The indexer reads these paths below `TCUT_TRAE_CN_HOME` (`~/.trae-cn`) and `TCUT_TRAE_CN_DATA` (`~/.config/Trae CN`):

| Source | What is indexed | Boundary |
| --- | --- | --- |
| `memory/projects/<project>/<YYYYMMDD>/session_memory_<hex>.jsonl` | session id, project, day, intent, outcome, actions, learned | one JSON object per line; incomplete trailing JSON waits for the next run |
| `memory/projects/<project>/<YYYYMMDD>/topics.md` | session id, local timestamp, project key, summary | lines matching the documented header are used; other lines increment `unparsed` |
| `memory/user_profile.md` and `memory/projects/*/project_memory.md` | blank-line-separated memory paragraphs | prose is governed by `store_content` |
| `ModularData/ai-agent/snapshot/<session>/v2/.git` | `before/after-chat-turn-*`, `toolcall-<message>-<call>` IDs and loose-object timestamps | packed commit objects can provide IDs without a timestamp |
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
