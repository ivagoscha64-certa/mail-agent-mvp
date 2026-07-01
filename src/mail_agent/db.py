from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from mail_agent.models import Classification, NormalizedMessage, utc_now_iso


SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        record_schema_version(conn)


def record_schema_version(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO schema_metadata(metadata_key, metadata_value)
        VALUES ('schema_version', ?)
        ON CONFLICT(metadata_key) DO UPDATE SET
            metadata_value = excluded.metadata_value
        """,
        (str(SCHEMA_VERSION),),
    )


def upsert_account(conn: sqlite3.Connection, provider: str, email: str, mode: str) -> None:
    conn.execute(
        """
        INSERT INTO accounts(provider, email, mode, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            provider = excluded.provider,
            mode = excluded.mode,
            is_active = 1
        """,
        (provider, email, mode, utc_now_iso()),
    )


def save_message(conn: sqlite3.Connection, message: NormalizedMessage) -> int:
    conn.execute(
        """
        INSERT OR IGNORE INTO messages(
            provider, account, message_uid, message_id, thread_id, sender,
            recipients_json, subject, message_date, text, html, headers_json,
            attachments_json, links_json, folder, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.provider.value,
            message.account,
            message.message_uid,
            message.message_id,
            message.thread_id,
            message.sender,
            json.dumps(message.recipients, ensure_ascii=False),
            message.subject,
            message.date,
            message.text,
            message.html,
            json.dumps(message.headers, ensure_ascii=False),
            json.dumps(message.attachments, ensure_ascii=False),
            json.dumps(message.links, ensure_ascii=False),
            message.folder,
            utc_now_iso(),
        ),
    )
    row = conn.execute(
        """
        SELECT id FROM messages
        WHERE provider = ? AND account = ? AND message_uid = ?
        """,
        (message.provider.value, message.account, message.message_uid),
    ).fetchone()
    return int(row["id"])


def message_exists(
    conn: sqlite3.Connection, *, provider: str, account: str, message_uid: str
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM messages
        WHERE provider = ? AND account = ? AND message_uid = ?
        """,
        (provider, account, message_uid),
    ).fetchone()
    return row is not None


def save_classification(
    conn: sqlite3.Connection, message_row_id: int, classification: Classification
) -> None:
    conn.execute(
        """
        INSERT INTO message_classifications(
            message_row_id, importance, action, risk, message_type, reason, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_row_id,
            classification.importance.value,
            classification.action.value,
            classification.risk.value,
            classification.message_type.value,
            classification.reason,
            utc_now_iso(),
        ),
    )


IMPORTANT_MESSAGE_SQL = """
WITH latest_classifications AS (
    SELECT c.*
    FROM message_classifications c
    JOIN (
        SELECT message_row_id, MAX(id) AS latest_id
        FROM message_classifications
        GROUP BY message_row_id
    ) latest ON latest.latest_id = c.id
)
SELECT
    m.id AS message_row_id,
    m.account,
    m.sender,
    m.subject,
    m.message_date,
    m.message_uid,
    c.importance,
    c.action,
    c.risk,
    c.message_type,
    c.reason
FROM messages m
JOIN latest_classifications c ON c.message_row_id = m.id
WHERE (
    c.importance IN ('high', 'medium')
    OR c.action IN ('spam_review', 'unsubscribe_candidate')
)
"""


def ensure_telegram_notification_baseline(
    conn: sqlite3.Connection, *, chat_id: str
) -> int:
    existing = conn.execute(
        "SELECT COUNT(*) FROM telegram_notifications WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()[0]
    if existing:
        return 0

    now = utc_now_iso()
    rows = conn.execute(IMPORTANT_MESSAGE_SQL).fetchall()
    conn.executemany(
        """
        INSERT OR IGNORE INTO telegram_notifications(
            message_row_id, account, chat_id, status, sent_at, created_at
        )
        VALUES (?, ?, ?, 'baseline_skipped', ?, ?)
        """,
        [(row["message_row_id"], row["account"], chat_id, now, now) for row in rows],
    )
    return len(rows)


def fetch_pending_telegram_notifications(
    conn: sqlite3.Connection, *, chat_id: str, limit: int
) -> list[sqlite3.Row]:
    return conn.execute(
        IMPORTANT_MESSAGE_SQL
        + """
AND NOT EXISTS (
    SELECT 1
    FROM telegram_notifications n
    WHERE n.message_row_id = m.id
      AND n.chat_id = ?
)
ORDER BY m.id DESC
LIMIT ?
""",
        (chat_id, limit),
    ).fetchall()


def mark_telegram_notifications_sent(
    conn: sqlite3.Connection, *, rows: Iterable[sqlite3.Row], chat_id: str
) -> int:
    now = utc_now_iso()
    items = [
        (row["message_row_id"], row["account"], chat_id, "sent", now, now)
        for row in rows
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO telegram_notifications(
            message_row_id, account, chat_id, status, sent_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        items,
    )
    return len(items)


def insert_run_log(
    conn: sqlite3.Connection,
    *,
    command: str,
    status: str,
    account: str,
    provider: str,
    started_at: str,
    finished_at: str,
    limit_value: int | None = None,
    new_count: int = 0,
    existing_count: int = 0,
    notified_count: int = 0,
    error_phase: str | None = None,
    error_type: str | None = None,
    error: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO run_log(
            command, status, account, provider, started_at, finished_at, limit_value,
            new_count, existing_count, notified_count, error_phase, error_type, error,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            command,
            status,
            account,
            provider,
            started_at,
            finished_at,
            limit_value,
            new_count,
            existing_count,
            notified_count,
            error_phase,
            error_type,
            error,
            utc_now_iso(),
        ),
    )
    return int(cursor.lastrowid)


def fetch_latest_run_log(
    conn: sqlite3.Connection, *, command: str | None = None
) -> sqlite3.Row | None:
    if command is None:
        return conn.execute(
            """
            SELECT *
            FROM run_log
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    return conn.execute(
        """
        SELECT *
        FROM run_log
        WHERE command = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (command,),
    ).fetchone()


def fetch_latest_successful_run_log(
    conn: sqlite3.Connection, *, command: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM run_log
        WHERE command = ?
          AND status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (command,),
    ).fetchone()


def fetch_run_logs(
    conn: sqlite3.Connection, *, command: str, limit: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM run_log
        WHERE command = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (command, limit),
    ).fetchall()
