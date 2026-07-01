import json
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mail_agent import db
from mail_agent.__main__ import _fetch_scheduler_status, _format_run_log_row, main
from mail_agent.config import load_settings
from mail_agent.diagnostics import build_operational_review_payload


def test_init_db_records_explicit_schema_version(tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT metadata_value
            FROM schema_metadata
            WHERE metadata_key = 'schema_version'
            """
        ).fetchone()

    assert row["metadata_value"] == "1"


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


def test_health_command_json_handles_missing_db_without_creating_it(
    monkeypatch,
    capsys,
    tmp_path,
):
    db_path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "health", "--json", "--skip-scheduler"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert db_path.exists() is False
    assert payload["db"] == {
        "audit_events": None,
        "error": None,
        "error_type": None,
        "exists": False,
        "messages": None,
        "path": str(db_path),
        "readable": False,
        "schema": {
            "compatible": None,
            "detected_version": None,
            "expected_tables": [
                "accounts",
                "approval_actions",
                "audit_log",
                "drafts",
                "message_classifications",
                "messages",
                "recommendations",
                "run_log",
                "schema_metadata",
                "spam_signals",
                "telegram_notifications",
                "unsubscribe_candidates",
            ],
            "expected_version": 1,
            "inspected": False,
            "metadata_present": False,
            "metadata_valid": False,
            "missing_tables": [],
            "present_tables": [],
        },
    }
    assert payload["latest_notify_run"] is None
    assert payload["last_successful_notify_run"] is None
    assert payload["runs"] == []
    assert payload["scheduler"] is None


def test_health_command_json_includes_local_counts_runs_and_scheduler(
    monkeypatch,
    capsys,
    tmp_path,
):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO messages(
                provider, account, message_uid, message_id, sender,
                recipients_json, subject, headers_json, attachments_json,
                links_json, text, html, created_at
            )
            VALUES (
                'gmail', 'iva196464@gmail.com', 'uid-1', 'message-1',
                'sender@example.com', '[]', 'Hello', '{}', '[]', '[]',
                '', '', '2026-06-30T00:00:00+00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO audit_log(action, status, reason, metadata_json, created_at)
            VALUES (
                'test_event', 'completed', 'health test', '{}',
                '2026-06-30T00:00:00+00:00'
            )
            """
        )
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

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "mail_agent.__main__._fetch_scheduler_status",
        lambda task_name: {
            "available": True,
            "last_result": None,
            "last_run": None,
            "next_run": None,
            "registered": False,
            "state": None,
            "task_name": task_name,
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "health", "--limit", "1", "--json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["db"]["exists"] is True
    assert payload["db"]["messages"] == 1
    assert payload["db"]["audit_events"] == 1
    assert payload["db"]["schema"]["compatible"] is True
    assert payload["db"]["schema"]["detected_version"] == 1
    assert payload["db"]["schema"]["metadata_present"] is True
    assert payload["db"]["schema"]["metadata_valid"] is True
    assert payload["db"]["schema"]["missing_tables"] == []
    assert "run_log" in payload["db"]["schema"]["present_tables"]
    assert "schema_metadata" in payload["db"]["schema"]["present_tables"]
    assert payload["latest_notify_run"]["status"] == "completed"
    assert payload["last_successful_notify_run"]["notified_count"] == 1
    assert len(payload["runs"]) == 1
    assert payload["scheduler"] == {
        "available": True,
        "last_result": None,
        "last_run": None,
        "next_run": None,
        "registered": False,
        "state": None,
        "task_name": "MailAgentNotifyNew",
    }


def test_status_command_handles_missing_db_without_creating_it(
    monkeypatch,
    capsys,
    tmp_path,
):
    db_path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr("sys.argv", ["mail-agent", "status"])

    main()

    output = capsys.readouterr().out
    assert db_path.exists() is False
    assert "DB exists: no" in output
    assert "Scheduler: skipped" in output


def test_health_command_json_handles_existing_empty_db(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    db_path.write_bytes(b"")
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "health", "--json", "--skip-scheduler"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["db"]["exists"] is True
    assert payload["db"]["readable"] is False
    assert payload["db"]["error_type"] == "OperationalError"
    assert "no such table" in payload["db"]["error"]
    assert payload["runs"] == []


def test_health_command_json_handles_old_db_with_missing_run_log(
    monkeypatch,
    capsys,
    tmp_path,
):
    db_path = tmp_path / "old.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY)")

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "health", "--json", "--skip-scheduler"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["db"]["exists"] is True
    assert payload["db"]["readable"] is False
    assert payload["db"]["error_type"] == "OperationalError"
    assert "run_log" in payload["db"]["error"]
    assert payload["db"]["schema"]["inspected"] is True
    assert payload["db"]["schema"]["compatible"] is False
    assert "run_log" in payload["db"]["schema"]["missing_tables"]
    assert "schema_metadata" in payload["db"]["schema"]["missing_tables"]
    assert payload["db"]["schema"]["metadata_present"] is False
    assert payload["db"]["schema"]["metadata_valid"] is False
    assert payload["db"]["schema"]["present_tables"] == ["audit_log", "messages"]
    assert payload["latest_notify_run"] is None


def test_health_command_json_handles_corrupt_db(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "corrupt.sqlite3"
    db_path.write_bytes(b"not a sqlite database")
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "health", "--json", "--skip-scheduler"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["db"]["exists"] is True
    assert payload["db"]["readable"] is False
    assert payload["db"]["error_type"] == "DatabaseError"
    assert "database" in payload["db"]["error"]
    assert payload["db"]["schema"]["inspected"] is False
    assert payload["db"]["schema"]["compatible"] is None


def test_operational_review_handles_missing_db_without_creating_it(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "missing-dir" / "missing.sqlite3"
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    assert db_path.exists() is False
    assert db_path.parent.exists() is False
    assert payload["status"] == "warning"
    assert payload["risk"] == "medium"
    assert payload["db"]["exists"] is False
    assert payload["db"]["schema"]["inspected"] is False
    assert payload["db"]["schema"]["compatible"] is None
    assert payload["safety"] == {
        "diagnostic_read_only": True,
        "gmail_called": False,
        "scheduler_checked": False,
        "scheduler_modified": False,
        "telegram_called": False,
    }
    assert {finding["code"] for finding in payload["findings"]} == {
        "db_missing",
        "notify_new_never_recorded",
    }


def test_operational_review_reports_healthy_db(monkeypatch, tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    finished_at = _iso_seconds_ago(60)
    with db.connect(db_path) as conn:
        db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at=finished_at,
            finished_at=finished_at,
            limit_value=25,
            new_count=2,
            existing_count=3,
            notified_count=1,
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    assert payload["status"] == "ok"
    assert payload["risk"] == "low"
    assert payload["db"]["exists"] is True
    assert payload["db"]["readable"] is True
    assert payload["db"]["schema"]["compatible"] is True
    assert payload["db"]["schema"]["detected_version"] == 1
    assert payload["db"]["schema"]["metadata_present"] is True
    assert payload["db"]["schema"]["metadata_valid"] is True
    assert payload["db"]["schema"]["missing_tables"] == []
    assert payload["notify_new"]["latest"]["status"] == "completed"
    assert payload["thresholds"] == {
        "notify_new_success_warning_after_seconds": 1800,
        "notify_new_success_critical_after_seconds": 7200,
    }
    assert payload["notify_new"]["last_successful_age_seconds"] < 1800
    assert [finding["code"] for finding in payload["findings"]] == [
        "db_readable",
        "latest_notify_new_completed",
        "notify_new_success_fresh",
    ]


def test_operational_review_warns_when_success_is_older_than_warning_threshold(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    finished_at = _iso_seconds_ago(1900)
    with db.connect(db_path) as conn:
        db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at=finished_at,
            finished_at=finished_at,
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    age_finding = _finding(payload, "notify_new_success_warning_age")
    assert payload["status"] == "warning"
    assert payload["risk"] == "medium"
    assert payload["notify_new"]["last_successful_age_seconds"] >= 1800
    assert age_finding["level"] == "warning"
    assert age_finding["observed_seconds"] >= 1800
    assert age_finding["threshold_seconds"] == 1800


def test_operational_review_critical_when_success_is_older_than_critical_threshold(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    finished_at = _iso_seconds_ago(7300)
    with db.connect(db_path) as conn:
        db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at=finished_at,
            finished_at=finished_at,
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    age_finding = _finding(payload, "notify_new_success_critical_age")
    assert payload["status"] == "critical"
    assert payload["risk"] == "high"
    assert payload["notify_new"]["last_successful_age_seconds"] >= 7200
    assert age_finding["level"] == "critical"
    assert age_finding["observed_seconds"] >= 7200
    assert age_finding["threshold_seconds"] == 7200


def test_operational_review_warns_when_success_timestamp_cannot_be_parsed(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="not-a-timestamp",
            finished_at="not-a-timestamp",
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    age_finding = _finding(payload, "notify_new_success_age_unknown")
    assert payload["status"] == "warning"
    assert payload["risk"] == "medium"
    assert payload["notify_new"]["last_successful_age_seconds"] is None
    assert age_finding["level"] == "warning"
    assert age_finding["observed_seconds"] is None
    assert age_finding["threshold_seconds"] == 1800


def test_operational_review_reports_latest_failed_run(monkeypatch, tmp_path):
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
        )
        db.insert_run_log(
            conn,
            command="notify-new",
            status="failed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at="2026-06-30T00:10:00+00:00",
            finished_at="2026-06-30T00:10:01+00:00",
            error_phase="telegram_send",
            error_type="RuntimeError",
            error="Telegram unavailable",
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    assert payload["status"] == "critical"
    assert payload["risk"] == "high"
    assert payload["notify_new"]["latest"]["status"] == "failed"
    assert "latest_notify_new_failed" in {
        finding["code"] for finding in payload["findings"]
    }


def test_operational_review_reports_old_db_missing_run_log(monkeypatch, tmp_path):
    db_path = tmp_path / "old.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY)")

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    assert payload["status"] == "critical"
    assert payload["risk"] == "high"
    assert payload["db"]["readable"] is False
    assert payload["db"]["error_type"] == "OperationalError"
    assert "run_log" in payload["db"]["error"]
    assert payload["db"]["schema"]["inspected"] is True
    assert payload["db"]["schema"]["compatible"] is False
    assert "run_log" in payload["db"]["schema"]["missing_tables"]
    assert "schema_metadata" in payload["db"]["schema"]["missing_tables"]
    assert payload["db"]["schema"]["metadata_present"] is False
    assert payload["db"]["schema"]["metadata_valid"] is False
    assert payload["db"]["schema"]["present_tables"] == ["audit_log", "messages"]
    assert "db_unreadable" in {finding["code"] for finding in payload["findings"]}


def test_operational_review_reports_corrupt_db(monkeypatch, tmp_path):
    db_path = tmp_path / "corrupt.sqlite3"
    db_path.write_bytes(b"not a sqlite database")
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    payload = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )

    assert payload["status"] == "critical"
    assert payload["risk"] == "high"
    assert payload["db"]["readable"] is False
    assert payload["db"]["error_type"] == "DatabaseError"
    assert "database" in payload["db"]["error"]
    assert payload["db"]["schema"]["inspected"] is False
    assert payload["db"]["schema"]["compatible"] is None


def test_health_reports_full_legacy_schema_without_metadata_as_incompatible(
    monkeypatch,
    capsys,
    tmp_path,
):
    db_path = tmp_path / "legacy.sqlite3"
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        conn.execute("DROP TABLE schema_metadata")

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "health", "--json", "--skip-scheduler"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["db"]["exists"] is True
    assert payload["db"]["readable"] is True
    assert payload["db"]["schema"]["inspected"] is True
    assert payload["db"]["schema"]["compatible"] is False
    assert payload["db"]["schema"]["detected_version"] is None
    assert payload["db"]["schema"]["metadata_present"] is False
    assert payload["db"]["schema"]["metadata_valid"] is False
    assert payload["db"]["schema"]["missing_tables"] == ["schema_metadata"]

    review = build_operational_review_payload(
        load_settings(),
        limit=5,
        sender_limit=3,
    )
    assert review["db"]["readable"] is True
    assert review["db"]["schema"]["compatible"] is False
    assert review["db"]["schema"]["detected_version"] is None
    assert review["db"]["schema"]["metadata_present"] is False
    assert review["db"]["schema"]["missing_tables"] == ["schema_metadata"]


def test_review_command_can_print_json(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    finished_at = _iso_seconds_ago(60)
    with db.connect(db_path) as conn:
        db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="iva196464@gmail.com",
            provider="gmail",
            started_at=finished_at,
            finished_at=finished_at,
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(
        "sys.argv",
        ["mail-agent", "review", "--limit", "2", "--sender-limit", "2", "--json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["risk"] == "low"
    assert payload["config"]["db_path"] == str(db_path)
    assert payload["notify_new"]["latest"]["status"] == "completed"
    assert payload["notify_new"]["last_successful_age_seconds"] < 1800


def test_scheduler_status_handles_json_parse_error(monkeypatch, tmp_path):
    _write_scheduler_script(tmp_path)
    monkeypatch.setattr("mail_agent.__main__.shutil.which", lambda name: "powershell")
    monkeypatch.setattr("mail_agent.__main__.DEFAULT_PROJECT_DIR", tmp_path)
    monkeypatch.setattr(
        "mail_agent.__main__.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout="not-json",
            stderr="",
        ),
    )

    payload = _fetch_scheduler_status("Task")

    assert payload["available"] is False
    assert payload["error_type"] == "JSONDecodeError"


def test_scheduler_status_handles_subprocess_failure(monkeypatch, tmp_path):
    _write_scheduler_script(tmp_path)
    monkeypatch.setattr("mail_agent.__main__.shutil.which", lambda name: "powershell")
    monkeypatch.setattr("mail_agent.__main__.DEFAULT_PROJECT_DIR", tmp_path)
    monkeypatch.setattr(
        "mail_agent.__main__.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr="failed",
        ),
    )

    payload = _fetch_scheduler_status("Task")

    assert payload == {
        "available": False,
        "error": "failed",
        "error_type": "SchedulerStatusCommandFailed",
        "returncode": 1,
        "task_name": "Task",
    }


def test_scheduler_status_handles_timeout(monkeypatch, tmp_path):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=10)

    _write_scheduler_script(tmp_path)
    monkeypatch.setattr("mail_agent.__main__.shutil.which", lambda name: "powershell")
    monkeypatch.setattr("mail_agent.__main__.DEFAULT_PROJECT_DIR", tmp_path)
    monkeypatch.setattr("mail_agent.__main__.subprocess.run", raise_timeout)

    payload = _fetch_scheduler_status("Task")

    assert payload["available"] is False
    assert payload["error_type"] == "TimeoutExpired"


def _write_scheduler_script(project_dir: Path) -> None:
    script_path = project_dir / "scripts" / "Register-NotifyNewTask.ps1"
    script_path.parent.mkdir()
    script_path.write_text("# test script", encoding="utf-8")


def _iso_seconds_ago(seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


def _finding(payload: dict, code: str) -> dict:
    for finding in payload["findings"]:
        if finding["code"] == code:
            return finding
    raise AssertionError(f"missing finding {code}")
