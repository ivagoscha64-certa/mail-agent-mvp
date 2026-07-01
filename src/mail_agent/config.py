from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from mail_agent.models import AgentMode


DEFAULT_PROJECT_DIR = Path(__file__).resolve().parents[2]
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_ACCOUNT_EMAIL = "your.email@example.com"


@dataclass(frozen=True)
class GmailApiConfig:
    provider: str
    account_email: str
    credentials_path: Path
    token_path: Path
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class ImapAccountConfig:
    provider: str
    account_email: str
    imap_host: str
    imap_port: int
    imap_timeout_seconds: int
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
    mail_backend: str
    gmail_api: GmailApiConfig
    imap_account: ImapAccountConfig
    telegram: TelegramConfig


def load_settings(env_file: Path | None = None) -> Settings:
    project_dir = get_project_dir()
    env_path = env_file or project_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        project_dir = get_project_dir()

    mode = AgentMode(os.getenv("MAIL_AGENT_MODE", AgentMode.READ_ONLY.value))
    if mode != AgentMode.READ_ONLY:
        raise ValueError("Only MAIL_AGENT_MODE=read_only is supported in this scaffold.")

    db_path = Path(
        os.getenv(
            "MAIL_AGENT_DB_PATH",
            str(project_dir / "data" / "mail-agent.sqlite3"),
        )
    )

    gmail_account_email = os.getenv("GMAIL_ACCOUNT_EMAIL", DEFAULT_ACCOUNT_EMAIL)
    imap_account_email = os.getenv("IMAP_ACCOUNT_EMAIL", gmail_account_email)
    return Settings(
        mode=mode,
        db_path=db_path,
        mail_backend=os.getenv("MAIL_BACKEND", "gmail_api"),
        gmail_api=GmailApiConfig(
            provider="gmail",
            account_email=gmail_account_email,
            credentials_path=Path(
                os.getenv(
                    "GMAIL_CREDENTIALS_PATH",
                    str(project_dir / "secrets" / "gmail-credentials.json"),
                )
            ),
            token_path=Path(
                os.getenv(
                    "GMAIL_TOKEN_PATH",
                    str(project_dir / "secrets" / "gmail-token.json"),
                )
            ),
            scopes=(GMAIL_READONLY_SCOPE,),
        ),
        imap_account=ImapAccountConfig(
            provider=os.getenv("IMAP_PROVIDER", "gmail"),
            account_email=imap_account_email,
            imap_host=os.getenv("IMAP_HOST", "imap.gmail.com"),
            imap_port=int(os.getenv("IMAP_PORT", "993")),
            imap_timeout_seconds=int(os.getenv("IMAP_TIMEOUT_SECONDS", "15")),
            imap_username=os.getenv("IMAP_USERNAME", imap_account_email),
            imap_password=os.getenv("IMAP_PASSWORD", ""),
        ),
        telegram=TelegramConfig(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            allowed_chat_id=os.getenv("TELEGRAM_ALLOWED_CHAT_ID", ""),
        ),
    )


def get_project_dir() -> Path:
    return Path(os.getenv("MAIL_AGENT_PROJECT_DIR", str(DEFAULT_PROJECT_DIR)))
