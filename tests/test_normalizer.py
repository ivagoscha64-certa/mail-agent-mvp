from email.message import EmailMessage

from mail_agent import db
from mail_agent.diagnostics import build_message_stats_payload
from mail_agent.models import Provider
from mail_agent.normalizer import normalize_imap_message


def test_normalizer_stores_rfc_date_as_iso_for_message_stats(monkeypatch, tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "iva196464@gmail.com"
    message["Subject"] = "Gmail-like date"
    message["Date"] = "Wed, 01 Jul 2026 20:32:39 +1000"
    message["Message-ID"] = "<uid-1@example.com>"
    message.set_content("Body")

    normalized = normalize_imap_message(
        provider=Provider.GMAIL,
        account="iva196464@gmail.com",
        uid="uid-1",
        folder="INBOX",
        message=message,
    )

    assert normalized.date == "2026-07-01T20:32:39+10:00"

    with db.connect(db_path) as conn:
        db.save_message(conn, normalized)
        stored_date = conn.execute(
            "SELECT message_date FROM messages WHERE message_uid = ?",
            ("uid-1",),
        ).fetchone()["message_date"]

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    stats = build_message_stats_payload(_load_settings(), sender_limit=5)

    assert stored_date.startswith("2026-07-01")
    assert stats["messages_by_day"] == [{"count": 1, "day": "2026-07-01"}]


def test_normalizer_uses_none_for_missing_or_invalid_date_header():
    missing_date = EmailMessage()
    missing_date.set_content("Body")
    invalid_date = EmailMessage()
    invalid_date["Date"] = "not a parseable date"
    invalid_date.set_content("Body")

    assert _normalized_date(missing_date) is None
    assert _normalized_date(invalid_date) is None


def _normalized_date(message: EmailMessage) -> str | None:
    return normalize_imap_message(
        provider=Provider.GMAIL,
        account="iva196464@gmail.com",
        uid="uid",
        folder="INBOX",
        message=message,
    ).date


def _load_settings():
    from mail_agent.config import load_settings

    return load_settings()
