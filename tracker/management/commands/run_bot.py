import sys
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Runs the Telegram Bot for Smart Expense Tracker'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-proxy',
            action='store_true',
            help='Bypass proxy and connect directly (for paid PythonAnywhere accounts or local testing)',
        )
        parser.add_argument(
            '--proxy',
            type=str,
            default=None,
            help='Specify a custom proxy URL (e.g. http://proxy.server:3128)',
        )

    def handle(self, *args, **options):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '').strip()

        if not token or token == 'your_api' or 'your_token' in token.lower():
            self.stdout.write(self.style.WARNING(
                "\n" + "=" * 65 + "\n"
                "  SMART EXPENSE TRACKER - TELEGRAM BOT RUNNER\n"
                "=" * 65 + "\n"
                "[!] Notice: Telegram Bot Token is currently set to 'your_api' in .env\n\n"
                "To connect and run the bot:\n"
                "  1. Open Telegram and message @BotFather.\n"
                "  2. Use /newbot to create your bot and copy your HTTP API token.\n"
                "  3. In your .env file, replace:\n"
                "       TELEGRAM_BOT_API=your_api\n"
                "     with:\n"
                "       TELEGRAM_BOT_API=<your_token_from_botfather>\n"
                "  4. Run this command again:\n"
                "       python manage.py run_bot\n"
                "=" * 65 + "\n"
            ))
            return

        from tracker.bot.runner import build_bot_application
        from telegram.error import NetworkError, Conflict
        import time

        no_proxy = options.get('no_proxy', False)
        proxy_arg = options.get('proxy', None)
        proxy_override = 'none' if no_proxy else proxy_arg

        self.stdout.write(self.style.SUCCESS("[+] Initializing Smart Expense Tracker Telegram Bot..."))
        application = build_bot_application(token, proxy_override=proxy_override)

        self.stdout.write(self.style.SUCCESS("[*] Bot is active and polling for updates. Press Ctrl+C to stop.\n"))

        backoff = 3
        while True:
            try:
                # bootstrap_retries=10 allows python-telegram-bot to retry initialization
                # if PythonAnywhere proxy returns a transient 503 Service Unavailable
                application.run_polling(
                    bootstrap_retries=10,
                    drop_pending_updates=False
                )
                break
            except KeyboardInterrupt:
                self.stdout.write(self.style.NOTICE("\nStopping bot..."))
                break
            except NetworkError as e:
                self.stdout.write(self.style.WARNING(
                    f"\n[!] Network or proxy issue: {e}\n"
                    f"    (PythonAnywhere proxy might be temporarily busy: 503). Retrying in {backoff}s..."
                ))
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"\n[!] Unexpected error: {e}. Retrying in {backoff}s..."
                ))
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

