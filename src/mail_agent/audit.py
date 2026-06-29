from __future__ import annotations

import json
import sqlite3
from typing import Any

from mail_agent.models import utc_now_iso


def log_event(
    conn: sqlite3.Connection,
    *,
    action: str,
    status: str,
    reason: str,
    account: str | None = None,
    message_uid: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log(
            account, message_uid, action, status, reason, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account,
            message_uid,
            action,
            status,
            reason,
            json.dumps(metadata or {}, ensure_ascii=False),
            utc_now_iso(),
        ),
    )

