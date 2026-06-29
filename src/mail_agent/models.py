from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class AgentMode(StrEnum):
    READ_ONLY = "read_only"


class Provider(StrEnum):
    MAILRU = "mailru"


class Importance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Risk(StrEnum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"


class MessageType(StrEnum):
    PERSONAL = "personal"
    WORK = "work"
    FINANCE = "finance"
    SERVICE = "service"
    NEWSLETTER = "newsletter"
    PROMO = "promo"
    SOCIAL = "social"
    SECURITY = "security"
    UNKNOWN = "unknown"


class RecommendedAction(StrEnum):
    IGNORE = "ignore"
    NOTIFY = "notify"
    DRAFT_REPLY = "draft_reply"
    CLEANUP_CANDIDATE = "cleanup_candidate"
    UNSUBSCRIBE_CANDIDATE = "unsubscribe_candidate"
    SPAM_REVIEW = "spam_review"


class UnsafeAction(StrEnum):
    SEND_EMAIL = "send_email"
    DELETE_EMAIL = "delete_email"
    MOVE_EMAIL = "move_email"
    MARK_SPAM = "mark_spam"
    UNSUBSCRIBE = "unsubscribe"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class NormalizedMessage:
    provider: Provider
    account: str
    message_uid: str
    message_id: str | None
    thread_id: str | None
    sender: str
    recipients: list[str]
    subject: str
    date: str | None
    text: str
    html: str
    headers: dict[str, str]
    attachments: list[dict[str, Any]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    folder: str = "INBOX"


@dataclass(frozen=True)
class Classification:
    importance: Importance
    action: RecommendedAction
    risk: Risk
    message_type: MessageType
    reason: str

