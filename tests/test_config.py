from pathlib import Path

from mail_agent.config import DEFAULT_PROJECT_DIR, load_settings


def test_default_project_dir_resolves_to_repo_root():
    assert DEFAULT_PROJECT_DIR == Path(__file__).resolve().parents[1]


def test_default_imap_account_is_gmail(monkeypatch, tmp_path):
    for key in (
        "MAIL_AGENT_PROJECT_DIR",
        "MAIL_AGENT_DB_PATH",
        "MAIL_BACKEND",
        "GMAIL_ACCOUNT_EMAIL",
        "GMAIL_CREDENTIALS_PATH",
        "GMAIL_TOKEN_PATH",
        "IMAP_PROVIDER",
        "IMAP_ACCOUNT_EMAIL",
        "IMAP_HOST",
        "IMAP_PORT",
        "IMAP_USERNAME",
        "IMAP_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings(env_file=tmp_path / "missing.env")

    assert settings.imap_account.provider == "gmail"
    assert settings.imap_account.account_email == "your.email@example.com"
    assert settings.imap_account.imap_host == "imap.gmail.com"
    assert settings.imap_account.imap_port == 993
    assert settings.imap_account.imap_timeout_seconds == 15
    assert settings.mail_backend == "gmail_api"
    assert settings.gmail_api.provider == "gmail"
    assert settings.gmail_api.account_email == "your.email@example.com"
    assert settings.db_path == DEFAULT_PROJECT_DIR / "data" / "mail-agent.sqlite3"
    assert settings.gmail_api.credentials_path.name == "gmail-credentials.json"
    assert settings.gmail_api.token_path.name == "gmail-token.json"


def test_project_dir_env_override_updates_default_paths(monkeypatch, tmp_path):
    for key in (
        "MAIL_AGENT_DB_PATH",
        "GMAIL_CREDENTIALS_PATH",
        "GMAIL_TOKEN_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MAIL_AGENT_PROJECT_DIR", str(tmp_path))

    settings = load_settings(env_file=tmp_path / "missing.env")

    assert settings.db_path == tmp_path / "data" / "mail-agent.sqlite3"
    assert settings.gmail_api.credentials_path == (
        tmp_path / "secrets" / "gmail-credentials.json"
    )
    assert settings.gmail_api.token_path == tmp_path / "secrets" / "gmail-token.json"


def test_explicit_path_env_overrides_project_dir(monkeypatch, tmp_path):
    db_path = tmp_path / "custom.sqlite3"
    credentials_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"
    monkeypatch.setenv("MAIL_AGENT_PROJECT_DIR", str(tmp_path / "project"))
    monkeypatch.setenv("MAIL_AGENT_DB_PATH", str(db_path))
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))

    settings = load_settings(env_file=tmp_path / "missing.env")

    assert settings.db_path == db_path
    assert settings.gmail_api.credentials_path == credentials_path
    assert settings.gmail_api.token_path == token_path
