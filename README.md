# Mail Agent MVP

Read-only MVP for a personal mail agent: Python, SQLite, Telegram bot, Gmail API, and IMAP fallback.

Current first test account:

```text
iva196464@gmail.com
```

The starter mode is strictly read-only:

- no email sending;
- no email deletion;
- no unsubscribe actions;
- no moving messages to spam;
- no moving messages between folders.

## Structure

- `src/mail_agent/config.py` - environment-based configuration.
- `src/mail_agent/safety.py` - central read-only safety policy.
- `src/mail_agent/mail/gmail_api.py` - read-only Gmail API connector.
- `src/mail_agent/mail/imap_client.py` - read-only IMAP fallback connector.
- `src/mail_agent/db.py` and `src/mail_agent/schema.sql` - SQLite storage.
- `src/mail_agent/telegram_bot.py` - basic Telegram commands.
- `src/mail_agent/classifier.py` - first rule-based classifications.
- `src/mail_agent/audit.py` - action audit log.

## Quick Start

```powershell
cd E:\AI\mail-agent-mvp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
Copy-Item .env.example .env
mail-agent init-db
mail-agent status
```

For Gmail API, put the OAuth client JSON here:

```text
E:\AI\mail-agent-mvp\secrets\gmail-credentials.json
```

Then authorize once:

```powershell
mail-agent auth-gmail
```

After authorization, read recent mail:

```powershell
mail-agent check-mail --limit 10
```

Telegram bot starts only when both `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_ALLOWED_CHAT_ID` are filled. This is deny-by-default: an empty
allowed chat id never authorizes every Telegram chat.

```powershell
mail-agent bot
```

To send a one-time summary:

```powershell
mail-agent send-summary --limit 10
```

To read recent Gmail messages and send Telegram only for new important messages:

```powershell
mail-agent notify-new --limit 25
```

`notify-new` is idempotent: already stored Gmail messages are skipped, and Telegram
notifications are recorded in SQLite so old important messages are not sent again.

If `TELEGRAM_ALLOWED_CHAT_ID` is not known yet:

1. Create a bot with Telegram `@BotFather`.
2. Put the token into `.env` as `TELEGRAM_BOT_TOKEN`.
3. Send `/start` to the bot in Telegram.
4. Run:

```powershell
mail-agent telegram-chat-id
```

5. Put the printed `chat_id` into `.env` as `TELEGRAM_ALLOWED_CHAT_ID`.

## Windows Task Scheduler

The project includes a safe helper script for scheduling the existing read-only
notification command:

```powershell
cd E:\AI\mail-agent-mvp
.\scripts\Register-NotifyNewTask.ps1
```

By default the script is a dry run. It checks the project path, virtualenv
Python, and `MAIL_AGENT_MODE`, then prints the Task Scheduler action without
creating anything:

```powershell
.\.venv\Scripts\python.exe -m mail_agent notify-new --limit 25
```

To create or update the scheduled task explicitly:

```powershell
.\scripts\Register-NotifyNewTask.ps1 -Register
```

The default task name is `MailAgentNotifyNew`, and the default interval is every
10 minutes. To use another interval:

```powershell
.\scripts\Register-NotifyNewTask.ps1 -Register -EveryMinutes 30
```

To inspect or disable the schedule:

```powershell
.\scripts\Register-NotifyNewTask.ps1 -Status
.\scripts\Register-NotifyNewTask.ps1 -Unregister
```

For local monitors or scripts, task status can also be printed as JSON:

```powershell
.\scripts\Register-NotifyNewTask.ps1 -Status -Json
```

The scheduled task only runs `notify-new`. It does not add email sending,
deletion, moving, spam, or unsubscribe actions.

Every `notify-new` run appends a JSONL result record here:

```text
E:\AI\mail-agent-mvp\data\notify-new-runs.jsonl
```

The same run result is also stored in SQLite table `run_log`, including:

- `started_at` and `finished_at`;
- `new_count`, `existing_count`, and `notified_count`;
- `status` as `completed` or `failed`;
- `error_phase`, `error_type`, and `error` for Gmail or Telegram failures.

To inspect the latest scheduled-run health:

```powershell
mail-agent status
```

`status` prints the latest `notify-new` run and the latest successful
`notify-new` run when available. It is diagnostic/read-only: it does not call
Gmail or Telegram and does not create the SQLite DB when the DB is missing.

To inspect recent `notify-new` run history from local SQLite only:

```powershell
mail-agent runs --limit 10
```

For local monitors or scripts, the same command can print JSON:

```powershell
mail-agent runs --limit 10 --json
```

To inspect local operational health in one read-only command:

```powershell
mail-agent health
```

`health` reads local SQLite counts, recent `notify-new` runs, and Windows Task
Scheduler status. It does not call Gmail or Telegram, and it does not create or
update the scheduled task. It reports missing, empty, old, or corrupt local DBs
as diagnostics instead of creating or migrating them.

For local monitors or scripts:

```powershell
mail-agent health --limit 5 --json
```

To skip the Task Scheduler query and read only SQLite/config state:

```powershell
mail-agent health --skip-scheduler
```

## Local Read-Only Web Panel

To inspect local agent state in a browser, start the local web panel:

```powershell
mail-agent web
```

By default it listens on:

```text
http://127.0.0.1:8765
```

The host and port can be changed for local diagnostics:

```powershell
mail-agent web --host 127.0.0.1 --port 8765
```

For safety, `mail-agent web` refuses non-loopback bind hosts such as `0.0.0.0`
unless you explicitly allow network exposure:

```powershell
mail-agent web --host 0.0.0.0 --allow-non-loopback
```

Use that opt-in only on a trusted network. The panel exposes local diagnostic
state and is intended to stay bound to `127.0.0.1` for normal use.

The web panel is diagnostic/read-only. It reads local configuration and local
SQLite state only. It does not call Gmail, does not send Telegram messages, does
not query or modify Windows Task Scheduler, and does not create or migrate the
SQLite DB during diagnostic reads. SQLite is opened in read-only mode for
diagnostic queries.

The panel exposes only `GET` endpoints:

- `GET /` - dashboard with local health, latest `notify-new` status, recent
  runs, and run log event filters.
- `GET /audit` - audit events and message statistics page with GET filters.
  Its audit and statistics forms preserve the selected filters in the query
  string when either form is applied.
- `GET /api/health?limit=` - JSON local health payload. `limit` controls recent
  run count and defaults to `10`.
- `GET /api/runs?limit=` - JSON recent `notify-new` runs from local SQLite.
  `limit` defaults to `10`.
- `GET /api/audit-events?limit=&action=&status=&account=` - JSON audit events.
  `limit` defaults to `25`; `action`, `status`, and `account` are exact-match
  filters.
- `GET /api/message-stats?sender_limit=&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`
  - JSON message counts by day and top senders. `sender_limit` controls top
  sender count and defaults to `10`; `limit` is still accepted as a
  backward-compatible alias when `sender_limit` is omitted. Dates are inclusive
  ISO date filters.
- `GET /api/run-log-events?limit=&command=&status=&finished_from=YYYY-MM-DD&finished_to=YYYY-MM-DD`
  - JSON run log events across recorded commands. `limit` defaults to `10`;
  `command` and `status` are exact-match filters; `finished_from` and
  `finished_to` are inclusive ISO date filters based on `finished_at`.
- `GET /favicon.ico` - empty `204 No Content` response to keep browser smoke
  checks free of favicon 404 noise.

Invalid `limit` or `sender_limit` values, invalid dates, or date ranges where
the start is after the end return HTTP 400 JSON errors. Missing DBs are reported
as diagnostics: JSON responses include `exists: false`, `readable: false`, and
empty result lists; the missing DB file and parent directory are not created by
these reads.

### Local Web JSON Contract

All JSON endpoints are diagnostic `GET` endpoints. They read local config and
SQLite only, skip Scheduler checks, do not call Gmail or Telegram, and return
HTTP 400 with `{"error": "..."}` for invalid query parameters.

- `GET /api/health?limit=`
  - Query: `limit` integer, default `10`, minimum `1`.
  - Response fields: `mode`, `backend`, `provider`, `account`, `scheduler`,
    `db`, `latest_notify_run`, `last_successful_notify_run`, `runs`.
  - `db` includes `path`, `exists`, `readable`, `messages`, `audit_events`,
    `error_type`, and `error`.
  - Missing DB: `db.exists: false`, `db.readable: false`, `runs: []`, run
    summary fields are `null`; no DB file or parent directory is created.

- `GET /api/runs?limit=`
  - Query: `limit` integer, default `10`, minimum `1`.
  - Response fields: `db`, `last_successful_notify_run`, `runs`.
  - Run rows include `id`, `command`, `status`, `account`, `provider`,
    `started_at`, `finished_at`, `limit`, count fields, and error fields.
  - Missing DB: `runs: []`, `last_successful_notify_run: null`; no DB file or
    parent directory is created.

- `GET /api/audit-events?limit=&action=&status=&account=`
  - Query: `limit` integer, default `25`, minimum `1`; `action`, `status`, and
    `account` are trimmed exact-match filters.
  - Response fields: `db`, `exists`, `readable`, `filters`, `error_type`,
    `error`, `audit_events`.
  - Audit rows include `id`, `account`, `message_uid`, `action`, `status`,
    `reason`, `metadata`, and `created_at`.
  - Missing DB: `exists: false`, `readable: false`, `audit_events: []`; filters
    are still echoed; no DB file or parent directory is created.

- `GET /api/message-stats?sender_limit=&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`
  - Query: `sender_limit` integer, default `10`, minimum `1`; `limit` is accepted
    as a backward-compatible alias when `sender_limit` is omitted; dates are
    inclusive ISO date filters.
  - Response fields: `db`, `exists`, `readable`, `filters`, `error_type`,
    `error`, `total_messages`, `messages_by_day`, `top_senders`.
  - Invalid dates or `date_from` after `date_to` return HTTP 400.
  - Missing DB: `exists: false`, `readable: false`, `total_messages: null`,
    empty stats lists; filters are still echoed; no DB file or parent directory
    is created.

- `GET /api/run-log-events?limit=&command=&status=&finished_from=YYYY-MM-DD&finished_to=YYYY-MM-DD`
  - Query: `limit` integer, default `10`, minimum `1`; `command` and `status`
    are trimmed exact-match filters; finished dates are inclusive ISO date
    filters based on `finished_at`.
  - Response fields: `db`, `exists`, `readable`, `filters`, `error_type`,
    `error`, `run_log_events`.
  - Run log rows use the same shape as `/api/runs` run rows.
  - Invalid dates or `finished_from` after `finished_to` return HTTP 400.
  - Missing DB: `exists: false`, `readable: false`, `run_log_events: []`;
    filters are still echoed; no DB file or parent directory is created.

## Operations Checklist

Before enabling unattended polling:

1. Confirm the agent is still in read-only mode:

```powershell
mail-agent health --skip-scheduler
```

2. Inspect recent local run history:

```powershell
mail-agent runs --limit 10
```

3. Preview the scheduled task without creating it:

```powershell
.\scripts\Register-NotifyNewTask.ps1
```

4. Inspect whether the task is already registered:

```powershell
.\scripts\Register-NotifyNewTask.ps1 -Status
```

Only run `.\scripts\Register-NotifyNewTask.ps1 -Register` when you explicitly
want to create or update the Windows scheduled task.

## Gmail API Access

For `iva196464@gmail.com`, the preferred path is Gmail API over HTTPS.

Required local files:

```text
secrets\gmail-credentials.json  # downloaded OAuth client from Google Cloud
secrets\gmail-token.json        # created locally after browser authorization
```

The app requests only this scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

That means read-only Gmail access: no sending, no deleting, no moving messages, no spam actions.

## Safety

All potentially dangerous operations go through `SafetyPolicy.assert_allowed`.

In `read_only` mode only these capabilities are allowed:

- read messages through IMAP;
- store message data and recommendations in SQLite;
- send Telegram notifications;
- create local draft records in the database.

Drafts are not written back to Gmail yet. That is intentionally outside the first read-only test.
