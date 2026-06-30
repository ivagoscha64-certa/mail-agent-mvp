import json

from mail_agent import db
from mail_agent.__main__ import _format_run_log_row, main


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


def test_runs_command_can_print_json(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:00:00+00:00",
            finished_at="2026-06-30T00:00:03+00:00",
            limit_value=25,
            new_count=2,
            existing_count=3,
            notified_count=1,
        )
        db.insert_run_log(
            conn,
            command="notify-new",
            status="failed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:10:00+00:00",
            finished_at="2026-06-30T00:10:01+00:00",
            limit_value=25,
            error_phase="gmail",
            error_type="RuntimeError",
            error="API unavailable",
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "runs", "--limit", "2", "--json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["db"] == str(db_path)
    assert [row["status"] for row in payload["runs"]] == ["failed", "completed"]
    assert payload["runs"][0]["error_phase"] == "gmail"
    assert payload["last_successful_notify_run"]["new_count"] == 2


def test_runs_command_json_handles_missing_db(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "runs", "--json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "db": str(db_path),
        "last_successful_notify_run": None,
        "runs": [],
    }
