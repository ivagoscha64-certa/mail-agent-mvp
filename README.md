# Mail Agent MVP

Каркас почтового агента по шагу 3: Python, SQLite, Telegram bot, Mail.ru IMAP.

Стартовый режим строго read-only:

- без удаления писем;
- без отправки писем;
- без отписок;
- без переноса в спам;
- без перемещения писем.

Первый ящик: `nadegda6464@mail.ru`.

## Структура

- `src/mail_agent/config.py` - конфигурация из переменных окружения.
- `src/mail_agent/safety.py` - центральная политика безопасности.
- `src/mail_agent/mail/imap_mailru.py` - read-only IMAP-коннектор Mail.ru.
- `src/mail_agent/db.py` и `src/mail_agent/schema.sql` - SQLite-хранилище.
- `src/mail_agent/telegram_bot.py` - базовые команды Telegram.
- `src/mail_agent/classifier.py` - первые rule-based классификации.
- `src/mail_agent/audit.py` - журнал действий.

## Быстрый старт

```powershell
cd E:\AI\mail-agent-mvp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
Copy-Item .env.example .env
mail-agent init-db
mail-agent status
```

Для проверки IMAP заполните `MAILRU_IMAP_PASSWORD` в `.env` app-паролем Mail.ru и выполните:

```powershell
mail-agent check-mail --limit 10
```

Telegram bot стартует только при заполненном `TELEGRAM_BOT_TOKEN`:

```powershell
mail-agent bot
```

## Безопасность

Все потенциально опасные операции проходят через `SafetyPolicy.assert_allowed`.
В режиме `read_only` разрешены только:

- чтение писем через IMAP;
- сохранение данных и рекомендаций в SQLite;
- отправка Telegram-уведомлений;
- создание локальных черновиков в базе как текстовых записей.

Черновики пока не пишутся в Mail.ru: это сознательно оставлено за пределами стартового read-only режима.

