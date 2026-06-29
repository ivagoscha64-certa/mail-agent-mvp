from __future__ import annotations

from email.message import EmailMessage, Message
from email.utils import getaddresses
from html.parser import HTMLParser

from mail_agent.models import NormalizedMessage, Provider


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)


def _payload_text(message: Message, content_type: str) -> str:
    if message.is_multipart():
        parts = [
            _payload_text(part, content_type)
            for part in message.walk()
            if part.get_content_type() == content_type
            and part.get_content_disposition() != "attachment"
        ]
        return "\n".join(part for part in parts if part)

    if message.get_content_type() != content_type:
        return ""

    payload = message.get_payload(decode=True)
    if not payload:
        return ""
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def normalize_mailru_message(
    *,
    account: str,
    uid: str,
    folder: str,
    message: EmailMessage,
) -> NormalizedMessage:
    html = _payload_text(message, "text/html")
    link_extractor = LinkExtractor()
    if html:
        link_extractor.feed(html)

    recipients = [
        address
        for _, address in getaddresses(message.get_all("to", []))
        if address
    ]
    headers = {key: value for key, value in message.items()}

    return NormalizedMessage(
        provider=Provider.MAILRU,
        account=account,
        message_uid=uid,
        message_id=message.get("Message-ID"),
        thread_id=message.get("In-Reply-To") or message.get("References"),
        sender=message.get("From", ""),
        recipients=recipients,
        subject=message.get("Subject", ""),
        date=message.get("Date"),
        text=_payload_text(message, "text/plain"),
        html=html,
        headers=headers,
        attachments=[
            {
                "filename": part.get_filename(),
                "content_type": part.get_content_type(),
            }
            for part in message.walk()
            if part.get_content_disposition() == "attachment"
        ],
        links=link_extractor.links,
        folder=folder,
    )

