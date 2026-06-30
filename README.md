# Mail Agent MVP

Read-only MVP for a personal mail agent: Python, SQLite, Telegram bot, and IMAP.

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
- `src/mail_agent/mail/imap_client.py` - read-only IMAP connector.
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

For Gmail IMAP, fill `IMAP_PASSWORD` in `.env` with a Google app password, then run:

```powershell
mail-agent check-mail --limit 10
```

Telegram bot starts only when `TELEGRAM_BOT_TOKEN` is filled:

```powershell
mail-agent bot
```

## Gmail Access

For `iva196464@gmail.com`, use a Google app password, not the normal account password.

Typical path in Google Account:

```text
Google Account -> Security -> 2-Step Verification -> App passwords
```

If app passwords are unavailable, enable 2-Step Verification first. Some Google accounts may not show app passwords if the account is managed by an organization or has a security policy that blocks them.

## Safety

All potentially dangerous operations go through `SafetyPolicy.assert_allowed`.

In `read_only` mode only these capabilities are allowed:

- read messages through IMAP;
- store message data and recommendations in SQLite;
- send Telegram notifications;
- create local draft records in the database.

Drafts are not written back to Gmail yet. That is intentionally outside the first read-only test.
