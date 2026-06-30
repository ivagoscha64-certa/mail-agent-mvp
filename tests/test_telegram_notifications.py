from mail_agent import db
from mail_agent.models import (
    Classification,
    Importance,
    MessageType,
    NormalizedMessage,
    Provider,
    RecommendedAction,
    Risk,
)


def test_telegram_notification_baseline_prevents_old_resends(tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        old_id = db.save_message(conn, _message("old-1", "Old important"))
        db.save_classification(conn, old_id, _important_classification())

        baseline_count = db.ensure_telegram_notification_baseline(conn, chat_id="123")

        new_id = db.save_message(conn, _message("new-1", "New important"))
        db.save_classification(conn, new_id, _important_classification())

        pending = db.fetch_pending_telegram_notifications(conn, chat_id="123", limit=10)

        assert baseline_count == 1
        assert [row["message_uid"] for row in pending] == ["new-1"]

        marked = db.mark_telegram_notifications_sent(conn, rows=pending, chat_id="123")
        pending_after_mark = db.fetch_pending_telegram_notifications(
            conn, chat_id="123", limit=10
        )

        assert marked == 1
        assert pending_after_mark == []


def _message(uid: str, subject: str) -> NormalizedMessage:
    return NormalizedMessage(
        provider=Provider.GMAIL,
        account="iva196464@gmail.com",
        message_uid=uid,
        message_id=f"<{uid}@example.test>",
        thread_id=f"thread-{uid}",
        sender="sender@example.test",
        recipients=["iva196464@gmail.com"],
        subject=subject,
        date="2026-06-30T00:00:00+00:00",
        text="Hello",
        html="",
        headers={},
    )


def _important_classification() -> Classification:
    return Classification(
        importance=Importance.HIGH,
        action=RecommendedAction.NOTIFY,
        risk=Risk.SAFE,
        message_type=MessageType.SECURITY,
        reason="Important security message.",
    )
