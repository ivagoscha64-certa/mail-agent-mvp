from __future__ import annotations

import argparse

from mail_agent import db
from mail_agent.audit import log_event
from mail_agent.classifier import classify
from mail_agent.config import load_settings
from mail_agent.mail.gmail_api import GmailApiClient
from mail_agent.mail.imap_client import ImapClient
from mail_agent.safety import SafetyPolicy
from mail_agent.telegram_bot import run_bot


def main() -> None:
    parser = argparse.ArgumentParser(prog="mail-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth-gmail")
    subparsers.add_parser("init-db")
    subparsers.add_parser("status")
    check_mail = subparsers.add_parser("check-mail")
    check_mail.add_argument("--limit", type=int, default=10)
    subparsers.add_parser("bot")

    args = parser.parse_args()
    settings = load_settings()
    safety = SafetyPolicy(settings.mode)

    if args.command == "auth-gmail":
        try:
            GmailApiClient(settings.gmail_api, safety).authorize()
        except RuntimeError as exc:
            raise SystemExit(f"ERROR: {exc}") from None
        print(f"Authorized Gmail API token: {settings.gmail_api.token_path}")
        return

    if args.command == "init-db":
        db.init_db(settings.db_path)
        with db.connect(settings.db_path) as conn:
            db.upsert_account(
                conn,
                settings.gmail_api.provider,
                settings.gmail_api.account_email,
                settings.mode.value,
            )
            log_event(
                conn,
                action="init_db",
                status="completed",
                reason="Initialized SQLite schema and first Gmail API account.",
                account=settings.gmail_api.account_email,
            )
        print(f"Initialized DB: {settings.db_path}")
        return

    db.init_db(settings.db_path)
    with db.connect(settings.db_path) as conn:
        db.upsert_account(
            conn,
            _active_provider(settings),
            _active_account_email(settings),
            settings.mode.value,
        )

        if args.command == "status":
            message_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            audit_count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            print(f"Mode: {settings.mode.value}")
            print(f"DB: {settings.db_path}")
            print(f"Backend: {settings.mail_backend}")
            print(f"Provider: {_active_provider(settings)}")
            print(f"Account: {_active_account_email(settings)}")
            print(f"Messages: {message_count}")
            print(f"Audit events: {audit_count}")
            return

        if args.command == "check-mail":
            client = _build_mail_client(settings, safety)
            saved = 0
            try:
                messages = client.iter_recent_messages(limit=args.limit)
                for message in messages:
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
            except RuntimeError as exc:
                raise SystemExit(f"ERROR: {exc}") from None
            print(f"Read and stored {saved} messages in read-only mode.")
            return

        if args.command == "bot":
            run_bot(settings.telegram, conn)
            return

def _active_provider(settings) -> str:
    if settings.mail_backend == "gmail_api":
        return settings.gmail_api.provider
    return settings.imap_account.provider


def _active_account_email(settings) -> str:
    if settings.mail_backend == "gmail_api":
        return settings.gmail_api.account_email
    return settings.imap_account.account_email


def _build_mail_client(settings, safety: SafetyPolicy):
    if settings.mail_backend == "gmail_api":
        return GmailApiClient(settings.gmail_api, safety)
    if settings.mail_backend == "imap":
        if not settings.imap_account.imap_password:
            raise RuntimeError("IMAP_PASSWORD is empty. Fill .env first.")
        return ImapClient(settings.imap_account, safety)
    raise RuntimeError(f"Unsupported MAIL_BACKEND: {settings.mail_backend}")


if __name__ == "__main__":
    main()
