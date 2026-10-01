"""
Django Management Command: monthly_tasks

Run scheduled monthly tasks for the Telegram bot:
  - On the 1st of the month: send budget prompt to all linked users
  - On the last day of the month: send end-of-month report to all linked users

Usage:
  python manage.py monthly_tasks

Designed to be triggered daily by PythonAnywhere's free-tier scheduled tasks.
The command auto-detects which actions to perform based on today's date (IST).
"""
import asyncio
import calendar
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings


class Command(BaseCommand):
    help = "Run daily-check for monthly bot tasks (budget prompt on 1st, EOM report on last day)."

    def handle(self, *args, **options):
        today = timezone.localdate()
        self.stdout.write(f"[monthly_tasks] Running for date: {today}")

        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '').strip()
        if not token or token == 'your_api' or 'your_token' in token.lower():
            self.stderr.write("[monthly_tasks] Telegram bot token not configured. Skipping.")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._run_tasks(today, token))
        finally:
            loop.close()

        self.stdout.write(self.style.SUCCESS("[monthly_tasks] Done."))

    async def _run_tasks(self, today, token):
        from tracker.bot.runner import build_bot_application

        app = build_bot_application(token)
        await app.initialize()

        try:
            # 1st of the month → Budget prompt
            if today.day == 1:
                self.stdout.write("[monthly_tasks] Day 1 detected — sending budget prompts...")
                from tracker.bot.scheduler import prompt_monthly_budgets_job
                await prompt_monthly_budgets_job(app)
                self.stdout.write(self.style.SUCCESS("[monthly_tasks] Budget prompts sent."))

            # Last day of the month → End-of-month report
            last_day = calendar.monthrange(today.year, today.month)[1]
            if today.day == last_day:
                self.stdout.write(f"[monthly_tasks] Last day ({today.day}) detected — sending EOM reports...")
                from tracker.bot.scheduler import (
                    get_linked_users, get_monthly_report_data,
                    escape_html, strip_html
                )
                from io import BytesIO

                links = await get_linked_users()
                for link in links:
                    try:
                        status, expenses, pdf_bytes, filename = await get_monthly_report_data(
                            link.user, today.month, today.year
                        )
                        report_msg = (
                            f"📈 <b>End of Month Report • {today.strftime('%B %Y')}</b>\n\n"
                            f"• <b>Total Spent:</b> <code>₹{status['total_spent']:,.2f}</code>\n"
                            f"• <b>Budget Limit:</b> <code>₹{status['budget_amount']:,.2f}</code>\n"
                            f"• <b>Remaining:</b> <code>₹{status['remaining']:,.2f}</code>\n"
                            f"• <b>Total Transactions:</b> {len(expenses)}\n\n"
                            f"📄 Detailed PDF report attached below!"
                        )
                        try:
                            await app.bot.send_message(chat_id=link.chat_id, text=report_msg, parse_mode='HTML')
                        except Exception:
                            clean_msg = strip_html(report_msg)
                            await app.bot.send_message(chat_id=link.chat_id, text=clean_msg, parse_mode=None)

                        await app.bot.send_document(
                            chat_id=link.chat_id,
                            document=BytesIO(pdf_bytes),
                            filename=filename,
                            caption=f"Report {today.strftime('%B %Y')}"
                        )
                        self.stdout.write(f"  ✓ Report sent to chat {link.chat_id}")
                    except Exception as e:
                        self.stderr.write(f"  ✗ Error for chat {link.chat_id}: {e}")

                self.stdout.write(self.style.SUCCESS("[monthly_tasks] EOM reports sent."))

            if today.day != 1 and today.day != last_day:
                self.stdout.write("[monthly_tasks] No monthly tasks to run today.")
        finally:
            await app.shutdown()
