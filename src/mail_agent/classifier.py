from __future__ import annotations

from mail_agent.models import (
    Classification,
    Importance,
    MessageType,
    NormalizedMessage,
    RecommendedAction,
    Risk,
)


SECURITY_WORDS = ("пароль", "password", "login", "код", "2fa", "безопасность")
NEWSLETTER_HEADERS = ("list-unsubscribe", "list-id")
PROMO_WORDS = ("скидка", "акция", "sale", "promo", "купон")
URGENT_RISK_WORDS = (
    "срочно оплат",
    "переведите",
    "подтвердите пароль",
    "verify password",
)


def classify(message: NormalizedMessage) -> Classification:
    haystack = " ".join(
        [
            message.subject,
            message.sender,
            message.text[:2000],
            " ".join(f"{k}: {v}" for k, v in message.headers.items()),
        ]
    ).lower()

    if any(word in haystack for word in URGENT_RISK_WORDS):
        return Classification(
            importance=Importance.HIGH,
            action=RecommendedAction.SPAM_REVIEW,
            risk=Risk.SUSPICIOUS,
            message_type=MessageType.SECURITY,
            reason="Найдены признаки срочного финансового или парольного давления.",
        )

    if any(header in {key.lower() for key in message.headers} for header in NEWSLETTER_HEADERS):
        return Classification(
            importance=Importance.LOW,
            action=RecommendedAction.UNSUBSCRIBE_CANDIDATE,
            risk=Risk.SAFE,
            message_type=MessageType.NEWSLETTER,
            reason="Письмо похоже на рассылку: найден List-Unsubscribe/List-ID.",
        )

    if any(word in haystack for word in SECURITY_WORDS):
        return Classification(
            importance=Importance.HIGH,
            action=RecommendedAction.NOTIFY,
            risk=Risk.SAFE,
            message_type=MessageType.SECURITY,
            reason="Письмо связано с доступом или безопасностью аккаунта.",
        )

    if any(word in haystack for word in PROMO_WORDS):
        return Classification(
            importance=Importance.LOW,
            action=RecommendedAction.CLEANUP_CANDIDATE,
            risk=Risk.SAFE,
            message_type=MessageType.PROMO,
            reason="Письмо похоже на промо или рекламное уведомление.",
        )

    return Classification(
        importance=Importance.MEDIUM,
        action=RecommendedAction.NOTIFY,
        risk=Risk.SAFE,
        message_type=MessageType.UNKNOWN,
        reason="Нет специальных признаков; письмо оставлено для обычного просмотра.",
    )
