from __future__ import annotations

import argparse

from mail_agent import db
from mail_agent.audit import log_event
from mail_agent.classifier import classify
from mail_agent.config import load_settings
from mail_agent.mail.imap_mailru import MailruImapClient
from mail_agent.models import Provider
from mail_agent.safety import SafetyPolicy
from mail_agent.telegram_bot import run_bot


def main() -> None:
    parser = argparse.ArgumentParser(prog="mail-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("status")
    check_mail = subparsers.add_parser("check-mail")
    check_mail.add_argument("--limit", type=int, default=10)
    subparsers.add_parser("bot")

    args = parser.parse_args()
    settings = load_settings()

    if args.command == "init-db":
        db.init_db(settings.db_path)
        with db.connect(settings.db_path) as conn:
            db.upsert_account(
                conn,
                Provider.MAILRU.value,
                settings.mailru.account_email,
                settings.mode.value,
            )
            log_event(
                conn,
                action="init_db",
                status="completed",
                reason="Initialized SQLite schema and first Mail.ru account.",
                account=settings.mailru.account_email,
            )
        print(f"Initialized DB: {settings.db_path}")
        return

    db.init_db(settings.db_path)
    with db.connect(settings.db_path) as conn:
        db.upsert_account(
            conn,
            Provider.MAILRU.value,
            settings.mailru.account_email,
            settings.mode.value,
        )

        if args.command == "status":
            message_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            audit_count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            print(f"Mode: {settings.mode.value}")
            print(f"DB: {settings.db_path}")
            print(f"Account: {settings.mailru.account_email}")
            print(f"Messages: {message_count}")
            print(f"Audit events: {audit_count}")
            return

        if args.command == "check-mail":
            if not settings.mailru.imap_password:
                raise RuntimeError("MAILRU_IMAP_PASSWORD is empty. Fill .env first.")
            safety = SafetyPolicy(settings.mode)
            client = MailruImapClient(settings.mailru, safety)
            saved = 0
            for message in client.iter_recent_messages(limit=args.limit):
                row_id = db.save_message(conn, message)
                classification = classify(message)
                db.save_classification(conn, row_id, classification)
                log_event(
                    conn,
                    action="read_message",
                    status="completed",
                    reason=classification.reason,
                    account=message.account,
                    message_uid=message.message_uid,
                    metadata={
                        "importance": classification.importance.value,
                        "action": classification.action.value,
                        "risk": classification.risk.value,
                    },
                )
                saved += 1
            print(f"Read and stored {saved} messages in read-only mode.")
            return

        if args.command == "bot":
            run_bot(settings.telegram, conn)
            return


if __name__ == "__main__":
    main()
