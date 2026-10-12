# MAINTENANCE.md — trae-cn-usage-tracker

Procedure file. This is a **router**: the long-form maintenance assets live under
[`docs/maintenance/README.md`](docs/maintenance/README.md), and the rules for working in this
repository live in [`AGENTS.md`](AGENTS.md). Do not duplicate their tables here — a duplicated fact
is the thing that drifts.

The one maintenance risk that matters: **Trae changing its on-disk format**. A renamed field reads
as `NULL`, a renamed source is simply unclaimed, the panels empty out, `tcut sync` prints "done",
and CI stays green. The format surface this tool depends on is registered at the top of
`scripts/tcut-sync.py` and rendered into
[`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md) — regenerate it with
`tcut format --write` and change the registry and the handler **in the same commit**.

The second risk is specific to this tool and easy to get wrong: the agent store is **encrypted**, so
the token counts Trae's own endpoints report are not on disk. Every token position renders `-`; the
`-` is a measurement, not a gap to fill in. Never convert a credit sample into a token count, and
never let a missing number become a `0`. The measured boundary is in
[`docs/maintenance/trae-cn-format.md`](docs/maintenance/trae-cn-format.md) § Encrypted boundary.

## Verification tiers
- **L0** — `python3 -m unittest discover -s scripts/tests` (temp database, no host). Two suites need
  `textual`: `test_tui.py` and `test_config.py`; run it with `.venv/bin/python`.
- **L1** — a throwaway store outside the repository, fed by the real footprint:
  `TCUT_DB=/tmp/tcut-check.db python3 scripts/tcut-sync.py`. This is where parser changes are proved,
  and the sync report's per-table row counts are how a regression in a table you did not touch stays
  visible.
- **L2** — the real `~/.trae-cn` / `~/.config/Trae CN` footprint and the real
  `~/.local/share/trae-cn-usage-tracker/usage.db`. Needs the owner's go-ahead; a destructive step
  takes a snapshot first (`tcut sync --full` does this automatically).

## Commands that produce the numbers
```bash
find ~/.trae-cn ~/.config/Trae\ CN -type f | wc -l    # source file count
TCUT_DB=/tmp/tcut-check.db tcut sync --quiet          # re-index; prints rows per table
TCUT_DB=/tmp/tcut-check.db tcut health                # settings, table counts, unparsed reasons
TCUT_DB=/tmp/tcut-check.db tcut models                # the catalog: account, group, rate
```

`tcut health` is the first thing to read when a panel goes empty: an `unparsed` reason naming a
source means the format moved, and a table at zero while its neighbours grew means a field was
renamed.

## CI
`.github/workflows/ci.yml` runs the offline suite on a Python 3.11 / 3.14 matrix — the declared floor
and the highest version measured green here. It is not the interpreter you develop on (`install.sh`
builds a venv), and a green run says nothing about a version it did not run.

## Assets
| Document | Read it when |
|---|---|
| [`trae-cn-format.md`](docs/maintenance/trae-cn-format.md) | Trae shipped a new version, or a panel shows nothing it used to show |
| [`compatibility.md`](docs/maintenance/compatibility.md) | Choosing what to claim is supported, or a version string needs updating |
| [`measurements.md`](docs/maintenance/measurements.md) | Restating a size, a timing, a row count, or the model-axis split |

All three carry numbers measured on one machine on one day. Trae's footprint is live and grows during
the session you are measuring it in — re-measure rather than copying a number forward.
