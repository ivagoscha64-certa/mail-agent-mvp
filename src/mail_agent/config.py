from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from mail_agent.models import AgentMode


DEFAULT_PROJECT_DIR = Path(r"E:\AI\mail-agent-mvp")


@dataclass(frozen=True)
class MailruConfig:
    account_email: str
    imap_host: str
    imap_port: int
    imap_username: str
    imap_password: str


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    allowed_chat_id: str


@dataclass(frozen=True)
class Settings:
    mode: AgentMode
    db_path: Path
    mailru: MailruConfig
    telegram: TelegramConfig


def load_settings(env_file: Path | None = None) -> Settings:
    env_path = env_file or DEFAULT_PROJECT_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    mode = AgentMode(os.getenv("MAIL_AGENT_MODE", AgentMode.READ_ONLY.value))
    if mode != AgentMode.READ_ONLY:
        raise ValueError("Only MAIL_AGENT_MODE=read_only is supported in this scaffold.")

    db_path = Path(
        os.getenv(
            "MAIL_AGENT_DB_PATH",
            str(DEFAULT_PROJECT_DIR / "data" / "mail-agent.sqlite3"),
        )
    )

    account_email = os.getenv("MAILRU_ACCOUNT_EMAIL", "nadegda6464@mail.ru")
    return Settings(
        mode=mode,
        db_path=db_path,
        mailru=MailruConfig(
            account_email=account_email,
            imap_host=os.getenv("MAILRU_IMAP_HOST", "imap.mail.ru"),
            imap_port=int(os.getenv("MAILRU_IMAP_PORT", "993")),
            imap_username=os.getenv("MAILRU_IMAP_USERNAME", account_email),
            imap_password=os.getenv("MAILRU_IMAP_PASSWORD", ""),
        ),
        telegram=TelegramConfig(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            allowed_chat_id=os.getenv("TELEGRAM_ALLOWED_CHAT_ID", ""),
        ),
    )

