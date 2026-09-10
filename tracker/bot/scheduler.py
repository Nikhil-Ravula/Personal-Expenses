import calendar
from datetime import date
from io import BytesIO
from django.utils import timezone
from asgiref.sync import sync_to_async
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from tracker.models import TelegramLink, TelegramSession, Budget, Expense
from tracker.services.budget_service import get_budget_status
from tracker.services.pdf_generator import generate_expense_pdf
from tracker.bot.handlers import escape_html, strip_html


@sync_to_async
def get_linked_users():
    return list(TelegramLink.objects.filter(chat_id__isnull=False).select_related('user'))


@sync_to_async
def check_user_needs_budget_prompt(user, month, year):
    has_budget = Budget.objects.filter(user=user, month=month, year=year, amount__gt=0).exists()
    return not has_budget


@sync_to_async
def set_session_budget_prompt(chat_id):
    session, _ = TelegramSession.objects.get_or_create(chat_id=chat_id)
    session.pending_action = 'set_monthly_budget'
    session.save(update_fields=['pending_action', 'updated_at'])


@sync_to_async
def get_monthly_report_data(user, month, year):
    status = get_budget_status(user, month=month, year=year)
    expenses = list(Expense.objects.filter(user=user, date__year=year, date__month=month).select_related('category').order_by('-date'))
    pdf_bytes, filename = generate_expense_pdf(
        expenses_qs=Expense.objects.filter(user=user, date__year=year, date__month=month),
        title=f"Monthly Expense Report - {calendar.month_name[month]} {year}",
        filter_label=f"{calendar.month_name[month]} {year}",
        user=user
    )
    return status, expenses, pdf_bytes, filename


async def prompt_monthly_budgets_job(application):
    """
    Auto-prompts linked users on the 1st of each month to set their budget.
    """
    now = timezone.now().date()
    links = await get_linked_users()

    for link in links:
        try:
            needs_prompt = await check_user_needs_budget_prompt(link.user, now.month, now.year)
            if needs_prompt:
                await set_session_budget_prompt(link.chat_id)
                uname_esc = escape_html(link.user.username)
                msg = (
                    f"👋 Good morning, <b>{uname_esc}</b>!\n\n"
                    f"A new month (<b>{now.strftime('%B %Y')}</b>) has begun. 🎯\n"
                    "Reply to this message with a number (e.g. <code>5000</code>) to set your budget limit for this month, or use <code>/budget &lt;amount&gt;</code>."
                )
                try:
                    await application.bot.send_message(chat_id=link.chat_id, text=msg, parse_mode='HTML')
                except Exception:
                    clean_msg = strip_html(msg)
                    await application.bot.send_message(chat_id=link.chat_id, text=clean_msg, parse_mode=None)
        except Exception as e:
            print(f"Error prompting budget for chat {link.chat_id}: {e}")


async def end_of_month_report_job(application):
    """
    Dispatches end-of-month summary & PDF report to all linked users.
    """
    now = timezone.now().date()
    # Check if today is the last day of the month
    last_day = calendar.monthrange(now.year, now.month)[1]
    if now.day != last_day:
        return

    links = await get_linked_users()
    for link in links:
        try:
            status, expenses, pdf_bytes, filename = await get_monthly_report_data(link.user, now.month, now.year)
            report_msg = (
                f"📈 <b>End of Month Report • {now.strftime('%B %Y')}</b>\n\n"
                f"• <b>Total Spent:</b> <code>₹{status['total_spent']:,.2f}</code>\n"
                f"• <b>Budget Limit:</b> <code>₹{status['budget_amount']:,.2f}</code>\n"
                f"• <b>Remaining:</b> <code>₹{status['remaining']:,.2f}</code>\n"
                f"• <b>Total Transactions:</b> {len(expenses)}\n\n"
                f"📄 Detailed PDF report attached below!"
            )
            try:
                await application.bot.send_message(chat_id=link.chat_id, text=report_msg, parse_mode='HTML')
            except Exception:
                clean_report_msg = strip_html(report_msg)
                await application.bot.send_message(chat_id=link.chat_id, text=clean_report_msg, parse_mode=None)
            await application.bot.send_document(
                chat_id=link.chat_id,
                document=BytesIO(pdf_bytes),
                filename=filename,
                caption=f"Report {now.strftime('%B %Y')}"
            )
        except Exception as e:
            print(f"Error dispatching EOM report for chat {link.chat_id}: {e}")


def setup_scheduler(application, loop=None):
    try:
        scheduler = AsyncIOScheduler(event_loop=loop) if loop else AsyncIOScheduler()

        # 1. 1st of every month at 09:00 AM
        scheduler.add_job(
            prompt_monthly_budgets_job,
            trigger=CronTrigger(day=1, hour=9, minute=0),
            args=[application],
            id="prompt_monthly_budget",
            replace_existing=True
        )

        # 2. Daily check at 21:00 (triggers on the last day of the month)
        scheduler.add_job(
            end_of_month_report_job,
            trigger=CronTrigger(hour=21, minute=0),
            args=[application],
            id="end_of_month_report",
            replace_existing=True
        )

        scheduler.start()
        return scheduler
    except Exception as e:
        print(f"Notice: APScheduler background jobs deferred: {e}")
        return None
