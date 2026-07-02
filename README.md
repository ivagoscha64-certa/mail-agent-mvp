# Mail Agent MVP

Read-only MVP for a personal mail agent: Python, SQLite, Telegram bot, Gmail API, and IMAP fallback.

Configure the local Gmail account in `.env`:

```text
GMAIL_ACCOUNT_EMAIL=your.email@example.com
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
cd <repo path>
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
Copy-Item .env.example .env
mail-agent init-db
mail-agent status
```

By default, project paths are derived from the repository root. You can override
that base folder with `MAIL_AGENT_PROJECT_DIR`, or override individual paths
such as `MAIL_AGENT_DB_PATH`, `GMAIL_CREDENTIALS_PATH`, and `GMAIL_TOKEN_PATH`
in `.env`.

For Gmail API, put the OAuth client JSON here by default:

```text
secrets\gmail-credentials.json
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
cd <repo path>
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
data\notify-new-runs.jsonl
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

For a compact daily operator summary:

```powershell
mail-agent ops
```

`ops` is read-only and prints status/risk, account, backend, mode, DB schema
compatibility, latest and last successful `notify-new` freshness, Scheduler
state, finding codes, and a short next-action phrase. It reuses the local
operational review checks, does not call Gmail or Telegram, and does not write
to SQLite. To skip the Task Scheduler query and read only local config and
SQLite state:

```powershell
mail-agent ops --skip-scheduler
```

Live side effects are separate and require explicitly running commands such as
`notify-new`; daily `ops` checks do not poll Gmail or send Telegram messages.

To generate a minimal local operational review without calling Gmail, Telegram,
or Task Scheduler:

```powershell
mail-agent review
```

For local monitors or scripts:

```powershell
mail-agent review --limit 10 --sender-limit 10 --json
```

`review` reports `status` as `ok`, `warning`, or `critical`, and `risk` as
`low`, `medium`, or `high`. Missing DBs are `warning`/`medium`; unreadable,
corrupt, or old-schema DBs are `critical`/`high`. A latest failed `notify-new`
run is `critical`/`high`. A readable DB with no recorded `notify-new` run is
`warning`/`medium`. The last successful `notify-new` run is considered fresh for
30 minutes, stale at 30 minutes (`warning`/`medium`), and critical at 2 hours
(`critical`/`high`). Unparseable successful-run timestamps are
`warning`/`medium`. The command opens SQLite only in read-only mode and does not
create a missing DB file or parent directory.

The `health --json` and `review --json` payloads include `db.schema` with a
small diagnostic schema summary. It reports `expected_version: 1`, the detected
explicit `schema_metadata` version when present, whether the schema was
inspected, whether the local table set and metadata version are compatible, and
any `missing_tables`. Old DBs are easier to recognize from `missing_tables` such
as `run_log` or `schema_metadata`, without relying only on SQLite error text.

### Operational Review Troubleshooting Examples

Use the finding `code` values to decide what to inspect next. These examples are
read-only: they only call `review`, `health --skip-scheduler`, or `runs`, and do
not call Gmail, Telegram, Scheduler, or create/migrate SQLite state.

#### Warning: missing or empty local history

Example findings:

```json
{
  "status": "warning",
  "risk": "medium",
  "findings": [
    {
      "level": "warning",
      "code": "db_missing",
      "message": "SQLite DB is missing; diagnostics did not create it."
    },
    {
      "level": "warning",
      "code": "notify_new_never_recorded",
      "message": "No notify-new run has been recorded in local SQLite."
    }
  ]
}
```

Read-only checks:

```powershell
mail-agent review --json --limit 10 --sender-limit 10
mail-agent health --skip-scheduler --json
mail-agent runs --limit 10 --json
```

Interpretation: the local DB path is missing, or the DB exists but has no
recorded `notify-new` run. Confirm `config.db_path` and `db.path` point to the
expected local file. If this is a first install, the warning may simply mean no
local polling run has been recorded yet.

#### Warning: stale or unparseable success timestamp

Example findings:

```json
{
  "status": "warning",
  "risk": "medium",
  "findings": [
    {
      "level": "warning",
      "code": "notify_new_success_warning_age",
      "observed_seconds": 1900,
      "threshold_seconds": 1800,
      "message": "Last successful notify-new run is older than the warning threshold."
    }
  ]
}
```

The related `notify_new_success_age_unknown` code means the last successful
`notify-new` timestamp could not be parsed. Inspect only local records first:

```powershell
mail-agent review --json
mail-agent runs --limit 10 --json
```

Interpretation: the last successful `notify-new` run is older than 30 minutes,
or its `finished_at` value is malformed. Check whether the latest local run is
recent, whether it failed, and whether the recorded timestamps look like ISO
datetimes.

#### Critical: latest notify-new failed

Example finding:

```json
{
  "status": "critical",
  "risk": "high",
  "findings": [
    {
      "level": "critical",
      "code": "latest_notify_new_failed",
      "message": "Latest notify-new run failed at 2026-06-30T00:10:01+00:00."
    }
  ]
}
```

Read-only checks:

```powershell
mail-agent runs --limit 10 --json
mail-agent review --json --limit 10 --sender-limit 10
```

Interpretation: inspect the latest run's `error_phase`, `error_type`, and
`error` fields in local SQLite. Do not run live Gmail or Telegram commands while
triaging unless you explicitly intend to exercise those integrations.

#### Critical: unreadable, corrupt, or old-schema DB

Example finding:

```json
{
  "status": "critical",
  "risk": "high",
  "findings": [
    {
      "level": "critical",
      "code": "db_unreadable",
      "message": "SQLite DB exists but could not be fully read: OperationalError: no such table: run_log"
    }
  ]
}
```

Read-only checks:

```powershell
mail-agent health --skip-scheduler --json
mail-agent review --json
```

Interpretation: `db.error_type` and `db.error` identify the local SQLite read
failure. Old schemas commonly surface as missing tables such as `run_log`;
corrupt files usually surface as SQLite database errors. Diagnostic reads keep
using SQLite read-only mode and do not repair, migrate, or replace the DB.
When SQLite metadata can be read, `db.schema.inspected` is `true` and
`db.schema.missing_tables` lists the expected schema tables that are absent. For
corrupt files, schema inspection may remain `false` because even metadata could
not be read. A full pre-metadata DB can be readable but still report
`db.schema.metadata_present: false`, `detected_version: null`, and
`compatible: false` until `init-db` applies the schema metadata table.

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
- `GET /review?limit=&sender_limit=` - HTML operational review page showing
  status/risk, freshness thresholds, latest and last successful `notify-new`
  ages, findings, DB summary, schema summary, safety flags, local message
  stats, and run log summary. `limit` controls recent run log counts and defaults to `10`;
  `sender_limit` controls top sender count and defaults to `10`.
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
- `GET /api/operational-review?limit=&sender_limit=` - JSON read-only
  operational review. `limit` controls recent run log counts and defaults to
  `10`; `sender_limit` controls top sender count and defaults to `10`.
- `GET /favicon.ico` - empty `204 No Content` response to keep browser smoke
  checks free of favicon 404 noise.

Invalid `limit` or `sender_limit` values, invalid dates, or date ranges where
the start is after the end return HTTP 400 JSON errors. Missing DBs are reported
as diagnostics: JSON responses include `exists: false`, `readable: false`, and
empty result lists; the missing DB file and parent directory are not created by
these reads.

The `/review` page includes a read-only handoff section with a selectable JSON
endpoint and matching local command. Use either form to export the same
operational review payload without calling Gmail, Telegram, or Scheduler:

```powershell
mail-agent review --json --limit 10 --sender-limit 10
```

### Local Web JSON Contract

All JSON endpoints are diagnostic `GET` endpoints. They read local config and
SQLite only, skip Scheduler checks, do not call Gmail or Telegram, and return
HTTP 400 with `{"error": "..."}` for invalid query parameters.

- `GET /api/health?limit=`
  - Query: `limit` integer, default `10`, minimum `1`.
  - Response fields: `mode`, `backend`, `provider`, `account`, `scheduler`,
    `db`, `latest_notify_run`, `last_successful_notify_run`, `runs`.
  - `db` includes `path`, `exists`, `readable`, `messages`, `audit_events`,
    `error_type`, `error`, and `schema`.
  - `db.schema` includes `expected_version`, `detected_version`, `inspected`,
    `compatible`, `metadata_present`, `metadata_valid`, `expected_tables`,
    `present_tables`, and `missing_tables`. Old schemas usually have
    `inspected: true`, `compatible: false`, and one or more `missing_tables`;
    full pre-metadata schemas have `metadata_present: false` and
    `detected_version: null`; corrupt DBs may have `inspected: false`.
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

- `GET /api/operational-review?limit=&sender_limit=`
  - Query: `limit` integer, default `10`, minimum `1`; `sender_limit` integer,
    default `10`, minimum `1`.
  - Response fields: `status`, `risk`, `generated_at`, `config`, `safety`,
    `thresholds`, `db`, `notify_new`, `local_activity`, and `findings`.
  - `thresholds` includes
    `notify_new_success_warning_after_seconds: 1800` and
    `notify_new_success_critical_after_seconds: 7200`.
  - `config` summarizes `mode`, `backend`, `provider`, `account`, and
    `db_path`.
  - `safety` explicitly reports that diagnostics are read-only and that Gmail,
    Telegram, and Scheduler were not called or modified.
  - `db` uses the same shape as `/api/health` DB info.
  - `db.schema.expected_version` is `1`. `detected_version` comes from
    `schema_metadata.schema_version` when present and parseable; otherwise it is
    `null`. `compatible` is `true` only when all expected tables are present and
    the detected schema version matches `expected_version`.
  - `notify_new` includes `latest`, `last_successful`,
    `last_successful_age_seconds`, and `recent_runs`.
  - `local_activity` includes nested `message_stats` and `run_log_events`
    payloads.
  - Findings include `level`, `code`, and `message`. Threshold findings also
    include `observed_seconds` and `threshold_seconds`.
  - Status/risk mapping: healthy DB plus latest completed `notify-new` and a
    fresh last successful `notify-new` is `ok`/`low`; missing DB, no recorded
    `notify-new` run, last successful `notify-new` older than 30 minutes but
    younger than 2 hours, or an unparseable last successful timestamp is
    `warning`/`medium`; unreadable/corrupt/old-schema DB, latest failed
    `notify-new`, or last successful `notify-new` older than 2 hours is
    `critical`/`high`.
  - Missing DB: reported as diagnostics; no DB file or parent directory is
    created.

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

3. Generate the local operational review:

```powershell
mail-agent review --json
```

4. Preview the scheduled task without creating it:

```powershell
.\scripts\Register-NotifyNewTask.ps1
```

5. Inspect whether the task is already registered:

```powershell
.\scripts\Register-NotifyNewTask.ps1 -Status
```

Only run `.\scripts\Register-NotifyNewTask.ps1 -Register` when you explicitly
want to create or update the Windows scheduled task.

## Gmail API Access

For Gmail accounts, the preferred path is Gmail API over HTTPS.

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
