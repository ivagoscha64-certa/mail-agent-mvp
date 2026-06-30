from __future__ import annotations

import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Iterator

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from mail_agent.config import GmailApiConfig
from mail_agent.models import Provider, UnsafeAction
from mail_agent.normalizer import normalize_imap_message
from mail_agent.safety import SafetyPolicy


class GmailApiClient:
    def __init__(self, config: GmailApiConfig, safety: SafetyPolicy) -> None:
        self.config = config
        self.safety = safety

    def authorize(self, *, open_browser: bool = True) -> None:
        credentials = load_or_create_credentials(self.config, open_browser=open_browser)
        self.config.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.token_path.write_text(credentials.to_json(), encoding="utf-8")

    def iter_recent_messages(self, *, limit: int = 50) -> Iterator:
        if not self.safety.can_read_mail:
            return

        credentials = load_or_create_credentials(self.config)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        result = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=limit)
            .execute()
        )
        for item in result.get("messages", []):
            raw_result = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="raw")
                .execute()
            )
            raw_message = _decode_gmail_raw(raw_result["raw"])
            parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
            if not isinstance(parsed, EmailMessage):
                parsed = EmailMessage(policy=policy.default)
                parsed.set_content(raw_message.decode("utf-8", errors="replace"))

            yield normalize_imap_message(
                provider=Provider.GMAIL,
                account=self.config.account_email,
                uid=raw_result["id"],
                folder="INBOX",
                message=parsed,
                thread_id=raw_result.get("threadId"),
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


def load_or_create_credentials(
    config: GmailApiConfig, *, open_browser: bool = True
) -> Credentials:
    credentials = _load_existing_token(config.token_path, config.scopes)
    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        config.token_path.parent.mkdir(parents=True, exist_ok=True)
        config.token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    if not config.credentials_path.exists():
        raise RuntimeError(
            "Gmail API credentials file is missing. Save the Google OAuth client "
            f"JSON as {config.credentials_path}."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.credentials_path),
        list(config.scopes),
    )
    return flow.run_local_server(port=0, open_browser=open_browser)


def _load_existing_token(token_path: Path, scopes: tuple[str, ...]) -> Credentials | None:
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path), list(scopes))


def _decode_gmail_raw(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)
