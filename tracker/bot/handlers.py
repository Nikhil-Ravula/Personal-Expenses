import re
import math
import logging
from io import BytesIO
from decimal import Decimal, InvalidOperation
from datetime import date
from django.utils import timezone
from django.db.models import Sum, Count
from asgiref.sync import sync_to_async
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from tracker.models import User, Category, Expense, Budget, TelegramLink, TelegramSession
from tracker.services.filter_parser import parse_filter_args, apply_expense_filters
from tracker.services.budget_service import get_budget_status, check_budget_thresholds_after_expense, get_or_create_budget
from tracker.services.pdf_generator import generate_expense_pdf

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Markdown & Telegram Safe Sending Helpers
# --------------------------------------------------------------------------

def escape_md(text) -> str:
    """
    Safely escape characters for Telegram Markdown v1:
    '_', '*', '`', '['
    Prevents entities parsing errors when dynamic values (category names,
    descriptions, usernames, labels) contain underscores or other symbols.
    """
    if text is None:
        return ""
    return escape_markdown(str(text), version=1)


async def safe_reply(update: Update, text: str, parse_mode: str = 'Markdown', reply_markup=None):
    """
    Safely send a reply to Telegram. If Telegram rejects the message due to entity
    parsing errors (e.g. malformed markdown), automatically fall back to sending
    plain text so the user never experiences silent command failure.
    """
    target = None
    if getattr(update, 'message', None):
        target = update.message
    elif getattr(update, 'callback_query', None) and getattr(update.callback_query, 'message', None):
        target = update.callback_query.message

    if not target:
        return None

    try:
        return await target.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"[safe_reply] Telegram rejected with parse_mode={parse_mode}: {e}. Retrying as plain text.")
        try:
            return await target.reply_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as inner:
            logger.error(f"[safe_reply] Plain text fallback also failed: {inner}")
            return None


async def safe_edit_text(query, text: str, parse_mode: str = 'Markdown', reply_markup=None):
    """
    Safely edit message text. Automatically falls back to plain text if Markdown parsing fails.
    """
    try:
        return await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"[safe_edit_text] Edit failed with parse_mode={parse_mode}: {e}. Retrying as plain text.")
        try:
            return await query.edit_message_text(text, parse_mode=None, reply_markup=reply_markup)
        except Exception as inner:
            logger.error(f"[safe_edit_text] Plain text edit fallback failed: {inner}")
            return None


# --------------------------------------------------------------------------
# DB Helpers (Wrapped in sync_to_async for async telegram handlers)
# --------------------------------------------------------------------------

@sync_to_async
def get_user_by_chat_id(chat_id: int):
    link = TelegramLink.objects.filter(chat_id=chat_id).select_related('user').first()
    return link.user if link else None


@sync_to_async
def link_chat_id_with_code(chat_id: int, code: str):
    code_clean = code.strip().upper()
    link = TelegramLink.objects.filter(link_code=code_clean).select_related('user').first()
    if not link:
        return False, "❌ Invalid or expired link code. Please check your Profile page on the website."

    link.chat_id = chat_id
    link.linked_at = timezone.now()
    link.link_code = None  # consume code
    link.save(update_fields=['chat_id', 'linked_at', 'link_code'])
    uname_esc = escape_md(link.user.username)
    return True, f"✅ Successfully linked your Telegram account with user *{uname_esc}*! You can now use all commands."


@sync_to_async
def create_user_category(user, cat_name: str):
    name_clean = cat_name.strip().capitalize()
    cat, created = Category.objects.get_or_create(user=user, name=name_clean)
    return cat, created


@sync_to_async
def get_user_categories_data(user):
    cats = (
        Category.objects.filter(user=user)
        .annotate(
            expense_count=Count('expenses'),
            total_spent=Sum('expenses__amount')
        )
        .order_by('name')
    )
    active = []
    empty = []
    for c in cats:
        if c.expense_count > 0:
            active.append({
                'id': c.id,
                'name': c.name,
                'count': c.expense_count,
                'total': c.total_spent or Decimal('0.00')
            })
        else:
            empty.append({
                'id': c.id,
                'name': c.name,
                'count': 0,
                'total': Decimal('0.00')
            })
    return active, empty


@sync_to_async
def delete_user_category_by_id_or_name(user, identifier: str):
    identifier_clean = identifier.strip()
    cat = None
    if identifier_clean.isdigit():
        cat = Category.objects.filter(id=int(identifier_clean), user=user).first()
    if not cat:
        cat = Category.objects.filter(name__iexact=identifier_clean, user=user).first()

    if not cat:
        return False, None, "Category not found."

    count = cat.expenses.count()
    if count > 0:
        return False, cat.name, f"Cannot delete '{cat.name}' because it contains {count} expense(s)."

    cat_name = cat.name
    cat.delete()
    return True, cat_name, "Deleted successfully."


@sync_to_async
def add_expense_db(user, category_name: str, exp_type: str, amount_val: Decimal):
    cat_clean = category_name.strip().capitalize()
    cat, _ = Category.objects.get_or_create(user=user, name=cat_clean)
    now = timezone.now().date()

    expense = Expense.objects.create(
        user=user,
        category=cat,
        type=exp_type.strip(),
        amount=amount_val,
        date=now,
        created_via='bot'
    )
    # Check budget thresholds
    alerts = check_budget_thresholds_after_expense(user, expense.date)
    return expense, alerts


@sync_to_async
def query_expenses_page_db(user, filter_text: str, page: int = 1, page_size: int = 25):
    filter_dict = parse_filter_args(filter_text, user=user)
    base_qs = Expense.objects.filter(user=user).select_related('category')
    qs = apply_expense_filters(base_qs, filter_dict)

    total_count = qs.count()
    agg = qs.aggregate(total=Sum('amount'))
    total_amount = agg['total'] or Decimal('0.00')

    total_pages = max(1, math.ceil(total_count / page_size))
    current_page = max(1, min(page, total_pages))

    offset = (current_page - 1) * page_size
    expenses = list(qs.order_by('-date', '-created_at')[offset:offset + page_size])

    return expenses, total_amount, total_count, current_page, total_pages, filter_dict['label']


@sync_to_async
def store_shown_page(chat_id: int, expense_ids: list, offset: int, filter_text: str = "", reset: bool = False):
    session, _ = TelegramSession.objects.get_or_create(chat_id=chat_id)
    if reset:
        current_list = []
    else:
        current_list = session.last_shown_list or []

    needed_len = offset + len(expense_ids)
    if len(current_list) < needed_len:
        current_list = current_list + [None] * (needed_len - len(current_list))

    for i, exp_id in enumerate(expense_ids):
        current_list[offset + i] = exp_id

    session.last_shown_list = current_list
    pdata = session.pending_data or {}
    pdata['show_filter'] = filter_text
    session.pending_data = pdata
    session.save(update_fields=['last_shown_list', 'pending_data', 'updated_at'])


@sync_to_async
def get_session_data(chat_id: int):
    session, _ = TelegramSession.objects.get_or_create(chat_id=chat_id)
    return session.last_shown_list, session.pending_action, session.pending_data


@sync_to_async
def set_pending_action(chat_id: int, action: str, data: dict = None):
    session, _ = TelegramSession.objects.get_or_create(chat_id=chat_id)
    session.pending_action = action
    session.pending_data = data or {}
    session.save(update_fields=['pending_action', 'pending_data', 'updated_at'])


@sync_to_async
def clear_pending_action(chat_id: int):
    session, _ = TelegramSession.objects.get_or_create(chat_id=chat_id)
    session.pending_action = None
    session.pending_data = {}
    session.save(update_fields=['pending_action', 'pending_data', 'updated_at'])


@sync_to_async
def delete_expense_by_id(user, expense_id: int):
    expense = Expense.objects.filter(id=expense_id, user=user).first()
    if expense:
        desc = f"{expense.type} (₹{expense.amount})"
        expense.delete()
        return True, desc
    return False, None


@sync_to_async
def edit_expense_db(user, expense_id: int, new_type: str, new_amount: Decimal):
    expense = Expense.objects.filter(id=expense_id, user=user).first()
    if expense:
        if new_type:
            expense.type = new_type.strip()
        if new_amount:
            expense.amount = new_amount
        expense.save()
        return True, expense
    return False, None


@sync_to_async
def query_total_db(user, filter_text: str):
    filter_dict = parse_filter_args(filter_text, user=user)
    qs = Expense.objects.filter(user=user)
    qs = apply_expense_filters(qs, filter_dict)
    agg = qs.aggregate(total=Sum('amount'))
    total = agg['total'] or Decimal('0.00')
    count = qs.count()
    return total, count, filter_dict['label']


@sync_to_async
def generate_pdf_for_user(user, filter_text: str):
    filter_dict = parse_filter_args(filter_text, user=user)
    qs = Expense.objects.filter(user=user).select_related('category')
    qs = apply_expense_filters(qs, filter_dict).order_by('-date', '-created_at')
    return generate_expense_pdf(qs, title="Expense Report", filter_label=filter_dict['label'], user=user)


@sync_to_async
def get_budget_status_db(user, month=None, year=None):
    return get_budget_status(user, month=month, year=year)


@sync_to_async
def modify_budget_db(user, action: str, amount_val: Decimal, month=None, year=None):
    now = timezone.now().date()
    month = month or now.month
    year = year or now.year

    budget, _ = Budget.objects.get_or_create(
        user=user,
        month=month,
        year=year,
        defaults={'amount': Decimal('0.00')}
    )

    if action == 'set':
        budget.amount = amount_val
    elif action == 'add':
        budget.amount += amount_val
    elif action == 'remove':
        budget.amount = max(Decimal('0.00'), budget.amount - amount_val)

    # Reset notification flags when limit is modified
    budget.notified_80 = False
    budget.notified_100 = False
    budget.save()
    return budget


# --------------------------------------------------------------------------
# Bot Command Handlers
# --------------------------------------------------------------------------

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)

    # 1. Deep linking direct connection: /start <code>
    if context.args and len(context.args) > 0:
        code = context.args[0].strip()
        success, reply = await link_chat_id_with_code(chat_id, code)
        if success:
            reply += (
                "\n\n💡 Type `/help` to see all commands."
                "\nQuick example: `/add food lunch 120`"
            )
        await safe_reply(update, reply)
        return

    # 2. Normal /start command
    if user:
        uname_esc = escape_md(user.username)
        msg = (
            f"👋 Welcome back, *{uname_esc}*!\n\n"
            "Your Telegram account is connected to *Smart Expense Tracker*.\n\n"
            "💡 Type `/help` to see the full list of commands.\n"
            "Quick example: `/add food pizza 150`"
        )
    else:
        msg = (
            "👋 Welcome to *Smart Expense Tracker Bot*!\n\n"
            "To link your Telegram account with your web dashboard:\n"
            "1. Log into your dashboard on the website.\n"
            "2. Navigate to your *Profile* page and click *Direct Redirect to Telegram*.\n"
            "3. Or send the command: `/link <YOUR_CODE>` (e.g. `/link A7X92B`)\n\n"
            "Once linked, all your expenses and reports will sync in real time!"
        )
    await safe_reply(update, msg)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📊 *Smart Expense Tracker - Available Commands*\n\n"
        "🔗 *Account Linking*\n"
        "• `/link <code>` — Connect your Telegram to your web account\n\n"
        "💸 *Adding Expenses*\n"
        "• `/add <category> <type> <price>`\n"
        "  _Examples:_ `/add food pizza 50` • `/add travel auto 20`\n\n"
        "📋 *Viewing Expenses*\n"
        "• `/show` — Show recent expenses\n"
        "• `/show <month>` — e.g. `/show september`\n"
        "• `/show <date>` — e.g. `/show 26 september 2026`\n\n"
        "🗑️ *Deleting & Editing*\n"
        "• `/delete <number>` — Delete item at that position from the last `/show` list\n"
        "• `/edit <number>` — Modify description/amount of item from the last `/show` list\n\n"
        "💰 *Totals & Analytics*\n"
        "• `/total` — Total of all expenses\n"
        "• `/total <month>` — Total for that month\n"
        "• `/total <category>` — Total for that category\n"
        "• `/total <month> <category>` — Category total for that month\n\n"
        "🏷️ *Categories*\n"
        "• `/create <category>` — Create custom category (e.g. `/create shopping`)\n"
        "• `/categories` — List all categories (shows active & empty)\n"
        "• `/empty_categories` — Show only empty categories with delete buttons\n"
        "• `/delete_category <name>` — Delete an empty category\n\n"
        "🎯 *Monthly Budget*\n"
        "• `/budget` — View current budget status, spent & remaining\n"
        "• `/budget <amount>` — Set budget limit for current month\n"
        "• `/budget add <amount>` — Add amount to current budget\n"
        "• `/budget remove <amount>` — Subtract amount from budget\n"
        "• `/budget remaining` — Show only remaining budget\n\n"
        "📄 *PDF Reports*\n"
        "• `/pdf` — Download PDF of all expenses\n"
        "• `/pdf <month>` — PDF for that month (e.g. `/pdf september`)\n"
        "• `/pdf <category>` — PDF for that category\n"
        "• `/pdf <month> <category>` — PDF for category within that month"
    )
    await safe_reply(update, help_text)


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await safe_reply(
            update,
            "⚠️ Please provide your 6-digit link code.\n"
            "Format: `/link <code>` (e.g. `/link 4B9K2A`)\n"
            "Generate your code from the web Profile page."
        )
        return

    code = context.args[0]
    success, reply = await link_chat_id_with_code(chat_id, code)
    await safe_reply(update, reply)


async def create_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    if not context.args:
        await safe_reply(update, "⚠️ Please specify a category name.\nFormat: `/create <category>` (e.g. `/create Books`)")
        return

    cat_name = " ".join(context.args).strip()
    cat, created = await create_user_category(user, cat_name)
    cat_esc = escape_md(cat.name)
    if created:
        await safe_reply(update, f"✅ Category *{cat_esc}* created successfully!")
    else:
        await safe_reply(update, f"ℹ️ Category *{cat_esc}* already exists.")


async def categories_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    active, empty = await get_user_categories_data(user)

    if not active and not empty:
        await safe_reply(
            update,
            "🏷️ You have no categories yet.\n"
            "Create one using: `/create <category>` (e.g. `/create Shopping`)"
        )
        return

    lines = ["🏷️ *Your Expense Categories*", ""]

    if active:
        lines.append("*Active Categories:*")
        for c in active:
            c_esc = escape_md(c['name'])
            lines.append(f"• *{c_esc}* — {c['count']} expense(s) (`₹{c['total']:,.2f}`)")
        lines.append("")

    keyboard = []
    if empty:
        lines.append("🗑️ *Empty Categories (0 expenses • Safe to delete):*")
        for idx, c in enumerate(empty, start=1):
            c_esc = escape_md(c['name'])
            lines.append(f"`{idx}.` *{c_esc}* (0 expenses)")
            keyboard.append([
                InlineKeyboardButton(f"🗑️ Delete {c['name']}", callback_data=f"delcat_{c['id']}")
            ])
        lines.append("")
        lines.append("💡 _Tap a button above to delete, or send:_ `/delete_category <name>`")
    else:
        lines.append("✨ All your categories currently have active expenses!")

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await safe_reply(update, "\n".join(lines), reply_markup=reply_markup)


async def empty_categories_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    _, empty = await get_user_categories_data(user)

    if not empty:
        await safe_reply(update, "✅ You have no empty categories! All categories have recorded expenses.")
        return

    lines = [
        "🗑️ *Empty Categories (0 Expenses)*",
        "These categories have no expenses and can safely be deleted:",
        ""
    ]
    keyboard = []
    for idx, c in enumerate(empty, start=1):
        c_esc = escape_md(c['name'])
        lines.append(f"`{idx}.` *{c_esc}*")
        keyboard.append([
            InlineKeyboardButton(f"🗑️ Delete {c['name']}", callback_data=f"delcat_{c['id']}")
        ])

    lines.append("")
    lines.append("💡 _Tap a button above to delete, or send:_ `/delete_category <name>`")

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_reply(update, "\n".join(lines), reply_markup=reply_markup)


async def delete_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    if not context.args:
        await safe_reply(
            update,
            "⚠️ Please specify the category to delete.\n"
            "Usage: `/delete_category <name>` (e.g. `/delete_category daily_items`)\n"
            "💡 Use `/empty_categories` to see all empty categories."
        )
        return

    cat_query = " ".join(context.args).strip()
    success, cat_name, msg = await delete_user_category_by_id_or_name(user, cat_query)

    if success:
        c_esc = escape_md(cat_name)
        await safe_reply(update, f"🗑️ Deleted empty category *{c_esc}* successfully!")
    else:
        c_esc = escape_md(cat_name or cat_query)
        if "contains" in msg:
            await safe_reply(update, f"⚠️ Cannot delete category *{c_esc}* because it contains active expenses. Only empty categories can be deleted.")
        else:
            await safe_reply(update, f"❌ Category *{c_esc}* was not found.")


async def add_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    # Syntax: /add <category> <type> <price>
    # E.g. /add food pizza 50  OR  /add "travel expenses" metro 45
    if not context.args or len(context.args) < 3:
        await safe_reply(
            update,
            "⚠️ Invalid format.\n"
            "Usage: `/add <category> <type> <price>`\n"
            "Examples:\n"
            "• `/add food pizza 50`\n"
            "• `/add travel auto 10`"
        )
        return

    # The last token should be the price
    price_str = context.args[-1].replace('₹', '').replace(',', '').strip()
    try:
        price = Decimal(price_str)
        if price <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        price_esc = escape_md(price_str)
        await safe_reply(update, f"❌ Invalid price '{price_esc}'. Price must be a positive number.")
        return

    # Category is the first argument, and middle arguments form the description
    category_name = context.args[0]
    exp_type = " ".join(context.args[1:-1])

    expense, alerts = await add_expense_db(user, category_name, exp_type, price)

    type_esc = escape_md(expense.type)
    cat_esc = escape_md(expense.category.name)

    response_text = (
        f"✅ *Expense Added!*\n"
        f"• *Item:* {type_esc}\n"
        f"• *Amount:* `₹{expense.amount:,.2f}`\n"
        f"• *Category:* {cat_esc}\n"
        f"• *Date:* {expense.date.strftime('%d %b %Y')}"
    )

    if alerts:
        escaped_alerts = [escape_md(a) for a in alerts]
        response_text += "\n\n" + "\n\n".join(escaped_alerts)

    await safe_reply(update, response_text)


def build_show_page_content(expenses, total_amount, total_count, current_page, total_pages, label, page_size=25):
    safe_label = escape_md(label)
    lines = [f"📋 *Expenses ({safe_label})*", ""]

    offset = (current_page - 1) * page_size
    for idx, e in enumerate(expenses, start=offset + 1):
        type_esc = escape_md(e.type)
        cat_esc = escape_md(e.category.name)
        lines.append(f"`{idx}.` {e.date.strftime('%d %b')} • *{type_esc}* ({cat_esc}) — `₹{e.amount:,.2f}`")

    lines.append("")
    if total_pages > 1:
        lines.append(f"💰 *Total:* `₹{total_amount:,.2f}` (Page {current_page} of {total_pages} • {total_count} items)")
    else:
        lines.append(f"💰 *Total:* `₹{total_amount:,.2f}` ({total_count} items)")

    lines.append("Tip: To delete an item, reply `/delete <number>`.")
    text = "\n".join(lines)

    keyboard = []
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"showpage_{current_page - 1}"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(f"Next ➡️ (Page {current_page + 1}/{total_pages})", callback_data=f"showpage_{current_page + 1}"))

    if nav_row:
        keyboard.append(nav_row)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    return text, reply_markup


async def show_expenses_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    page_size = 25
    expenses, total_amount, total_count, current_page, total_pages, label = await query_expenses_page_db(
        user, filter_text, page=1, page_size=page_size
    )

    safe_label = escape_md(label)

    if not expenses:
        await safe_reply(update, f"ℹ️ No expenses found for: *{safe_label}*.")
        return

    offset = (current_page - 1) * page_size
    expense_ids = [e.id for e in expenses]
    await store_shown_page(chat_id, expense_ids, offset, filter_text=filter_text, reset=True)

    text, reply_markup = build_show_page_content(
        expenses, total_amount, total_count, current_page, total_pages, label, page_size=page_size
    )
    await safe_reply(update, text, reply_markup=reply_markup)


async def delete_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    if not context.args or not context.args[0].isdigit():
        await safe_reply(
            update,
            "⚠️ Please specify the number from your last `/show` list.\n"
            "Example: `/delete 1`"
        )
        return

    item_num = int(context.args[0])
    shown_list, _, _ = await get_session_data(chat_id)

    if not shown_list:
        await safe_reply(update, "⚠️ No active list found. Please run `/show` first to view your expenses.")
        return

    if item_num < 1 or item_num > len(shown_list) or not shown_list[item_num - 1]:
        await safe_reply(update, f"❌ Invalid item number {item_num}. Please choose a number from your `/show` list.")
        return

    target_id = shown_list[item_num - 1]

    def fetch_expense():
        return Expense.objects.filter(id=target_id, user=user).select_related('category').first()

    exp = await sync_to_async(fetch_expense)()
    if not exp:
        await safe_reply(update, "❌ Expense not found (it may have already been deleted).")
        return

    # Store pending deletion in session
    await set_pending_action(
        chat_id,
        action='delete_confirm',
        data={'expense_id': target_id, 'summary': f"{exp.type} (₹{exp.amount})"}
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"del_yes_{target_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="del_no")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    type_esc = escape_md(exp.type)
    cat_esc = escape_md(exp.category.name)

    await safe_reply(
        update,
        f"❓ Are you sure you want to delete:\n*{type_esc}* — `₹{exp.amount:,.2f}` ({cat_esc}) on {exp.date.strftime('%d %b %Y')}?",
        reply_markup=reply_markup
    )


async def edit_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    if not context.args or not context.args[0].isdigit():
        await safe_reply(update, "⚠️ Usage: `/edit <number>`\nExample: `/edit 1` (referencing the last `/show` list)")
        return

    item_num = int(context.args[0])
    shown_list, _, _ = await get_session_data(chat_id)

    if not shown_list or item_num < 1 or item_num > len(shown_list) or not shown_list[item_num - 1]:
        await safe_reply(update, "❌ Invalid item number. Please use `/show` to see your current list.")
        return

    target_id = shown_list[item_num - 1]

    def fetch_expense():
        return Expense.objects.filter(id=target_id, user=user).first()

    exp = await sync_to_async(fetch_expense)()
    if not exp:
        await safe_reply(update, "❌ Expense not found.")
        return

    await set_pending_action(chat_id, action='edit_pending', data={'expense_id': target_id})
    type_esc = escape_md(exp.type)
    await safe_reply(
        update,
        f"✏️ Editing *{type_esc}* (Current amount: `₹{exp.amount:,.2f}`).\n\n"
        "Please reply with the new description and amount:\n"
        "Format: `<description> <amount>` (e.g. `Pizza with cheese 60`)"
    )


async def total_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    total, count, label = await query_total_db(user, filter_text)

    safe_label = escape_md(label)
    msg = (
        f"📊 *Expense Total*\n"
        f"• *Scope:* {safe_label}\n"
        f"• *Total Amount:* `₹{total:,.2f}`\n"
        f"• *Transactions:* {count}"
    )
    await safe_reply(update, msg)


async def pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    status_msg = await safe_reply(update, "⏳ Generating your PDF report...")

    try:
        pdf_bytes, filename = await generate_pdf_for_user(user, filter_text)
        await context.bot.send_document(
            chat_id=chat_id,
            document=BytesIO(pdf_bytes),
            filename=filename,
            caption="📄 Expense Report • Smart Tracker"
        )
        if status_msg:
            await status_msg.delete()
    except Exception as e:
        if status_msg:
            await status_msg.edit_text(f"❌ Failed to generate PDF: {str(e)}")
        else:
            await safe_reply(update, f"❌ Failed to generate PDF: {str(e)}")


async def budget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using `/link <code>`.")
        return

    args = context.args

    # 1. /budget (view current)
    if not args:
        status = await get_budget_status_db(user)
        if not status['has_budget']:
            await safe_reply(
                update,
                f"ℹ️ No budget set for {timezone.now().strftime('%B %Y')}.\n"
                "To set a budget limit, send: `/budget <amount>` (e.g. `/budget 5000`)"
            )
            return

        status_icon = "🚨" if status['is_over'] else ("⚠️" if status['percent_spent'] >= 80 else "✅")
        msg = (
            f"{status_icon} *Monthly Budget Status ({timezone.now().strftime('%B %Y')})*\n\n"
            f"• *Budget Limit:* `₹{status['budget_amount']:,.2f}`\n"
            f"• *Total Spent:* `₹{status['total_spent']:,.2f}` ({status['percent_spent']}%)\n"
            f"• *Remaining:* `₹{status['remaining']:,.2f}`\n"
        )
        if status['is_over']:
            msg += f"\n🚨 *Over Budget by ₹{abs(status['remaining']):,.2f}!*"
        await safe_reply(update, msg)
        return

    first_arg = args[0].lower()

    # 2. /budget remaining
    if first_arg == 'remaining':
        status = await get_budget_status_db(user)
        if not status['has_budget']:
            await safe_reply(update, "ℹ️ No budget set for this month yet. Set one via `/budget <amount>`.")
            return
        await safe_reply(update, f"💰 Remaining budget for this month: `₹{status['remaining']:,.2f}`")
        return

    # 3. /budget add <amount>
    if first_arg == 'add':
        if len(args) < 2:
            await safe_reply(update, "⚠️ Usage: `/budget add <amount>` (e.g. `/budget add 1000`)")
            return
        try:
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='add', amount_val=amt)
            await safe_reply(update, f"✅ Added ₹{amt:,.2f}. New budget for this month: `₹{budget.amount:,.2f}`")
        except (InvalidOperation, ValueError):
            await safe_reply(update, "❌ Invalid amount.")
        return

    # 4. /budget remove <amount>
    if first_arg == 'remove':
        if len(args) < 2:
            await safe_reply(update, "⚠️ Usage: `/budget remove <amount>` (e.g. `/budget remove 500`)")
            return
        try:
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='remove', amount_val=amt)
            await safe_reply(update, f"✅ Deducted ₹{amt:,.2f}. New budget for this month: `₹{budget.amount:,.2f}`")
        except (InvalidOperation, ValueError):
            await safe_reply(update, "❌ Invalid amount.")
        return

    # 5. /budget <amount> OR /budget <month> <amount>
    try:
        # Check if first arg is month name
        parsed = parse_filter_args(first_arg)
        if parsed['month'] and len(args) >= 2:
            month_val = parsed['month']
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='set', amount_val=amt, month=month_val)
            await safe_reply(update, f"🎯 Budget for month {month_val} set to `₹{budget.amount:,.2f}`.")
            return

        amt = Decimal(first_arg)
        budget = await modify_budget_db(user, action='set', amount_val=amt)
        await safe_reply(update, f"🎯 Budget for {timezone.now().strftime('%B %Y')} set to `₹{budget.amount:,.2f}`.")
    except (InvalidOperation, ValueError):
        await safe_reply(
            update,
            "⚠️ Invalid budget command.\n"
            "Examples:\n"
            "• `/budget 5000`\n"
            "• `/budget september 6000`\n"
            "• `/budget add 1000`\n"
            "• `/budget remove 500`\n"
            "• `/budget remaining`"
        )


# --------------------------------------------------------------------------
# Message & Callback Query Handlers (Session & Confirmation State)
# --------------------------------------------------------------------------

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        return

    text = update.message.text.strip()
    _, pending_action, pending_data = await get_session_data(chat_id)

    if pending_action == 'delete_confirm':
        if text.lower() in ['yes', 'y', 'confirm']:
            target_id = pending_data.get('expense_id')
            success, desc = await delete_expense_by_id(user, target_id)
            await clear_pending_action(chat_id)
            if success:
                desc_esc = escape_md(desc)
                await safe_reply(update, f"🗑️ Deleted *{desc_esc}*.")
            else:
                await safe_reply(update, "❌ Expense already deleted or not found.")
        elif text.lower() in ['no', 'n', 'cancel']:
            await clear_pending_action(chat_id)
            await safe_reply(update, "❌ Deletion cancelled.")
        return

    if pending_action == 'set_monthly_budget':
        # Auto-prompt reply on 1st of month: a plain numeric reply saves as budget
        try:
            amt = Decimal(text.replace('₹', '').replace(',', '').strip())
            budget = await modify_budget_db(user, action='set', amount_val=amt)
            await clear_pending_action(chat_id)
            await safe_reply(update, f"🎯 Budget for {timezone.now().strftime('%B %Y')} set to `₹{budget.amount:,.2f}`!")
        except (InvalidOperation, ValueError):
            await safe_reply(update, "Please reply with a valid number for your budget, or send `/help`.")
        return

    if pending_action == 'edit_pending':
        target_id = pending_data.get('expense_id')
        parts = text.split()
        if len(parts) >= 2:
            try:
                new_amount = Decimal(parts[-1].replace('₹', '').replace(',', ''))
                new_type = " ".join(parts[:-1])
                success, exp = await edit_expense_db(user, target_id, new_type, new_amount)
                await clear_pending_action(chat_id)
                if success:
                    type_esc = escape_md(exp.type)
                    await safe_reply(update, f"✅ Updated to *{type_esc}* — `₹{exp.amount:,.2f}`!")
                else:
                    await safe_reply(update, "❌ Expense not found.")
                return
            except (InvalidOperation, ValueError):
                pass
        await safe_reply(update, "⚠️ Format: `<description> <amount>` (e.g. `Dinner 150`) or type `/cancel`.")


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        return

    data = query.data
    if data.startswith("showpage_"):
        target_page = int(data.split("_")[1])
        _, _, pending_data = await get_session_data(chat_id)
        filter_text = pending_data.get('show_filter', '') if pending_data else ''

        page_size = 25
        expenses, total_amount, total_count, current_page, total_pages, label = await query_expenses_page_db(
            user, filter_text, page=target_page, page_size=page_size
        )

        if expenses:
            offset = (current_page - 1) * page_size
            expense_ids = [e.id for e in expenses]
            await store_shown_page(chat_id, expense_ids, offset, filter_text=filter_text, reset=False)

            text, reply_markup = build_show_page_content(
                expenses, total_amount, total_count, current_page, total_pages, label, page_size=page_size
            )
            await safe_edit_text(query, text, reply_markup=reply_markup)
        return

    if data.startswith("delcat_"):
        cat_id = data.split("_")[-1]
        success, cat_name, msg = await delete_user_category_by_id_or_name(user, cat_id)
        if success:
            c_esc = escape_md(cat_name)
            await safe_edit_text(query, f"🗑️ Deleted empty category *{c_esc}*.")
        else:
            await safe_edit_text(query, f"⚠️ {msg}")
        return

    if data.startswith("del_yes_"):
        exp_id = int(data.split("_")[-1])
        success, desc = await delete_expense_by_id(user, exp_id)
        await clear_pending_action(chat_id)
        if success:
            desc_esc = escape_md(desc)
            await safe_edit_text(query, f"🗑️ Deleted *{desc_esc}*.")
        else:
            await safe_edit_text(query, "❌ Expense already deleted or not found.")
    elif data == "del_no":
        await clear_pending_action(chat_id)
        await safe_edit_text(query, "❌ Deletion cancelled.")
