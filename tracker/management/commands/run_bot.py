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

        self.stdout.write(self.style.SUCCESS("[+] Initializing Smart Expense Tracker Telegram Bot..."))

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

        # Start scheduler
        scheduler = setup_scheduler(application)
        self.stdout.write(self.style.SUCCESS("[+] In-process background scheduler started (Monthly budget prompts & reports)"))

        self.stdout.write(self.style.SUCCESS("[*] Bot is active and polling for updates. Press Ctrl+C to stop.\n"))
        try:
            application.run_polling()
        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("\nStopping bot..."))
            scheduler.shutdown()

