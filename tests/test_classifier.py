from mail_agent.classifier import classify
from mail_agent.models import MessageType, NormalizedMessage, Provider, RecommendedAction, Risk


def test_classifier_matches_russian_security_words():
    result = classify(_message(subject="Код безопасности", text="Ваш пароль был изменен"))

    assert result.message_type == MessageType.SECURITY
    assert result.action == RecommendedAction.NOTIFY
    assert result.reason == "Письмо связано с доступом или безопасностью аккаунта."


def test_classifier_matches_russian_urgent_risk_words():
    result = classify(_message(subject="Срочно оплатите", text="Подтвердите пароль"))

    assert result.message_type == MessageType.SECURITY
    assert result.action == RecommendedAction.SPAM_REVIEW
    assert result.risk == Risk.SUSPICIOUS
    assert "срочного финансового" in result.reason


def _message(*, subject: str, text: str) -> NormalizedMessage:
    return NormalizedMessage(
        provider=Provider.GMAIL,
        account="configured-account@example.com",
        message_uid="uid-1",
        message_id="<uid-1@example.test>",
        thread_id="thread-1",
        sender="sender@example.test",
        recipients=["configured-account@example.com"],
        subject=subject,
        date="2026-06-30T00:00:00+00:00",
        text=text,
        html="",
        headers={},
    )
