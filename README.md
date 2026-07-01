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
