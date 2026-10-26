# Trae CN format notes

## Format registry (generated)

The surface below is generated from the registry at the top of `scripts/tcut-sync.py`, so it
cannot describe a field the parser no longer reads. Regenerate it with `tcut format --write` in
the same change as the registry — a hand-copied list is how `schema_version` once became a value
nothing read: written, plausible, and disconnected from the code.

<!-- BEGIN generated: tcut format -->
- **`state.vscdb` keys read** (the literal `LIKE` pattern each is reached through):
  - `prompt_history` → `icube-ai-agent-storage-input-history`
  - `session_agent_map` → `icube_session_agent_map`
  - `agent_definitions` → `currentAgentData%`
  - `model_catalog` → `%_AI.agent.model.model_list_map`
  - `session_selected_model` → `%:AI.agent.model.session_selected_model`
  - `session_list` → `memento/icube-ai-agent-storage`
- **JSON fields read out of a `state.vscdb` blob**: `agent_id`, `consumption_rate`, `context_window_size`, `data`, `default`, `description`, `display_name`, `features`, `fee_model_level`, `inputText`, `list`, `max`, `mode`, `modelId`, `model_type`, `name`, `prompt_max_tokens`, `provider`, `rate`, `sessionId`, `type`
- **Credential fields never read** (a custom-provider entry carries them beside the fields above): `ak`, `sk`, `base_url`, `custom_config`
- **Credit-balance log tag**: `[ICubeUsageService]`
- **`unparsed` reasons**: `session_memory:bad_name`, `session_memory:not_json`, `session_memory:not_object`, `topic:no_match`, `topic:bad_time`, `snapshot:time_unreadable`, `vscdb:open_failed`, `vscdb:read_failed`, `model_map:not_json`, `model_map:shape`, `model_map:group_shape`, `model_map:entry_shape`, `model_map:no_name`, `session_model:not_json`, `session_model:shape`, `session_model:no_model_id`, `mcp:bad_metadata`, `credit_log:read_failed`, `credit_log:bad_timestamp`, `credit_log:event_shape`
<!-- END generated -->

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

## What `sessions` columns can and cannot be NULL (measured)

Re-measured 2026-10-13 on this machine's 49 indexed sessions:

| column | NULL | note |
| --- | ---: | --- |
| `turns`, `toolcalls` | **0** | the writer always stores a number; 25 rows carry a stored **0** because their snapshot repo has no tags |
| `project_key`, `project` | **28** | both NULL together — snapshot-only and session-list-only rows have no workspace key |
| `first_ts`, `last_ts` | **25** | the rows whose position comes only from `created_ts`; every one of them is stamped, so `COALESCE` never yields NULL here |

Two consequences the code has to respect. A dash is owed to `projects` (28 rows have no key
to count, so `0 projects` would be a claim about the world, not about the field), and it is
**not** owed to `turns`/`toolcalls`: a stored 0 there is a number the indexer wrote, and
rendering it `-` would hide the difference between "no turns recorded" and "the snapshot had
no tags". That difference is a measurement question, not a rendering one — see *Snapshot tag
timestamps, measured* above, and the 25 rows it reports as having no measured time.

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
- A parser generation (`PARSER_VERSION`) is stamped in `meta`. When it differs from the stored one, every cursor is dropped once and each source is re-read, so a repaired reader reaches rows an earlier build already indexed; `tcut health` reports a stale index until that sync runs.
- `--full` snapshots existing indexed state, resets the index, and scans again.
- A source record that cannot be parsed increments `unparsed`, keyed by `(reason, source)`; it is never silently treated as valid, and re-reading one file replaces that file's count instead of adding to it.

## Summary

The indexer reads the readable session summaries, topics, memory, snapshot tags, `state.vscdb` and
the installed inventory; the encrypted agent database is not parsed. Project paths prefer the real
path from `workspace.json`. JSONL is read incrementally by byte offset, and an incomplete trailing
line waits for the next sync; other whole-file sources are re-read when their size/mtime changes.
Every input that cannot be parsed lands in `unparsed`.

The model catalog is stored one key per account under `<account>_AI.agent.model.model_list_map`;
measured on this machine it holds 284 rows with only 42 distinct names, so the primary key is
(account, group, name) — keying on the name alone would swallow 242 rows and still look like a clean
sync. The model currently selected for each session lives in
`<account>:AI.agent.model.session_selected_model`, one row per agent label; Trae keeps only the
current value, never a switch history. An entry's `ak`/`sk`/`base_url`/`custom_config` can carry
credentials, so the parser reads a whitelist and none of those fields ever reaches the database.

Token counts do not exist on this machine: the agent database is encrypted (entropy 8.000 bits/byte
over the first 1 MB, zero keyword hits), the WAL frames are ciphertext too, and the logs carry only
the usage endpoint's URL and status code, never a response body. Across all 11,837 files there is no
record shaped like `prompt_tokens`/`rawUsage`, while the same search does find them in CodeBuddy's
transcripts. So this tool shows no tokens and prints `-` where a token number would go.

A snapshot ref names an **annotated tag object**, not a commit: one session repo holds 87 tags, all
of type `tag`, and the `object` line must be peeled to the commit before its time can be read. In
the measured commits `author` and `committer` agreed on 87/87, and the `tagger` line sat about ten
seconds behind the commit, so the commit time is what is stored and the tagger time is the fallback
used only when the commit object cannot be read. A parser that recognised only a `commit ` header
once wrote all 89 turns and all 139 tool calls on this machine with no timestamp while the suite
stayed green — because the fixtures wrote lightweight refs (ref pointing straight at a commit), a
shape the real app never produces. Of the 49 sessions on this machine, 24 carry a measured time and
25 have no measured timestamp at all; and 0 have no time anywhere, because the session id places
all 49 (re-measured 2026-10-12). A windowed count therefore prints `-` only for a row with neither a
`last_ts` nor a `created_ts` — an empty set on this machine, but a rule that must stay: Trae wrote
25 of the 49 rows without a time and could stop writing the id prefix tomorrow. The session id's
first four hex bytes are its creation second; compared against each session's first dated turn the
median delta is 0.0 s and the worst 144 s, and no turn predates that derived second — it is a floor,
not a guess at the middle. It lives in its own column, `sessions.created_ts`, and enters a window
only as the fallback inside `COALESCE(last_ts, created_ts)`; `first_ts`/`last_ts` keep their meaning
as measured activity. Every surface that prints a position earned this way carries a leading `~`
(`db.derived_mark`), because in a table where a derivation looks exactly like a measurement the
derivation will sooner or later be taken for a fact.

`sessions.agent` is written only by the memory records. Measured 2026-10-12: **24 of the 49
sessions carry no agent label at all**, and all 20 sessions in the current 7d window are among
those 24 — the newer a session, the less likely it is to have been written into memory. `agents` is
the **installed inventory** (5 names here), and `q_agents` joins on `s.agent = a.name`, so a whole
window failing to join a single row is decided by the data itself, not by a broken panel. An empty
panel must therefore say which emptiness it is: `none dated in <range>` when the range placed no
session, `no session in this range names an installed agent` when it placed sessions but they lack
the field, and `no agents installed` only when the inventory table itself is empty. The three
empties have three different fixes, and only the first should send you to the range picker.

Whether each `sessions` column can be NULL, re-measured 2026-10-13 over the same 49 rows: `turns`
and `toolcalls` have **not a single NULL** (the writer always stores a number, and 25 of the rows
store a **0** because their snapshot repo has no tags); `project_key` and `project` are **NULL
together on 28 rows** (rows that are snapshot-only, or appear only in the session list, have no
workspace key); `first_ts`/`last_ts` are **NULL on 25 rows**, and all 25 are already caught by
`created_ts`, so `COALESCE` never yields NULL here. Two consequences: `projects` is owed a `-` (28
rows have no key to count, so `0 projects` asserts something about the world, not about the field),
and `turns`/`toolcalls` are **not** — the 0 there is a number the indexer wrote, and rendering it
`-` would flatten "no turns" and "the snapshot had no tags" into one sentence. The latter is a
measurement question, not a rendering one; see *Snapshot tag timestamps, measured* above and the 25
rows it reports as having no measured time.
