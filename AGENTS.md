# AGENTS.md — Trae CN Usage Tracker

## Scope

This repository is a passive reader for Trae CN only. Do not broaden it to international Trae or to CodeBuddy transcripts without an explicit design decision.

本仓库只被动读取 Trae CN。未经明确设计决策，不要扩展到国际版 Trae 或 CodeBuddy transcript。

## Hard rules

- Read Trae's directories; never write into them.
- Keep the tracker database local. No network, upload, telemetry, or subprocess path in production scripts.
- Tests use throwaway databases under temporary directories. They must never open `~/.local/share/trae-cn-usage-tracker/usage.db`; `_hermetic.py` enforces this with an audit hook.
- Treat encrypted `ModularData/ai-agent/database.db` as unreadable. Do not guess its schema or claim tool names/tokens that are not in plaintext sources. The absence of token counts on disk is a measurement (8.000 bits/byte, zero keyword hits, 11,837 files walked), recorded in `docs/maintenance/trae-cn-format.md` — re-measure before believing any claim that a new source has them.
- From a model catalog entry, read only the documented whitelist. `ak`, `sk`, `base_url` and `custom_config` can carry credentials for a custom endpoint and must never be stored; `test_sync.py::VscdbTest.test_a_model_entrys_credentials_are_never_stored` scans every value of every table to prove it.
- A credit balance is a *level* sampled at app start. `spent >=` is a lower bound derived at query time; never store or print it as measured consumption, and never turn a `skipped` fetch into a `0`.
- `models` is keyed by (account, group_name, name), never by name: one real footprint holds 284 entries under 42 distinct names, and a name-only key discards 242 of them while still reporting `unparsed=0`.
- `store_content = true` is an intentional project decision: session summaries, prompt history, and memory prose may be stored in the local SQLite database. `store_content = false` must purge that prose while preserving metadata.
- Commit messages, when this standalone repository gains history, are English.

## Verification

Run:

```sh
python3 -m unittest discover -s scripts/tests
python3 -m pyflakes scripts/*.py
```

The first command must finish with `OK`; the second must be silent. A real-footprint read-only check may use `TCUT_DB=/tmp/tcut-check.db tcut sync --quiet`, never the default database.

## Change discipline

Keep parser assumptions in `docs/maintenance/trae-cn-format.md`. If a Trae file shape changes, update the format note, the fixture test, and the unparsed reason that makes the change observable.
