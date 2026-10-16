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

## Summary

The first real-footprint read used a separate database; the baseline is 49 sessions, 2 projects,
89 turns, 139 tool-call IDs, 293 prompts, 5 agents, 31 skills, 1 plugin and 1 MCP, with
`unparsed=0`. The second, incremental read added zero records for every file-backed source. These
numbers are a baseline for the current local data only — not a promise about future versions or
future usage.

The model axis, measured 2026-10-12: the model catalog holds 284 rows (only 42 distinct names,
across 7 accounts and 9 groups), of which 251 carry a `consumption_rate`; session model selections
number 21, covering 11 of the 49 sessions. Before the change `models` held only 42 rows — keying on
the name swallowed 242 of them while `unparsed` stayed 0. There is not one token row: all 11,837
files were searched for quoted token keys with zero hits, while the same search does match in
CodeBuddy's transcripts.
