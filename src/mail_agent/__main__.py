from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from mail_agent import db
from mail_agent.audit import log_event
from mail_agent.classifier import classify
from mail_agent.config import load_settings
from mail_agent.mail.gmail_api import GmailApiClient
from mail_agent.mail.imap_client import ImapClient
from mail_agent.safety import SafetyPolicy
from mail_agent.telegram_bot import (
    print_chat_ids,
    run_bot,
    send_pending_summary,
    send_summary,
    validate_telegram_config,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mail-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    auth_gmail = subparsers.add_parser("auth-gmail")
    auth_gmail.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorization URL instead of opening the default browser.",
    )
    subparsers.add_parser("init-db")
    subparsers.add_parser("status")
    runs = subparsers.add_parser("runs")
    runs.add_argument("--limit", type=int, default=10)
    check_mail = subparsers.add_parser("check-mail")
    check_mail.add_argument("--limit", type=int, default=10)
    send_telegram = subparsers.add_parser("send-summary")
    send_telegram.add_argument("--limit", type=int, default=10)
    notify_new = subparsers.add_parser("notify-new")
    notify_new.add_argument("--limit", type=int, default=25)
    subparsers.add_parser("telegram-chat-id")
    subparsers.add_parser("bot")

    args = parser.parse_args()
    settings = load_settings()
    safety = SafetyPolicy(settings.mode)

    if args.command == "auth-gmail":
        try:
            GmailApiClient(settings.gmail_api, safety).authorize(
                open_browser=not args.no_browser
            )
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

    if args.command == "runs":
        if args.limit < 1:
            raise SystemExit("ERROR: --limit must be at least 1")
        if not settings.db_path.exists():
            print(f"No DB found: {settings.db_path}")
            return
        with db.connect(settings.db_path) as conn:
            run_rows = db.fetch_run_logs(conn, command="notify-new", limit=args.limit)
            latest_successful_notify_run = db.fetch_latest_successful_run_log(
                conn,
                command="notify-new",
            )
            print(f"DB: {settings.db_path}")
            if not run_rows:
                print("No notify-new runs recorded.")
                return
            print(f"Latest notify-new runs (limit={args.limit}):")
            for row in run_rows:
                print(_format_run_log_row(row))
            if latest_successful_notify_run:
                print(
                    "Last successful notify-new run: "
                    f"{latest_successful_notify_run['finished_at']}"
                )
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
            latest_notify_run = db.fetch_latest_run_log(conn, command="notify-new")
            latest_successful_notify_run = db.fetch_latest_successful_run_log(
                conn,
                command="notify-new",
            )
            print(f"Mode: {settings.mode.value}")
            print(f"DB: {settings.db_path}")
            print(f"Backend: {settings.mail_backend}")
            print(f"Provider: {_active_provider(settings)}")
            print(f"Account: {_active_account_email(settings)}")
            print(f"Messages: {message_count}")
            print(f"Audit events: {audit_count}")
            if latest_notify_run:
                print(
                    "Last notify-new run: "
                    f"{latest_notify_run['status']} at "
                    f"{latest_notify_run['finished_at']} "
                    f"(new={latest_notify_run['new_count']}, "
                    f"existing={latest_notify_run['existing_count']}, "
                    f"notified={latest_notify_run['notified_count']})"
                )
                if latest_notify_run["error"]:
                    print(
                        "Last notify-new error: "
                        f"{latest_notify_run['error_phase'] or 'unknown'} "
                        f"{latest_notify_run['error_type']}: "
                        f"{latest_notify_run['error']}"
                    )
            if latest_successful_notify_run:
                print(
                    "Last successful notify-new run: "
                    f"{latest_successful_notify_run['finished_at']}"
                )
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

        if args.command == "notify-new":
            run_started_at = _utc_now()
            saved = 0
            skipped_existing = 0
            notified = 0
            error_phase = "setup"
            try:
                error_phase = "telegram_config"
                validate_telegram_config(settings.telegram)
                db.ensure_telegram_notification_baseline(
                    conn,
                    chat_id=settings.telegram.allowed_chat_id,
                )
                error_phase = "gmail"
                client = _build_mail_client(settings, safety)
                messages = client.iter_recent_messages(limit=args.limit)
                for message in messages:
                    if db.message_exists(
                        conn,
                        provider=message.provider.value,
                        account=message.account,
                        message_uid=message.message_uid,
                    ):
                        skipped_existing += 1
                        continue

                    row_id = db.save_message(conn, message)
                    classification = classify(message)
                    db.save_classification(conn, row_id, classification)
                    log_event(
                        conn,
                        action="read_new_message",
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

                error_phase = "telegram_send"
                notified = send_pending_summary(
                    settings.telegram,
                    conn,
                    limit=args.limit,
                )
            except Exception as exc:
                conn.rollback()
                _record_notify_run(
                    conn,
                    settings=settings,
                    started_at=run_started_at,
                    finished_at=_utc_now(),
                    status="failed",
                    limit_value=args.limit,
                    new_count=saved,
                    existing_count=skipped_existing,
                    notified_count=notified,
                    error_phase=error_phase,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                conn.commit()
                raise SystemExit(f"ERROR: {type(exc).__name__}: {exc}") from None
            _record_notify_run(
                conn,
                settings=settings,
                started_at=run_started_at,
                finished_at=_utc_now(),
                status="completed",
                limit_value=args.limit,
                new_count=saved,
                existing_count=skipped_existing,
                notified_count=notified,
            )
            print(
                "Read new mail and notified Telegram: "
                f"new={saved}, existing={skipped_existing}, notified={notified}."
            )
            return

        if args.command == "bot":
            run_bot(settings.telegram, conn)
            return

        if args.command == "telegram-chat-id":
            try:
                print_chat_ids(settings.telegram)
            except RuntimeError as exc:
                raise SystemExit(f"ERROR: {exc}") from None
            return

        if args.command == "send-summary":
            try:
                send_summary(settings.telegram, conn, limit=args.limit)
            except RuntimeError as exc:
                raise SystemExit(f"ERROR: {exc}") from None
            print("Telegram summary sent.")
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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _format_run_log_row(row) -> str:
    line = (
        f"{row['finished_at']} | {row['status']} | "
        f"new={row['new_count']} existing={row['existing_count']} "
        f"notified={row['notified_count']}"
    )
    if row["status"] == "failed":
        error_parts = [
            row["error_phase"] or "unknown",
            row["error_type"] or "Error",
            row["error"] or "",
        ]
        line += " | error=" + ": ".join(part for part in error_parts if part)
    return line


def _write_notify_run_log(db_path: Path, payload: dict) -> None:
    log_path = db_path.parent / "notify-new-runs.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _record_notify_run(
    conn,
    *,
    settings,
    started_at: str,
    finished_at: str,
    status: str,
    limit_value: int,
    new_count: int,
    existing_count: int,
    notified_count: int,
    error_phase: str | None = None,
    error_type: str | None = None,
    error: str | None = None,
) -> None:
    payload = {
        "account": _active_account_email(settings),
        "error": error,
        "error_phase": error_phase,
        "error_type": error_type,
        "existing": existing_count,
        "finished_at": finished_at,
        "limit": limit_value,
        "new": new_count,
        "notified": notified_count,
        "provider": _active_provider(settings),
        "started_at": started_at,
        "status": status,
    }
    db.insert_run_log(
        conn,
        command="notify-new",
        status=status,
        account=payload["account"],
        provider=payload["provider"],
        started_at=started_at,
        finished_at=finished_at,
        limit_value=limit_value,
        new_count=new_count,
        existing_count=existing_count,
        notified_count=notified_count,
        error_phase=error_phase,
        error_type=error_type,
        error=error,
    )
    try:
        _write_notify_run_log(settings.db_path, payload)
    except OSError as exc:
        print(f"WARNING: could not write notify-new JSONL run log: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
