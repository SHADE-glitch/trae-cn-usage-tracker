# Compatibility matrix

| Component | Supported | Notes |
| --- | --- | --- |
| Python | 3.11–3.14 | `tomllib` and standard-library `unittest` are used |
| Trae | Trae CN | International Trae is out of scope |
| OS | Linux | Paths follow the Linux Trae CN layout; no network is required |
| Database | SQLite 3 via Python stdlib | Tracker schema version is currently 4 (v2 rebuilt `models` per account and group; v3 added `credit_events`; v4 added `sessions.created_ts`, a *derived* creation second that never overwrites `last_ts`) |
| Headless CLI | stdlib only | `sync`, reports, export, health, backup and restore work without Textual |
| TUI | Textual 8.2.x | `requirements.txt` pins `>=8.2,<9` |
| Content storage | local SQLite, opt-out | `store_content=false` purges prose while retaining metadata |

## Compatibility contract

The readable footprint is treated as an observed format, not a stable public Trae API. The parser is deliberately conservative: malformed input increments `unparsed`, and an encrypted source is skipped rather than guessed. A future Trae release can therefore be measured before its parser is changed.

## 中文说明

支持 Python 3.11–3.14、Linux 和 Trae CN；国际版 Trae 不在范围内。无头 CLI 只依赖标准库，TUI 使用 Textual 8.2.x。Trae 的磁盘格式不是稳定公开 API，解析器遇到格式变化会记录 `unparsed`，不会静默假装成功，也不会猜测加密数据库结构。
