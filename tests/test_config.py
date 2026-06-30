from mail_agent.config import load_settings


def test_default_imap_account_is_gmail(monkeypatch, tmp_path):
    for key in (
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
    assert settings.imap_account.account_email == "iva196464@gmail.com"
    assert settings.imap_account.imap_host == "imap.gmail.com"
    assert settings.imap_account.imap_port == 993
    assert settings.imap_account.imap_timeout_seconds == 15
    assert settings.mail_backend == "gmail_api"
    assert settings.gmail_api.provider == "gmail"
    assert settings.gmail_api.account_email == "iva196464@gmail.com"
    assert settings.gmail_api.credentials_path.name == "gmail-credentials.json"
    assert settings.gmail_api.token_path.name == "gmail-token.json"
