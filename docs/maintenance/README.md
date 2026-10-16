# Maintenance notes

Everything here exists because **Trae CN changing its on-disk format is the main maintenance risk**
for this tool: a renamed field or source produces no error — the panels empty out, `tcut sync`
prints "done", and CI stays green.

| Document | Read it when |
|---|---|
| [`trae-cn-format.md`](trae-cn-format.md) | Trae shipped a new version, or a panel shows nothing it used to show |
| [`compatibility.md`](compatibility.md) | Choosing what to claim is supported, or a version string needs updating |
| [`measurements.md`](measurements.md) | Judging a size or performance change, or comparing against the recorded baseline |

These three are English-only on purpose: they carry commands and readings, not prose a reader
needs in two languages. The bilingual pair of documents is `README.md` / `README.zh-CN.md` and
`MAINTENANCE.md` / `MAINTENANCE.zh-CN.md`.

Three standing checks cover this area — all part of `python3 -m unittest discover -s scripts/tests`:

- `test_format_registry.py` — the parser and the registry at the top of `scripts/tcut-sync.py` agree,
  in both directions (nothing read unregistered, nothing registered unread, no inlined key literal).
- `test_maintenance_docs.py` — the generated block in `trae-cn-format.md` still equals `tcut format`
  output, and the CI matrix the docs state is the one the workflow runs. Edit the registry, run
  `tcut format --write`.
- `test_privacy.py` — nothing is read that could leave the machine, and no free-text value lands in
  any column of any table.
