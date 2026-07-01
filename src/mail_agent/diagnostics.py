from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from mail_agent import db


SchedulerFetcher = Callable[[str], dict]

NOTIFY_NEW_SUCCESS_WARNING_AFTER_SECONDS = 1800
NOTIFY_NEW_SUCCESS_CRITICAL_AFTER_SECONDS = 7200
DIAGNOSTIC_SCHEMA_VERSION = 1
EXPECTED_SCHEMA_TABLES = [
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
]


def active_provider(settings) -> str:
    if settings.mail_backend == "gmail_api":
        return settings.gmail_api.provider
    return settings.imap_account.provider


def active_account_email(settings) -> str:
    if settings.mail_backend == "gmail_api":
        return settings.gmail_api.account_email
    return settings.imap_account.account_email


def build_runs_payload(settings, *, limit: int) -> dict:
    payload = {
        "db": str(settings.db_path),
        "last_successful_notify_run": None,
        "runs": [],
    }

    if not settings.db_path.exists():
        return payload

    with connect_readonly(settings.db_path) as conn:
        run_rows = db.fetch_run_logs(conn, command="notify-new", limit=limit)
        latest_successful_notify_run = db.fetch_latest_successful_run_log(
            conn,
            command="notify-new",
        )
        payload["last_successful_notify_run"] = (
            run_log_row_to_dict(latest_successful_notify_run)
            if latest_successful_notify_run
            else None
        )
        payload["runs"] = [run_log_row_to_dict(row) for row in run_rows]
    return payload


def build_run_log_events_payload(
    settings,
    *,
    limit: int,
    command: str | None = None,
    status: str | None = None,
    finished_from: str | None = None,
    finished_to: str | None = None,
) -> dict:
    filters = {
        "command": _clean_filter(command),
        "finished_from": _clean_date_filter(finished_from, name="finished_from"),
        "finished_to": _clean_date_filter(finished_to, name="finished_to"),
        "status": _clean_filter(status),
    }
    if (
        filters["finished_from"]
        and filters["finished_to"]
        and filters["finished_from"] > filters["finished_to"]
    ):
        raise ValueError("finished_from must be on or before finished_to")

    payload = {
        "db": str(settings.db_path),
        "exists": settings.db_path.exists(),
        "filters": filters,
        "readable": False,
        "error": None,
        "error_type": None,
        "run_log_events": [],
    }

    if not settings.db_path.exists():
        return payload

    try:
        with connect_readonly(settings.db_path) as conn:
            clauses = []
            params: list[str | int] = []
            if filters["command"]:
                clauses.append("command = ?")
                params.append(filters["command"])
            if filters["status"]:
                clauses.append("status = ?")
                params.append(filters["status"])
            if filters["finished_from"]:
                clauses.append("SUBSTR(finished_at, 1, 10) >= ?")
                params.append(filters["finished_from"])
            if filters["finished_to"]:
                clauses.append("SUBSTR(finished_at, 1, 10) <= ?")
                params.append(filters["finished_to"])
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT *
                FROM run_log
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            payload["run_log_events"] = [run_log_row_to_dict(row) for row in rows]
            payload["readable"] = True
    except sqlite3.Error as exc:
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)

    return payload


def build_audit_events_payload(
    settings,
    *,
    limit: int,
    action: str | None = None,
    status: str | None = None,
    account: str | None = None,
) -> dict:
    filters = {
        "account": _clean_filter(account),
        "action": _clean_filter(action),
        "status": _clean_filter(status),
    }
    payload = {
        "audit_events": [],
        "db": str(settings.db_path),
        "exists": settings.db_path.exists(),
        "filters": filters,
        "readable": False,
        "error": None,
        "error_type": None,
    }

    if not settings.db_path.exists():
        return payload

    try:
        with connect_readonly(settings.db_path) as conn:
            clauses = []
            params: list[str | int] = []
            for column in ("account", "action", "status"):
                if filters[column]:
                    clauses.append(f"{column} = ?")
                    params.append(filters[column])
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT id, account, message_uid, action, status, reason,
                       metadata_json, created_at
                FROM audit_log
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            payload["audit_events"] = [audit_event_row_to_dict(row) for row in rows]
            payload["readable"] = True
    except sqlite3.Error as exc:
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)

    return payload


def build_message_stats_payload(
    settings,
    *,
    sender_limit: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    filters = {
        "date_from": _clean_date_filter(date_from, name="date_from"),
        "date_to": _clean_date_filter(date_to, name="date_to"),
        "sender_limit": sender_limit,
    }
    if (
        filters["date_from"]
        and filters["date_to"]
        and filters["date_from"] > filters["date_to"]
    ):
        raise ValueError("date_from must be on or before date_to")

    payload = {
        "db": str(settings.db_path),
        "exists": settings.db_path.exists(),
        "filters": filters,
        "readable": False,
        "error": None,
        "error_type": None,
        "messages_by_day": [],
        "top_senders": [],
        "total_messages": None,
    }

    if not settings.db_path.exists():
        return payload

    try:
        with connect_readonly(settings.db_path) as conn:
            day_expr = "COALESCE(SUBSTR(message_date, 1, 10), SUBSTR(created_at, 1, 10))"
            clauses = []
            params: list[str | int] = []
            if filters["date_from"]:
                clauses.append(f"{day_expr} >= ?")
                params.append(filters["date_from"])
            if filters["date_to"]:
                clauses.append(f"{day_expr} <= ?")
                params.append(filters["date_to"])
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            payload["total_messages"] = conn.execute(
                f"SELECT COUNT(*) FROM messages {where_sql}",
                params,
            ).fetchone()[0]
            by_day_rows = conn.execute(
                f"""
                SELECT {day_expr} AS day,
                       COUNT(*) AS count
                FROM messages
                {where_sql}
                GROUP BY day
                ORDER BY day DESC
                """,
                params,
            ).fetchall()
            sender_rows = conn.execute(
                f"""
                SELECT sender, COUNT(*) AS count, MAX(created_at) AS latest_created_at
                FROM messages
                {where_sql}
                GROUP BY sender
                ORDER BY count DESC, latest_created_at DESC, sender ASC
                LIMIT ?
                """,
                [*params, sender_limit],
            ).fetchall()
            payload["messages_by_day"] = [
                {"count": row["count"], "day": row["day"]} for row in by_day_rows
            ]
            payload["top_senders"] = [
                {
                    "count": row["count"],
                    "latest_created_at": row["latest_created_at"],
                    "sender": row["sender"],
                }
                for row in sender_rows
            ]
            payload["readable"] = True
    except sqlite3.Error as exc:
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)

    return payload


def build_operational_review_payload(
    settings,
    *,
    limit: int,
    sender_limit: int,
) -> dict:
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    health = build_health_payload(
        settings,
        run_limit=limit,
        include_scheduler=False,
        scheduler_task_name="MailAgentNotifyNew",
    )
    stats = build_message_stats_payload(settings, sender_limit=sender_limit)
    run_log = build_run_log_events_payload(settings, limit=limit)

    findings: list[dict] = []
    db_info = health["db"]
    latest_notify_run = health["latest_notify_run"]
    last_successful_notify_run = health["last_successful_notify_run"]
    last_successful_age_seconds = _notify_new_success_age_seconds(
        generated_at,
        last_successful_notify_run,
    )

    if not db_info["exists"]:
        findings.append(
            _review_finding(
                "warning",
                "db_missing",
                "SQLite DB is missing; diagnostics did not create it.",
            )
        )
    elif not db_info["readable"]:
        findings.append(
            _review_finding(
                "critical",
                "db_unreadable",
                (
                    "SQLite DB exists but could not be fully read: "
                    f"{db_info['error_type']}: {db_info['error']}"
                ),
            )
        )
    else:
        findings.append(
            _review_finding(
                "ok",
                "db_readable",
                "SQLite DB is present and readable in read-only mode.",
            )
        )

    if latest_notify_run and latest_notify_run["status"] == "failed":
        findings.append(
            _review_finding(
                "critical",
                "latest_notify_new_failed",
                (
                    "Latest notify-new run failed"
                    f" at {latest_notify_run['finished_at']}."
                ),
            )
        )
    elif latest_notify_run:
        findings.append(
            _review_finding(
                "ok",
                "latest_notify_new_completed",
                (
                    "Latest notify-new run completed"
                    f" at {latest_notify_run['finished_at']}."
                ),
            )
        )
    else:
        findings.append(
            _review_finding(
                "warning",
                "notify_new_never_recorded",
                "No notify-new run has been recorded in local SQLite.",
            )
        )

    if (
        db_info["readable"]
        and (not latest_notify_run or latest_notify_run["status"] != "failed")
    ):
        findings.append(
            _notify_new_success_age_finding(
                last_successful_age_seconds,
                last_successful_notify_run,
            )
        )

    status, risk = _review_status_and_risk(findings)
    return {
        "status": status,
        "risk": risk,
        "generated_at": generated_at,
        "thresholds": {
            "notify_new_success_warning_after_seconds": (
                NOTIFY_NEW_SUCCESS_WARNING_AFTER_SECONDS
            ),
            "notify_new_success_critical_after_seconds": (
                NOTIFY_NEW_SUCCESS_CRITICAL_AFTER_SECONDS
            ),
        },
        "config": {
            "account": active_account_email(settings),
            "backend": settings.mail_backend,
            "db_path": str(settings.db_path),
            "mode": settings.mode.value,
            "provider": active_provider(settings),
        },
        "safety": {
            "diagnostic_read_only": True,
            "gmail_called": False,
            "scheduler_checked": False,
            "scheduler_modified": False,
            "telegram_called": False,
        },
        "db": db_info,
        "notify_new": {
            "latest": latest_notify_run,
            "last_successful": last_successful_notify_run,
            "last_successful_age_seconds": last_successful_age_seconds,
            "recent_runs": health["runs"],
        },
        "local_activity": {
            "message_stats": stats,
            "run_log_events": run_log,
        },
        "findings": findings,
    }


def build_health_payload(
    settings,
    *,
    run_limit: int,
    include_scheduler: bool,
    scheduler_task_name: str,
    scheduler_fetcher: SchedulerFetcher | None = None,
) -> dict:
    payload = {
        "account": active_account_email(settings),
        "backend": settings.mail_backend,
        "db": {
            "audit_events": None,
            "error": None,
            "error_type": None,
            "exists": settings.db_path.exists(),
            "messages": None,
            "path": str(settings.db_path),
            "readable": False,
            "schema": _uninspected_schema_summary(),
        },
        "last_successful_notify_run": None,
        "latest_notify_run": None,
        "mode": settings.mode.value,
        "provider": active_provider(settings),
        "runs": [],
        "scheduler": None,
    }

    if settings.db_path.exists():
        try:
            with connect_readonly(settings.db_path) as conn:
                payload["db"]["schema"] = inspect_schema(conn)
                payload["db"]["messages"] = conn.execute(
                    "SELECT COUNT(*) FROM messages"
                ).fetchone()[0]
                payload["db"]["audit_events"] = conn.execute(
                    "SELECT COUNT(*) FROM audit_log"
                ).fetchone()[0]
                latest_notify_run = db.fetch_latest_run_log(conn, command="notify-new")
                latest_successful_notify_run = db.fetch_latest_successful_run_log(
                    conn,
                    command="notify-new",
                )
                payload["latest_notify_run"] = (
                    run_log_row_to_dict(latest_notify_run) if latest_notify_run else None
                )
                payload["last_successful_notify_run"] = (
                    run_log_row_to_dict(latest_successful_notify_run)
                    if latest_successful_notify_run
                    else None
                )
                payload["runs"] = [
                    run_log_row_to_dict(row)
                    for row in db.fetch_run_logs(
                        conn,
                        command="notify-new",
                        limit=run_limit,
                    )
                ]
                payload["db"]["readable"] = True
        except sqlite3.Error as exc:
            payload["db"]["error_type"] = type(exc).__name__
            payload["db"]["error"] = str(exc)

    if include_scheduler:
        if scheduler_fetcher is None:
            raise ValueError("scheduler_fetcher is required when include_scheduler=True")
        payload["scheduler"] = scheduler_fetcher(scheduler_task_name)

    return payload


def _notify_new_success_age_seconds(
    generated_at: str,
    last_successful_notify_run: dict | None,
) -> int | None:
    if not last_successful_notify_run:
        return None
    try:
        generated = _parse_iso_datetime(generated_at)
        finished = _parse_iso_datetime(last_successful_notify_run["finished_at"])
    except (TypeError, ValueError):
        return None
    return max(0, int((generated - finished).total_seconds()))


def _notify_new_success_age_finding(
    age_seconds: int | None,
    last_successful_notify_run: dict | None,
) -> dict:
    if not last_successful_notify_run:
        return _review_finding(
            "warning",
            "notify_new_success_missing",
            "No successful notify-new run has been recorded in local SQLite.",
            observed_seconds=None,
            threshold_seconds=NOTIFY_NEW_SUCCESS_WARNING_AFTER_SECONDS,
        )
    if age_seconds is None:
        return _review_finding(
            "warning",
            "notify_new_success_age_unknown",
            (
                "Last successful notify-new timestamp could not be parsed: "
                f"{last_successful_notify_run['finished_at']}."
            ),
            observed_seconds=None,
            threshold_seconds=NOTIFY_NEW_SUCCESS_WARNING_AFTER_SECONDS,
        )
    if age_seconds >= NOTIFY_NEW_SUCCESS_CRITICAL_AFTER_SECONDS:
        return _review_finding(
            "critical",
            "notify_new_success_critical_age",
            (
                "Last successful notify-new run is older than the critical "
                "threshold."
            ),
            observed_seconds=age_seconds,
            threshold_seconds=NOTIFY_NEW_SUCCESS_CRITICAL_AFTER_SECONDS,
        )
    if age_seconds >= NOTIFY_NEW_SUCCESS_WARNING_AFTER_SECONDS:
        return _review_finding(
            "warning",
            "notify_new_success_warning_age",
            (
                "Last successful notify-new run is older than the warning "
                "threshold."
            ),
            observed_seconds=age_seconds,
            threshold_seconds=NOTIFY_NEW_SUCCESS_WARNING_AFTER_SECONDS,
        )
    return _review_finding(
        "ok",
        "notify_new_success_fresh",
        "Last successful notify-new run is within the freshness threshold.",
        observed_seconds=age_seconds,
        threshold_seconds=NOTIFY_NEW_SUCCESS_WARNING_AFTER_SECONDS,
    )


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _review_finding(
    level: str,
    code: str,
    message: str,
    *,
    observed_seconds: int | None = None,
    threshold_seconds: int | None = None,
) -> dict:
    finding = {
        "code": code,
        "level": level,
        "message": message,
    }
    if observed_seconds is not None or threshold_seconds is not None:
        finding["observed_seconds"] = observed_seconds
        finding["threshold_seconds"] = threshold_seconds
    return finding


def _review_status_and_risk(findings: list[dict]) -> tuple[str, str]:
    levels = {finding["level"] for finding in findings}
    if "critical" in levels:
        return "critical", "high"
    if "warning" in levels:
        return "warning", "medium"
    return "ok", "low"


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri_path = quote(db_path.absolute().as_posix(), safe="/:")
    conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def inspect_schema(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    present_tables = [row["name"] for row in rows]
    missing_tables = [
        table for table in EXPECTED_SCHEMA_TABLES if table not in present_tables
    ]
    metadata_present = "schema_metadata" in present_tables
    detected_version = None
    if metadata_present:
        try:
            row = conn.execute(
                """
                SELECT metadata_value
                FROM schema_metadata
                WHERE metadata_key = 'schema_version'
                """
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            try:
                detected_version = int(row["metadata_value"])
            except (TypeError, ValueError):
                detected_version = None
    metadata_valid = detected_version == DIAGNOSTIC_SCHEMA_VERSION
    compatible = not missing_tables and detected_version == DIAGNOSTIC_SCHEMA_VERSION
    return {
        "compatible": compatible,
        "detected_version": detected_version,
        "expected_tables": EXPECTED_SCHEMA_TABLES,
        "expected_version": DIAGNOSTIC_SCHEMA_VERSION,
        "inspected": True,
        "metadata_present": metadata_present,
        "metadata_valid": metadata_valid,
        "missing_tables": missing_tables,
        "present_tables": present_tables,
    }


def _uninspected_schema_summary() -> dict:
    return {
        "compatible": None,
        "detected_version": None,
        "expected_tables": EXPECTED_SCHEMA_TABLES,
        "expected_version": DIAGNOSTIC_SCHEMA_VERSION,
        "inspected": False,
        "metadata_present": False,
        "metadata_valid": False,
        "missing_tables": [],
        "present_tables": [],
    }


def audit_event_row_to_dict(row) -> dict:
    return {
        "account": row["account"],
        "action": row["action"],
        "created_at": row["created_at"],
        "id": row["id"],
        "message_uid": row["message_uid"],
        "metadata": _decode_metadata(row["metadata_json"]),
        "reason": row["reason"],
        "status": row["status"],
    }


def run_log_row_to_dict(row) -> dict:
    return {
        "account": row["account"],
        "command": row["command"],
        "error": row["error"],
        "error_phase": row["error_phase"],
        "error_type": row["error_type"],
        "existing_count": row["existing_count"],
        "finished_at": row["finished_at"],
        "id": row["id"],
        "limit": row["limit_value"],
        "new_count": row["new_count"],
        "notified_count": row["notified_count"],
        "provider": row["provider"],
        "started_at": row["started_at"],
        "status": row["status"],
    }


def _decode_metadata(value: str) -> dict:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if isinstance(decoded, dict):
        return decoded
    return {}


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_date_filter(value: str | None, *, name: str) -> str | None:
    cleaned = _clean_filter(value)
    if cleaned is None:
        return None
    try:
        date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date: YYYY-MM-DD") from exc
    return cleaned
