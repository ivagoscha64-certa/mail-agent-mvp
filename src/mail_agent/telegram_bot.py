from __future__ import annotations

import asyncio
import sqlite3

from mail_agent.config import TelegramConfig


def build_summary(conn: sqlite3.Connection, *, limit: int = 10) -> str:
    rows = conn.execute(
        """
        SELECT
            m.account,
            m.sender,
            m.subject,
            m.message_date,
            c.importance,
            c.action,
            c.risk,
            c.message_type,
            c.reason
        FROM messages m
        LEFT JOIN message_classifications c ON c.message_row_id = m.id
        WHERE c.importance IN ('high', 'medium')
           OR c.action IN ('spam_review', 'unsubscribe_candidate')
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        return "Mail agent: no messages selected for notification yet."

    lines = ["Mail agent summary", "Mode: read-only", ""]
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"{index}. {row['importance'] or 'unknown'} / {row['action'] or 'unknown'} / {row['risk'] or 'unknown'}",
                f"Account: {row['account']}",
                f"From: {_compact(row['sender'], 120)}",
                f"Subject: {_compact(row['subject'] or '(no subject)', 140)}",
                f"Type: {row['message_type'] or 'unknown'}",
                f"Reason: {_compact(row['reason'] or 'No reason stored.', 180)}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def send_summary(config: TelegramConfig, conn: sqlite3.Connection, *, limit: int = 10) -> None:
    if not config.bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Fill .env first.")
    if not config.allowed_chat_id:
        raise RuntimeError(
            "TELEGRAM_ALLOWED_CHAT_ID is empty. Send /start to the bot, then run "
            "`mail-agent telegram-chat-id`."
        )

    async def _send() -> None:
        from telegram import Bot

        bot = Bot(config.bot_token)
        await bot.send_message(
            chat_id=config.allowed_chat_id,
            text=build_summary(conn, limit=limit),
            disable_web_page_preview=True,
        )

    asyncio.run(_send())


def print_chat_ids(config: TelegramConfig) -> None:
    if not config.bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Fill .env first.")

    async def _print() -> None:
        from telegram import Bot

        bot = Bot(config.bot_token)
        updates = await bot.get_updates(limit=20, timeout=5)
        if not updates:
            print("No Telegram updates yet. Send /start to your bot, then run again.")
            return
        seen: set[int] = set()
        for update in updates:
            chat = update.effective_chat
            if not chat or chat.id in seen:
                continue
            seen.add(chat.id)
            print(f"chat_id={chat.id} type={chat.type} title={chat.title or ''}")

    asyncio.run(_print())


def run_bot(config: TelegramConfig, conn: sqlite3.Connection) -> None:
    if not config.bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Fill .env before starting bot.")

    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes

    async def status(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed_chat(config, update):
            return
        account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        message_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        await update.message.reply_text(
            f"Mail agent: read-only\nAccounts: {account_count}\nMessages: {message_count}"
        )

    async def accounts(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed_chat(config, update):
            return
        rows = conn.execute(
            "SELECT provider, email, mode FROM accounts ORDER BY email"
        ).fetchall()
        text = "\n".join(f"{row['provider']}: {row['email']} ({row['mode']})" for row in rows)
        await update.message.reply_text(text or "No accounts configured yet.")

    async def inbox(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_allowed_chat(config, update):
            return
        rows = conn.execute(
            """
            SELECT sender, subject, message_date
            FROM messages
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()
        text = "\n\n".join(
            f"{row['message_date'] or 'no date'}\n{row['sender']}\n{row['subject']}"
            for row in rows
        )
        await update.message.reply_text(text or "No stored messages yet.")

    async def table_count(update: Update, _context: ContextTypes.DEFAULT_TYPE, table: str) -> None:
        if not _is_allowed_chat(config, update):
            return
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        await update.message.reply_text(f"{table}: {count}")

    app = Application.builder().token(config.bot_token).build()
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("accounts", accounts))
    app.add_handler(CommandHandler("inbox", inbox))
    app.add_handler(CommandHandler("drafts", lambda u, c: table_count(u, c, "drafts")))
    app.add_handler(CommandHandler("cleanup", lambda u, c: table_count(u, c, "recommendations")))
    app.add_handler(CommandHandler("spam", lambda u, c: table_count(u, c, "spam_signals")))
    app.add_handler(
        CommandHandler("unsubscribe", lambda u, c: table_count(u, c, "unsubscribe_candidates"))
    )
    app.run_polling()


def _is_allowed_chat(config: TelegramConfig, update) -> bool:
    if not config.allowed_chat_id:
        return True
    chat = update.effective_chat
    return bool(chat and str(chat.id) == config.allowed_chat_id)


def _compact(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."
