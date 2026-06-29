from __future__ import annotations

import sqlite3

from mail_agent.config import TelegramConfig


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
