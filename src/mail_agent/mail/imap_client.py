from __future__ import annotations

import imaplib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Iterator

from mail_agent.config import ImapAccountConfig
from mail_agent.models import Provider, UnsafeAction
from mail_agent.normalizer import normalize_imap_message
from mail_agent.safety import SafetyPolicy


class ImapClient:
    def __init__(self, config: ImapAccountConfig, safety: SafetyPolicy) -> None:
        self.config = config
        self.safety = safety

    def iter_recent_messages(self, *, folder: str = "INBOX", limit: int = 50) -> Iterator:
        if not self.safety.can_read_mail:
            return

        provider = Provider(self.config.provider)
        with imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port) as imap:
            imap.login(self.config.imap_username, self.config.imap_password)
            imap.select(folder, readonly=True)
            status, data = imap.uid("search", None, "ALL")
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")

            uids = data[0].split()[-limit:]
            for raw_uid in reversed(uids):
                uid = raw_uid.decode("ascii", errors="replace")
                status, fetch_data = imap.uid("fetch", raw_uid, "(BODY.PEEK[])")
                if status != "OK":
                    raise RuntimeError(f"IMAP fetch failed for UID {uid}: {status}")

                raw_message = _extract_message_bytes(fetch_data)
                parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
                if not isinstance(parsed, EmailMessage):
                    parsed = EmailMessage(policy=policy.default)
                    parsed.set_content(raw_message.decode("utf-8", errors="replace"))

                yield normalize_imap_message(
                    provider=provider,
                    account=self.config.account_email,
                    uid=uid,
                    folder=folder,
                    message=parsed,
                )

    def send_email(self, *_args, **_kwargs) -> None:
        self.safety.assert_allowed(UnsafeAction.SEND_EMAIL)

    def delete_email(self, *_args, **_kwargs) -> None:
        self.safety.assert_allowed(UnsafeAction.DELETE_EMAIL)

    def move_email(self, *_args, **_kwargs) -> None:
        self.safety.assert_allowed(UnsafeAction.MOVE_EMAIL)

    def mark_spam(self, *_args, **_kwargs) -> None:
        self.safety.assert_allowed(UnsafeAction.MARK_SPAM)

    def unsubscribe(self, *_args, **_kwargs) -> None:
        self.safety.assert_allowed(UnsafeAction.UNSUBSCRIBE)


def _extract_message_bytes(fetch_data: list[bytes | tuple]) -> bytes:
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    raise RuntimeError("IMAP fetch response did not contain message bytes.")
