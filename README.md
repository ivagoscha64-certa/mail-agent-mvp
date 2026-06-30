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

Telegram bot starts only when `TELEGRAM_BOT_TOKEN` is filled:

```powershell
mail-agent bot
```

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
