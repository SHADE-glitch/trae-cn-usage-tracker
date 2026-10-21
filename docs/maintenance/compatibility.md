# Compatibility matrix

| Component | Supported | Notes |
| --- | --- | --- |
| Python | 3.11–3.14 | `tomllib` and standard-library `unittest` are used |
| Trae | Trae CN | International Trae is out of scope |
| OS | Linux | Paths follow the Linux Trae CN layout; no network is required |
| Database | SQLite 3 via Python stdlib | Tracker schema version is currently 5 (v2 rebuilt `models` per account and group; v3 added `credit_events`; v4 added `sessions.created_ts`, a *derived* creation second that never overwrites `last_ts`; v5 decoded each selection into `model`/`provider`/`third_party` and added the `credit_intervals`/`credit_alloc` estimate) |
| Headless CLI | stdlib only | `sync`, reports, export, health, backup and restore work without Textual |
| TUI | Textual 8.2.x | `requirements.txt` pins `>=8.2,<9` |
| Content storage | local SQLite, opt-out | `store_content=false` purges prose while retaining metadata |
| CI | Python 3.11 / 3.14 | `.github/workflows/ci.yml` runs the offline suite on both ends of the declared range |

## Compatibility contract

The readable footprint is treated as an observed format, not a stable public Trae API. The parser is deliberately conservative: malformed input increments `unparsed`, and an encrypted source is skipped rather than guessed. A future Trae release can therefore be measured before its parser is changed.

## Summary

Supports Python 3.11–3.14, Linux and Trae CN; international Trae is out of scope. The
headless CLI depends only on the standard library, and the TUI uses Textual 8.2.x. Trae's
on-disk format is not a stable public API, so the parser records `unparsed` when the format
changes rather than silently pretending success, and it never guesses the schema of the
encrypted database.
