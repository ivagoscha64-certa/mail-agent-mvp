from mail_agent import db
from mail_agent.__main__ import _format_run_log_row


def test_run_log_tracks_latest_and_latest_success(tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        completed_id = db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:00:00+00:00",
            finished_at="2026-06-30T00:00:03+00:00",
            limit_value=25,
            new_count=15,
            existing_count=10,
            notified_count=15,
        )
        failed_id = db.insert_run_log(
            conn,
            command="notify-new",
            status="failed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:10:00+00:00",
            finished_at="2026-06-30T00:10:01+00:00",
            limit_value=25,
            new_count=0,
            existing_count=3,
            notified_count=0,
            error_phase="telegram_send",
            error_type="RuntimeError",
            error="Telegram unavailable",
        )

        latest = db.fetch_latest_run_log(conn, command="notify-new")
        latest_success = db.fetch_latest_successful_run_log(conn, command="notify-new")

        assert latest["id"] == failed_id
        assert latest["status"] == "failed"
        assert latest["error_phase"] == "telegram_send"
        assert latest["error"] == "Telegram unavailable"
        assert latest_success["id"] == completed_id
        assert latest_success["new_count"] == 15
        assert latest_success["existing_count"] == 10
        assert latest_success["notified_count"] == 15


def test_fetch_run_logs_returns_recent_rows_with_limit(tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        first_id = db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:00:00+00:00",
            finished_at="2026-06-30T00:00:03+00:00",
        )
        second_id = db.insert_run_log(
            conn,
            command="notify-new",
            status="failed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:10:00+00:00",
            finished_at="2026-06-30T00:10:01+00:00",
            error_phase="gmail",
            error_type="RuntimeError",
            error="API unavailable",
        )
        db.insert_run_log(
            conn,
            command="check-mail",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:20:00+00:00",
            finished_at="2026-06-30T00:20:01+00:00",
        )

        rows = db.fetch_run_logs(conn, command="notify-new", limit=2)

        assert [row["id"] for row in rows] == [second_id, first_id]
        assert _format_run_log_row(rows[0]) == (
            "2026-06-30T00:10:01+00:00 | failed | "
            "new=0 existing=0 notified=0 | "
            "error=gmail: RuntimeError: API unavailable"
        )
