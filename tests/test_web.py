import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer

import pytest

from mail_agent import db
from mail_agent import __main__ as cli
from mail_agent.audit import log_event
from mail_agent.diagnostics import (
    build_audit_events_payload,
    build_health_payload,
    build_message_stats_payload,
    build_operational_review_payload,
    build_run_log_events_payload,
    build_runs_payload,
)
from mail_agent.models import NormalizedMessage, Provider
from mail_agent.web import MailAgentWebHandler, is_loopback_bind_host


def test_diagnostics_uses_readonly_payload_without_creating_missing_db(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "missing-dir" / "missing.sqlite3"
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    from mail_agent.config import load_settings

    settings = load_settings()
    health = build_health_payload(
        settings,
        run_limit=10,
        include_scheduler=False,
        scheduler_task_name="MailAgentNotifyNew",
    )
    runs = build_runs_payload(settings, limit=10)
    audit = build_audit_events_payload(settings, limit=10)
    stats = build_message_stats_payload(settings, sender_limit=10)
    run_log = build_run_log_events_payload(settings, limit=10)
    review = build_operational_review_payload(settings, limit=10, sender_limit=10)

    assert db_path.exists() is False
    assert db_path.parent.exists() is False
    assert health["db"]["exists"] is False
    assert health["db"]["readable"] is False
    assert health["runs"] == []
    assert runs == {
        "db": str(db_path),
        "last_successful_notify_run": None,
        "runs": [],
    }
    assert audit["exists"] is False
    assert audit["readable"] is False
    assert audit["audit_events"] == []
    assert stats["exists"] is False
    assert stats["filters"] == {
        "date_from": None,
        "date_to": None,
        "sender_limit": 10,
    }
    assert stats["readable"] is False
    assert stats["messages_by_day"] == []
    assert stats["top_senders"] == []
    assert stats["total_messages"] is None
    assert run_log["exists"] is False
    assert run_log["filters"] == {
        "command": None,
        "finished_from": None,
        "finished_to": None,
        "status": None,
    }
    assert run_log["readable"] is False
    assert run_log["run_log_events"] == []
    assert review["status"] == "warning"
    assert review["risk"] == "medium"
    assert review["db"]["exists"] is False
    assert review["local_activity"]["message_stats"]["top_senders"] == []


def test_web_api_health_and_runs_are_readonly_get_endpoints(monkeypatch, tmp_path):
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
    with _web_server() as base_url:
        health = _get_json(f"{base_url}/api/health")
        runs = _get_json(f"{base_url}/api/runs?limit=1")
        review = _get_json(
            f"{base_url}/api/operational-review?limit=1&sender_limit=1"
        )
        html = _get_text(f"{base_url}/")
        review_html = _get_text(f"{base_url}/review?limit=1&sender_limit=1")

    assert health["mode"] == "read_only"
    assert health["db"]["exists"] is True
    assert health["db"]["readable"] is True
    assert health["latest_notify_run"]["status"] == "failed"
    assert health["last_successful_notify_run"]["status"] == "completed"
    assert health["scheduler"] is None
    assert len(runs["runs"]) == 1
    assert runs["runs"][0]["status"] == "failed"
    assert review["status"] == "critical"
    assert review["risk"] == "high"
    assert review["notify_new"]["latest"]["status"] == "failed"
    assert review["safety"]["scheduler_checked"] is False
    assert "Mail Agent Panel" in html
    assert "read_only" in html
    assert "Recent Runs" in html
    assert "Run Log Events" in html
    assert 'href="/review"' in html
    assert "Mail Agent Operational Review" in review_html
    assert "Review Status" in review_html
    assert "Freshness Thresholds" in review_html
    assert "Warning After Seconds" in review_html
    assert "1800" in review_html
    assert "7200" in review_html
    assert "Last Successful Age Seconds" in review_html
    assert "latest_notify_new_failed" in review_html
    assert "Database Summary" in review_html
    assert "Safety Flags" in review_html
    assert "Local Message Stats" in review_html
    assert "Run Log Summary" in review_html


def test_web_api_operational_review_includes_threshold_age_fields(
    monkeypatch,
    tmp_path,
):
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
    with _web_server() as base_url:
        review = _get_json(
            f"{base_url}/api/operational-review?limit=5&sender_limit=5"
        )

    age_finding = _finding(review, "notify_new_success_fresh")
    assert review["status"] == "ok"
    assert review["thresholds"] == {
        "notify_new_success_warning_after_seconds": 1800,
        "notify_new_success_critical_after_seconds": 7200,
    }
    assert review["notify_new"]["last_successful_age_seconds"] < 1800
    assert age_finding["observed_seconds"] < 1800
    assert age_finding["threshold_seconds"] == 1800


def test_web_api_filters_run_log_events_by_status_and_finished_range(
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
            account="primary@example.com",
            provider="gmail",
            started_at="2026-06-28T00:00:00+00:00",
            finished_at="2026-06-28T00:00:03+00:00",
            new_count=1,
            notified_count=1,
        )
        db.insert_run_log(
            conn,
            command="check-mail",
            status="completed",
            account="primary@example.com",
            provider="gmail",
            started_at="2026-06-29T00:00:00+00:00",
            finished_at="2026-06-29T00:00:03+00:00",
            new_count=2,
        )
        db.insert_run_log(
            conn,
            command="notify-new",
            status="failed",
            account="primary@example.com",
            provider="gmail",
            started_at="2026-06-30T00:00:00+00:00",
            finished_at="2026-06-30T00:00:03+00:00",
            error_phase="telegram_send",
            error_type="RuntimeError",
            error="Telegram unavailable",
        )
        db.insert_run_log(
            conn,
            command="notify-new",
            status="completed",
            account="primary@example.com",
            provider="gmail",
            started_at="2026-07-01T00:00:00+00:00",
            finished_at="2026-07-01T00:00:03+00:00",
            new_count=3,
            notified_count=3,
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    with _web_server() as base_url:
        payload = _get_json(
            f"{base_url}/api/run-log-events"
            "?command=check-mail&status=completed"
            "&finished_from=2026-06-29&finished_to=2026-06-30"
        )
        html = _get_text(
            f"{base_url}/"
            "?command=check-mail&status=completed"
            "&finished_from=2026-06-29&finished_to=2026-06-30"
        )

    assert payload["exists"] is True
    assert payload["readable"] is True
    assert payload["filters"] == {
        "command": "check-mail",
        "finished_from": "2026-06-29",
        "finished_to": "2026-06-30",
        "status": "completed",
    }
    assert [row["command"] for row in payload["run_log_events"]] == ["check-mail"]
    assert "Run Log Events" in html
    assert "check-mail" in html
    assert 'name="command" value="check-mail"' in html
    assert 'name="finished_from" value="2026-06-29"' in html
    assert 'name="finished_to" value="2026-06-30"' in html


def test_web_api_audit_events_and_message_stats_are_readonly_get_endpoints(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.save_message(
            conn,
            _message(
                uid="uid-1",
                sender="alerts@example.com",
                date="2026-06-29T10:00:00+00:00",
            ),
        )
        db.save_message(
            conn,
            _message(
                uid="uid-2",
                sender="alerts@example.com",
                date="2026-06-29T11:00:00+00:00",
            ),
        )
        db.save_message(
            conn,
            _message(
                uid="uid-3",
                sender="boss@example.com",
                date="2026-06-30T08:00:00+00:00",
            ),
        )
        log_event(
            conn,
            action="read_new_message",
            status="completed",
            reason="classified locally",
            account="iva196464@gmail.com",
            message_uid="uid-3",
            metadata={"importance": "high"},
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    with _web_server() as base_url:
        audit = _get_json(f"{base_url}/api/audit-events?limit=5")
        stats = _get_json(f"{base_url}/api/message-stats?limit=5")
        html = _get_text(f"{base_url}/audit")

    assert audit["exists"] is True
    assert audit["readable"] is True
    assert audit["audit_events"][0]["action"] == "read_new_message"
    assert audit["audit_events"][0]["metadata"] == {"importance": "high"}
    assert stats["exists"] is True
    assert stats["readable"] is True
    assert stats["filters"]["sender_limit"] == 5
    assert stats["total_messages"] == 3
    assert stats["messages_by_day"] == [
        {"count": 1, "day": "2026-06-30"},
        {"count": 2, "day": "2026-06-29"},
    ]
    assert stats["top_senders"][0]["sender"] == "alerts@example.com"
    assert stats["top_senders"][0]["count"] == 2
    assert "Mail Agent Audit" in html
    assert "Recent Audit Events" in html
    assert "Messages By Day" in html
    assert "alerts@example.com" in html


def test_web_api_filters_audit_events_by_action_status_and_account(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        log_event(
            conn,
            action="read_new_message",
            status="completed",
            reason="matching event",
            account="primary@example.com",
            message_uid="uid-1",
        )
        log_event(
            conn,
            action="read_new_message",
            status="failed",
            reason="wrong status",
            account="primary@example.com",
            message_uid="uid-2",
        )
        log_event(
            conn,
            action="read_message",
            status="completed",
            reason="wrong action",
            account="primary@example.com",
            message_uid="uid-3",
        )
        log_event(
            conn,
            action="read_new_message",
            status="completed",
            reason="wrong account",
            account="secondary@example.com",
            message_uid="uid-4",
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    with _web_server() as base_url:
        audit = _get_json(
            f"{base_url}/api/audit-events"
            "?action=read_new_message&status=completed&account=primary@example.com"
        )
        html = _get_text(
            f"{base_url}/audit"
            "?action=read_new_message&status=completed&account=primary@example.com"
        )

    assert audit["filters"] == {
        "account": "primary@example.com",
        "action": "read_new_message",
        "status": "completed",
    }
    assert [row["message_uid"] for row in audit["audit_events"]] == ["uid-1"]
    assert "matching event" in html
    assert "wrong status" not in html


def test_web_api_filters_message_stats_by_date_range(monkeypatch, tmp_path):
    db_path = tmp_path / "mail.sqlite3"
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.save_message(
            conn,
            _message(
                uid="uid-1",
                sender="old@example.com",
                date="2026-06-28T10:00:00+00:00",
            ),
        )
        db.save_message(
            conn,
            _message(
                uid="uid-2",
                sender="inside@example.com",
                date="2026-06-29T11:00:00+00:00",
            ),
        )
        db.save_message(
            conn,
            _message(
                uid="uid-3",
                sender="inside@example.com",
                date="2026-06-30T08:00:00+00:00",
            ),
        )
        db.save_message(
            conn,
            _message(
                uid="uid-4",
                sender="future@example.com",
                date="2026-07-01T08:00:00+00:00",
            ),
        )

    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    with _web_server() as base_url:
        stats = _get_json(
            f"{base_url}/api/message-stats"
            "?sender_limit=1&date_from=2026-06-29&date_to=2026-06-30"
        )
        html = _get_text(
            f"{base_url}/audit"
            "?sender_limit=1&date_from=2026-06-29&date_to=2026-06-30"
        )

    assert stats["filters"] == {
        "date_from": "2026-06-29",
        "date_to": "2026-06-30",
        "sender_limit": 1,
    }
    assert stats["total_messages"] == 2
    assert stats["messages_by_day"] == [
        {"count": 1, "day": "2026-06-30"},
        {"count": 1, "day": "2026-06-29"},
    ]
    assert stats["top_senders"] == [
        {
            "count": 2,
            "latest_created_at": stats["top_senders"][0]["latest_created_at"],
            "sender": "inside@example.com",
        }
    ]
    assert 'name="sender_limit" value="1"' in html


def test_web_api_handles_missing_db_without_creating_it(monkeypatch, tmp_path):
    db_path = tmp_path / "missing-dir" / "missing.sqlite3"
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    with _web_server() as base_url:
        health = _get_json(f"{base_url}/api/health")
        runs = _get_json(f"{base_url}/api/runs?limit=10")
        audit = _get_json(
            f"{base_url}/api/audit-events"
            "?limit=10&action=read_new_message&status=completed&account=missing@example.com"
        )
        stats = _get_json(
            f"{base_url}/api/message-stats"
            "?sender_limit=7&date_from=2026-06-29&date_to=2026-06-30"
        )
        run_log = _get_json(
            f"{base_url}/api/run-log-events"
            "?limit=10&command=notify-new&status=failed"
            "&finished_from=2026-06-29&finished_to=2026-06-30"
        )
        review = _get_json(
            f"{base_url}/api/operational-review?limit=10&sender_limit=7"
        )
        review_html = _get_text(f"{base_url}/review?limit=10&sender_limit=7")
        html = _get_text(
            f"{base_url}/audit"
            "?action=read_new_message&date_from=2026-06-29&date_to=2026-06-30"
        )

    assert db_path.exists() is False
    assert db_path.parent.exists() is False
    assert health["db"]["exists"] is False
    assert health["db"]["readable"] is False
    assert health["runs"] == []
    assert runs["runs"] == []
    assert audit["exists"] is False
    assert audit["filters"] == {
        "account": "missing@example.com",
        "action": "read_new_message",
        "status": "completed",
    }
    assert audit["readable"] is False
    assert audit["audit_events"] == []
    assert stats["exists"] is False
    assert stats["filters"] == {
        "date_from": "2026-06-29",
        "date_to": "2026-06-30",
        "sender_limit": 7,
    }
    assert stats["readable"] is False
    assert stats["messages_by_day"] == []
    assert stats["top_senders"] == []
    assert run_log["exists"] is False
    assert run_log["filters"] == {
        "command": "notify-new",
        "finished_from": "2026-06-29",
        "finished_to": "2026-06-30",
        "status": "failed",
    }
    assert run_log["readable"] is False
    assert run_log["run_log_events"] == []
    assert review["status"] == "warning"
    assert review["risk"] == "medium"
    assert review["db"]["exists"] is False
    assert "Mail Agent Operational Review" in review_html
    assert "db_missing" in review_html
    assert "Diagnostic Read-only" in review_html
    assert "Mail Agent Audit" in html


def test_web_smoke_all_readonly_endpoints_do_not_create_missing_db_or_call_side_effects(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "missing-dir" / "missing.sqlite3"
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))

    def fail_side_effect(*args, **kwargs):
        raise AssertionError("external side effect should not be called")

    monkeypatch.setattr(subprocess, "run", fail_side_effect)

    from mail_agent.mail import gmail_api
    from mail_agent import telegram_bot

    monkeypatch.setattr(gmail_api.GmailApiClient, "__init__", fail_side_effect)
    monkeypatch.setattr(gmail_api.GmailApiClient, "authorize", fail_side_effect)
    monkeypatch.setattr(telegram_bot, "send_summary", fail_side_effect)
    monkeypatch.setattr(telegram_bot, "send_pending_summary", fail_side_effect)
    monkeypatch.setattr(telegram_bot, "send_text", fail_side_effect)
    monkeypatch.setattr(telegram_bot, "print_chat_ids", fail_side_effect)
    monkeypatch.setattr(telegram_bot, "run_bot", fail_side_effect)

    with _web_server() as base_url:
        dashboard = _get_text(
            f"{base_url}/?command=notify-new&status=failed"
            "&finished_from=2026-06-29&finished_to=2026-06-30"
        )
        audit_html = _get_text(
            f"{base_url}/audit?action=read_new_message&status=completed"
            "&account=missing@example.com&sender_limit=3"
            "&date_from=2026-06-29&date_to=2026-06-30"
        )
        review_html = _get_text(f"{base_url}/review?limit=2&sender_limit=3")
        health = _get_json(f"{base_url}/api/health?limit=2")
        runs = _get_json(f"{base_url}/api/runs?limit=2")
        audit = _get_json(
            f"{base_url}/api/audit-events"
            "?limit=2&action=read_new_message&status=completed"
            "&account=missing@example.com"
        )
        stats = _get_json(
            f"{base_url}/api/message-stats"
            "?sender_limit=3&date_from=2026-06-29&date_to=2026-06-30"
        )
        run_log = _get_json(
            f"{base_url}/api/run-log-events"
            "?limit=2&command=notify-new&status=failed"
            "&finished_from=2026-06-29&finished_to=2026-06-30"
        )
        review = _get_json(
            f"{base_url}/api/operational-review?limit=2&sender_limit=3"
        )

    assert db_path.exists() is False
    assert db_path.parent.exists() is False
    assert "Mail Agent Panel" in dashboard
    assert '<link rel="icon" href="data:,">' in dashboard
    assert "Run Log Events" in dashboard
    assert 'name="command" value="notify-new"' in dashboard
    assert "Mail Agent Audit" in audit_html
    assert 'href="/review"' in audit_html
    assert '<link rel="icon" href="data:,">' in audit_html
    assert 'type="hidden" name="action" value="read_new_message"' in audit_html
    assert 'type="hidden" name="status" value="completed"' in audit_html
    assert 'type="hidden" name="account" value="missing@example.com"' in audit_html
    assert 'type="hidden" name="date_from" value="2026-06-29"' in audit_html
    assert 'type="hidden" name="date_to" value="2026-06-30"' in audit_html
    assert 'name="sender_limit" value="3"' in audit_html
    assert "input.type !== 'hidden'" in audit_html
    assert "Mail Agent Operational Review" in review_html
    assert '<link rel="icon" href="data:,">' in review_html
    assert "No run log events recorded." in review_html
    assert "No senders recorded." in review_html
    assert "Sender Limit" in review_html
    assert ">3<" in review_html
    assert health["db"]["exists"] is False
    assert health["db"]["readable"] is False
    assert health["scheduler"] is None
    assert runs["runs"] == []
    assert audit["audit_events"] == []
    assert audit["filters"] == {
        "account": "missing@example.com",
        "action": "read_new_message",
        "status": "completed",
    }
    assert stats["filters"] == {
        "date_from": "2026-06-29",
        "date_to": "2026-06-30",
        "sender_limit": 3,
    }
    assert stats["top_senders"] == []
    assert run_log["filters"] == {
        "command": "notify-new",
        "finished_from": "2026-06-29",
        "finished_to": "2026-06-30",
        "status": "failed",
    }
    assert run_log["run_log_events"] == []
    assert review["safety"] == {
        "diagnostic_read_only": True,
        "gmail_called": False,
        "scheduler_checked": False,
        "scheduler_modified": False,
        "telegram_called": False,
    }
    assert review["local_activity"]["message_stats"]["filters"]["sender_limit"] == 3


def test_web_api_operational_review_rejects_invalid_params(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(tmp_path / "missing.sqlite3"))

    with _web_server() as base_url:
        try:
            _get_text(f"{base_url}/api/operational-review?limit=0")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            limit_payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("Expected HTTP 400")

        try:
            _get_text(f"{base_url}/api/operational-review?sender_limit=0")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            sender_limit_payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("Expected HTTP 400")

    assert limit_payload == {"error": "limit must be at least 1"}
    assert sender_limit_payload == {"error": "sender_limit must be at least 1"}


def test_web_api_rejects_invalid_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(tmp_path / "missing.sqlite3"))

    with _web_server() as base_url:
        try:
            _get_text(f"{base_url}/api/runs?limit=0")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("Expected HTTP 400")

    assert payload == {"error": "limit must be at least 1"}


def test_web_api_rejects_invalid_sender_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(tmp_path / "missing.sqlite3"))

    with _web_server() as base_url:
        try:
            _get_text(f"{base_url}/api/message-stats?sender_limit=0")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("Expected HTTP 400")

    assert payload == {"error": "sender_limit must be at least 1"}


def test_web_api_rejects_invalid_run_log_finished_range(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(tmp_path / "missing.sqlite3"))

    with _web_server() as base_url:
        try:
            _get_text(
                f"{base_url}/api/run-log-events"
                "?finished_from=2026-07-01&finished_to=2026-06-30"
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("Expected HTTP 400")

    assert payload == {"error": "finished_from must be on or before finished_to"}


def test_web_favicon_is_empty_success_response(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(tmp_path / "missing.sqlite3"))

    with _web_server() as base_url:
        with urllib.request.urlopen(f"{base_url}/favicon.ico", timeout=5) as response:
            body = response.read()

    assert response.status == 204
    assert body == b""


def test_web_bind_host_defaults_to_loopback(monkeypatch):
    called = {}

    def fake_run_web_server(*, host: str, port: int) -> None:
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr(sys, "argv", ["mail-agent", "web"])
    monkeypatch.setattr("mail_agent.web.run_web_server", fake_run_web_server)

    cli.main()

    assert called == {"host": "127.0.0.1", "port": 8765}


def test_web_rejects_non_loopback_bind_host_without_explicit_allow(monkeypatch):
    def fail_run_web_server(*, host: str, port: int) -> None:
        raise AssertionError("web server should not start for unsafe host")

    monkeypatch.setattr(
        sys,
        "argv",
        ["mail-agent", "web", "--host", "0.0.0.0"],
    )
    monkeypatch.setattr("mail_agent.web.run_web_server", fail_run_web_server)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert "refusing to bind" in str(exc_info.value)
    assert "--allow-non-loopback" in str(exc_info.value)


def test_web_allows_non_loopback_bind_host_with_explicit_allow(monkeypatch):
    called = {}

    def fake_run_web_server(*, host: str, port: int) -> None:
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mail-agent",
            "web",
            "--host",
            "0.0.0.0",
            "--port",
            "8766",
            "--allow-non-loopback",
        ],
    )
    monkeypatch.setattr("mail_agent.web.run_web_server", fake_run_web_server)

    cli.main()

    assert called == {"host": "0.0.0.0", "port": 8766}


def test_web_loopback_bind_host_detection():
    assert is_loopback_bind_host("127.0.0.1") is True
    assert is_loopback_bind_host("localhost") is True
    assert is_loopback_bind_host("::1") is True
    assert is_loopback_bind_host("0.0.0.0") is False
    assert is_loopback_bind_host("192.168.1.10") is False


def _message(uid: str, sender: str, date: str) -> NormalizedMessage:
    return NormalizedMessage(
        provider=Provider.GMAIL,
        account="iva196464@gmail.com",
        message_uid=uid,
        message_id=f"<{uid}@example.com>",
        thread_id=None,
        sender=sender,
        recipients=["iva196464@gmail.com"],
        subject="Test message",
        date=date,
        text="Body",
        html="",
        headers={},
    )


class _web_server:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MailAgentWebHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def _get_json(url: str) -> dict:
    return json.loads(_get_text(url))


def _get_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _iso_seconds_ago(seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


def _finding(payload: dict, code: str) -> dict:
    for finding in payload["findings"]:
        if finding["code"] == code:
            return finding
    raise AssertionError(f"missing finding {code}")
