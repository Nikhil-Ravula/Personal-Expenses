import os
import sys
import socket
import threading
import logging
import asyncio
from django.conf import settings

logger = logging.getLogger(__name__)

_bot_thread = None
_bot_started = False
_bot_lock_socket = None


def acquire_bot_lock(port=49152):
    """
    Acquire a cross-process lock on localhost:port so only ONE
    process ever polls the Telegram Bot API at a time.
    OS automatically releases this socket when the process exits.
    """
    global _bot_lock_socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(('127.0.0.1', port))
        s.listen(1)
        _bot_lock_socket = s
        return True
    except OSError:
        return False


async def bot_error_handler(update: object, context) -> None:
    """
    Gracefully handle polling errors and conflicts without crashing or spamming tracebacks.
    """
    from telegram.error import Conflict, NetworkError
    err = context.error
    if isinstance(err, Conflict):
        logger.warning("[Telegram Bot] Conflict: another getUpdates session is active. Retrying shortly...")
        await asyncio.sleep(4)
    elif isinstance(err, NetworkError):
        logger.warning(f"[Telegram Bot] Network connection interrupted: {err}. Retrying...")
        await asyncio.sleep(2)
    else:
        logger.error(f"[Telegram Bot Error]: {err}")


def build_bot_application(token: str, loop=None):
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        filters
    )
    from tracker.bot.handlers import (
        start_handler,
        help_handler,
        link_handler,
        create_category_handler,
        add_expense_handler,
        show_expenses_handler,
        delete_expense_handler,
        edit_expense_handler,
        total_handler,
        pdf_handler,
        budget_handler,
        text_message_handler,
        callback_query_handler
    )
    from tracker.bot.scheduler import setup_scheduler

    application = ApplicationBuilder().token(token).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("link", link_handler))
    application.add_handler(CommandHandler("create", create_category_handler))
    application.add_handler(CommandHandler("add", add_expense_handler))
    application.add_handler(CommandHandler("show", show_expenses_handler))
    application.add_handler(CommandHandler("delete", delete_expense_handler))
    application.add_handler(CommandHandler("edit", edit_expense_handler))
    application.add_handler(CommandHandler("total", total_handler))
    application.add_handler(CommandHandler("pdf", pdf_handler))
    application.add_handler(CommandHandler("budget", budget_handler))

    # Callback queries for inline confirm/cancel
    application.add_handler(CallbackQueryHandler(callback_query_handler))

    # Plain text messages for session confirmation/budget input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    # Register custom error handler to catch conflicts and disconnects cleanly
    application.add_error_handler(bot_error_handler)

    # Start scheduler
    try:
        setup_scheduler(application, loop=loop)
    except Exception as e:
        logger.warning(f"Could not start bot scheduler: {e}")

    return application


def start_bot_background():
    global _bot_thread, _bot_started
    if _bot_started:
        return
    _bot_started = True

    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '').strip()
    if not token or token == 'your_api' or 'your_token' in token.lower():
        logger.info("Telegram Bot: Token not configured in .env (skipping auto-start).")
        return

    # Check cross-process singleton lock
    if not acquire_bot_lock():
        logger.info("[Telegram Bot] Another server process is already running the bot instance. Skipping duplicate startup.")
        return

    def _worker():
        import time
        from telegram.error import Conflict
        time.sleep(1.0)
        while True:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                application = build_bot_application(token, loop=loop)
                logger.info("[Telegram Bot] Auto-started in background thread with runserver.")
                print("\n[+] Smart Expense Tracker Telegram Bot auto-started with server!\n")
                application.run_polling(stop_signals=None, close_loop=False)
                break
            except Conflict:
                logger.warning("[Telegram Bot] Conflict encountered, waiting 3s before retry...")
                time.sleep(3)
            except Exception as e:
                logger.error(f"[Telegram Bot Error]: {e}")
                time.sleep(4)

    _bot_thread = threading.Thread(target=_worker, name="TelegramBotThread", daemon=True)
    _bot_thread.start()
