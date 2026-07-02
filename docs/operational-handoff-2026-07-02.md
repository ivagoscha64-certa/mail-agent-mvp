# Mail Agent MVP Operational Handoff - 2026-07-02

## Status

The MVP is healthy for read-only local operation.

- Repository branch: `master`.
- Configured account: `iva196464@gmail.com`.
- Mode: `read_only`.
- Backend/provider: Gmail API / `gmail`.
- SQLite DB is present and readable at `E:\AI\mail-agent-mvp\data\mail-agent.sqlite3`.
- Schema check: `compatible=true`, `metadata_present=true`, `detected_version=1`.
- Operational review: `status=ok`, `risk=low`.
- Windows scheduled task: `MailAgentNotifyNew`, registered, `Ready`, last result `0`.

## Recent Commits

- `0618323 fix(mail): normalize message dates for local stats`
- `7174091 fix(mail): retry transient Gmail API failures`
- `35c01b3 fix(scheduler): emit ISO status timestamps`
- `0a88d0d ci: add pytest workflow`
- `7f98341 feat(db): record explicit schema version`
- `8adcc23 chore(config): derive project paths from repository root`

## Closed Audit Risks

- Local message date stats now normalize stored message dates.
- Transient Gmail API failures are retried.
- Scheduler status timestamps are emitted as ISO values.
- CI runs pytest.
- SQLite schema version is explicit in `schema_metadata`.
- Project paths are derived from the repository root instead of fragile process paths.
- `.env` explicitly sets `GMAIL_ACCOUNT_EMAIL=iva196464@gmail.com`.
- Local SQLite DB has been migrated to schema version `1`.

## Live Canary

Controlled live canary was run before this handoff with:

```powershell
.\.venv\Scripts\python.exe -m mail_agent notify-new --limit 25
```

The canary completed successfully with `new=0`, `existing=25`, and `notified=0`.
Telegram was not called because there were no new pending important messages.

Read-only handoff diagnostics later observed newer scheduled `notify-new` runs.
The latest observed run was `id=101`, `status=completed`, `new=0`,
`existing=25`, `notified=0`, finished at `2026-07-01T23:24:07+00:00`.

Historical failed run `id=94` for account `your.email@example.com` is retained
as history and should not be edited or deleted.

## Daily Diagnostics

Use these commands for routine read-only checks:

```powershell
.\.venv\Scripts\python.exe -m mail_agent health --skip-scheduler --json
.\.venv\Scripts\python.exe -m mail_agent review --limit 10 --sender-limit 10 --json
.\.venv\Scripts\python.exe -m mail_agent runs --limit 10 --json
.\scripts\Register-NotifyNewTask.ps1 -Status -Json
```

Expected healthy signals:

- `account` / `config.account` is `iva196464@gmail.com`.
- `mode` / `config.mode` is `read_only`.
- DB schema is compatible with metadata present and detected version `1`.
- Latest `notify-new` run is `completed`.
- Scheduler is registered and `Ready`.
- Review reports `status=ok` and `risk=low`.

## Backup

SQLite backup before the schema/local ops work:

```text
E:\AI\_tmp\mail-agent.sqlite3.bak-20260702-082411
```

Do not delete this backup during routine maintenance.

## Read-Only Limits

The project is intentionally constrained to read-only mail operations:

- no email sending;
- no email deletion;
- no unsubscribe actions;
- no moving messages to spam;
- no moving messages between folders.

Do not run the following commands without explicit operational intent:

- `notify-new`
- `check-mail`
- `send-summary`
- `bot`
- `auth-gmail`

Do not modify `secrets`, `.env`, local DB contents, backup files, or historical
`run_log` rows as part of routine handoff checks.
