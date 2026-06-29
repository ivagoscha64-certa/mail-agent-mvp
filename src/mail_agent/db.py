from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from mail_agent.models import Classification, NormalizedMessage, utc_now_iso


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


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

