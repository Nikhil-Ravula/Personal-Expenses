import html
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
from telegram.ext import ContextTypes

from tracker.models import User, Category, Expense, Budget, TelegramLink, TelegramSession
from tracker.services.filter_parser import parse_filter_args, apply_expense_filters
from tracker.services.budget_service import get_budget_status, check_budget_thresholds_after_expense, get_or_create_budget
from tracker.services.pdf_generator import generate_expense_pdf

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# HTML & Telegram Safe Sending Helpers
# --------------------------------------------------------------------------

def escape_html(text) -> str:
    """
    Safely escape characters for Telegram HTML mode:
    '&', '<', '>'
    Prevents tag injection and entity parsing errors when dynamic values
    (category names, descriptions, usernames, labels) contain symbols.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


# Backward-compatibility alias
def escape_md(text) -> str:
    return escape_html(text)


def strip_html(text: str) -> str:
    """Strips HTML tags for plain text fallback."""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)


async def safe_reply(update: Update, text: str, parse_mode: str = 'HTML', reply_markup=None):
    """
    Safely send a reply to Telegram using HTML. If Telegram rejects the message due to entity
    parsing errors, automatically fall back to sending plain text with stripped HTML tags
    so the user never sees raw tags or experiences silent command failure.
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
            clean_text = strip_html(text)
            return await target.reply_text(clean_text, parse_mode=None, reply_markup=reply_markup)
        except Exception as inner:
            logger.error(f"[safe_reply] Plain text fallback also failed: {inner}")
            return None


async def safe_edit_text(query, text: str, parse_mode: str = 'HTML', reply_markup=None):
    """
    Safely edit message text using HTML. Automatically falls back to plain text if HTML parsing fails.
    """
    try:
        return await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"[safe_edit_text] Edit failed with parse_mode={parse_mode}: {e}. Retrying as plain text.")
        try:
            clean_text = strip_html(text)
            return await query.edit_message_text(clean_text, parse_mode=None, reply_markup=reply_markup)
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
    uname_esc = escape_html(link.user.username)
    return True, f"✅ Successfully linked your Telegram account with user <b>{uname_esc}</b>! You can now use all commands."


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
                "\n\n💡 Type <code>/help</code> to see all commands."
                "\nQuick example: <code>/add food lunch 120</code>"
            )
        await safe_reply(update, reply)
        return

    # 2. Normal /start command
    if user:
        uname_esc = escape_html(user.username)
        msg = (
            f"👋 Welcome back, <b>{uname_esc}</b>!\n\n"
            "Your Telegram account is connected to <b>Smart Expense Tracker</b>.\n\n"
            "💡 Type <code>/help</code> to see the full list of commands.\n"
            "Quick example: <code>/add food pizza 150</code>"
        )
    else:
        msg = (
            "👋 Welcome to <b>Smart Expense Tracker Bot</b>!\n\n"
            "To link your Telegram account with your web dashboard:\n"
            "1. Log into your dashboard on the website.\n"
            "2. Navigate to your <b>Profile</b> page and click <b>Direct Redirect to Telegram</b>.\n"
            "3. Or send the command: <code>/link &lt;YOUR_CODE&gt;</code> (e.g. <code>/link A7X92B</code>)\n\n"
            "Once linked, all your expenses and reports will sync in real time!"
        )
    await safe_reply(update, msg)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📊 <b>Smart Expense Tracker — Commands</b>\n\n"
        "🔗 <b>Account Linking</b>\n"
        "• <code>/link &lt;code&gt;</code> — Connect Telegram to web dashboard\n\n"
        "💸 <b>Adding Expenses</b>\n"
        "• <code>/add &lt;category&gt; &lt;item&gt; &lt;amount&gt;</code>\n"
        "  <i>e.g. <code>/add food pizza 50</code> • <code>/add travel auto 20</code></i>\n\n"
        "📋 <b>Viewing Expenses</b>\n"
        "• <code>/show</code> — Recent expenses\n"
        "• <code>/show &lt;month&gt;</code> — e.g. <code>/show september</code>\n"
        "• <code>/show &lt;date&gt;</code> — e.g. <code>/show 26 september 2026</code>\n\n"
        "🗑️ <b>Deleting &amp; Editing</b>\n"
        "• <code>/delete &lt;number&gt;</code> — Delete item from last <code>/show</code> list\n"
        "• <code>/edit &lt;number&gt;</code> — Edit item from last <code>/show</code> list\n\n"
        "💰 <b>Totals &amp; Analytics</b>\n"
        "• <code>/total</code> — Total of all expenses\n"
        "• <code>/total &lt;month&gt;</code> — Total for month\n"
        "• <code>/total &lt;category&gt;</code> — Total for category\n"
        "• <code>/total &lt;month&gt; &lt;category&gt;</code> — Category total for month\n\n"
        "🏷️ <b>Categories</b>\n"
        "• <code>/create &lt;category&gt;</code> — Create custom category\n"
        "• <code>/categories</code> — View all categories\n"
        "• <code>/empty_categories</code> — View &amp; delete empty categories\n"
        "• <code>/delete_category &lt;name&gt;</code> — Delete empty category\n\n"
        "🎯 <b>Monthly Budget</b>\n"
        "• <code>/budget</code> — View current budget status\n"
        "• <code>/budget &lt;amount&gt;</code> — Set monthly limit\n"
        "• <code>/budget add &lt;amount&gt;</code> — Add to budget\n"
        "• <code>/budget remove &lt;amount&gt;</code> — Deduct from budget\n"
        "• <code>/budget remaining</code> — Quick remaining balance\n\n"
        "📄 <b>PDF Reports</b>\n"
        "• <code>/pdf</code> — Download full expense report\n"
        "• <code>/pdf &lt;month&gt;</code> — PDF for that month\n"
        "• <code>/pdf &lt;category&gt;</code> — PDF for that category"
    )
    await safe_reply(update, help_text)


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await safe_reply(
            update,
            "⚠️ Please provide your 6-digit link code.\n"
            "Format: <code>/link &lt;code&gt;</code> (e.g. <code>/link 4B9K2A</code>)\n"
            "Generate your code from the web Profile page."
        )
        return

    code = context.args[0]
    success, reply = await link_chat_id_with_code(chat_id, code)
    await safe_reply(update, reply)


async def create_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    if not context.args:
        await safe_reply(update, "⚠️ Please specify a category name.\nFormat: <code>/create &lt;category&gt;</code> (e.g. <code>/create Books</code>)")
        return

    cat_name = " ".join(context.args).strip()
    cat, created = await create_user_category(user, cat_name)
    cat_esc = escape_html(cat.name)
    if created:
        await safe_reply(update, f"✅ Category <b>{cat_esc}</b> created successfully!")
    else:
        await safe_reply(update, f"ℹ️ Category <b>{cat_esc}</b> already exists.")


async def categories_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    active, empty = await get_user_categories_data(user)

    if not active and not empty:
        await safe_reply(
            update,
            "🏷️ You have no categories yet.\n"
            "Create one using: <code>/create &lt;category&gt;</code> (e.g. <code>/create Shopping</code>)"
        )
        return

    lines = ["🏷️ <b>Your Expense Categories</b>", ""]

    if active:
        lines.append("<b>Active Categories:</b>")
        for c in active:
            c_esc = escape_html(c['name'])
            lines.append(f"• <b>{c_esc}</b> — {c['count']} expense(s) (<code>₹{c['total']:,.2f}</code>)")
        lines.append("")

    keyboard = []
    if empty:
        lines.append("🗑️ <b>Empty Categories (0 expenses • Safe to delete):</b>")
        for idx, c in enumerate(empty, start=1):
            c_esc = escape_html(c['name'])
            lines.append(f"<b>{idx}.</b> {c_esc} (0 expenses)")
            keyboard.append([
                InlineKeyboardButton(f"🗑️ Delete {c['name']}", callback_data=f"delcat_{c['id']}")
            ])
        lines.append("")
        lines.append("💡 <i>Tap a button above to delete, or send:</i> <code>/delete_category &lt;name&gt;</code>")
    else:
        lines.append("✨ All your categories currently have active expenses!")

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await safe_reply(update, "\n".join(lines), reply_markup=reply_markup)


async def empty_categories_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    _, empty = await get_user_categories_data(user)

    if not empty:
        await safe_reply(update, "✅ You have no empty categories! All categories have recorded expenses.")
        return

    lines = [
        "🗑️ <b>Empty Categories (0 Expenses)</b>",
        "These categories have no expenses and can safely be deleted:",
        ""
    ]
    keyboard = []
    for idx, c in enumerate(empty, start=1):
        c_esc = escape_html(c['name'])
        lines.append(f"<b>{idx}.</b> {c_esc}")
        keyboard.append([
            InlineKeyboardButton(f"🗑️ Delete {c['name']}", callback_data=f"delcat_{c['id']}")
        ])

    lines.append("")
    lines.append("💡 <i>Tap a button above to delete, or send:</i> <code>/delete_category &lt;name&gt;</code>")

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_reply(update, "\n".join(lines), reply_markup=reply_markup)


async def delete_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    if not context.args:
        await safe_reply(
            update,
            "⚠️ Please specify the category to delete.\n"
            "Usage: <code>/delete_category &lt;name&gt;</code> (e.g. <code>/delete_category daily_items</code>)\n"
            "💡 Use <code>/empty_categories</code> to see all empty categories."
        )
        return

    cat_query = " ".join(context.args).strip()
    success, cat_name, msg = await delete_user_category_by_id_or_name(user, cat_query)

    if success:
        c_esc = escape_html(cat_name)
        await safe_reply(update, f"🗑️ Deleted empty category <b>{c_esc}</b> successfully!")
    else:
        c_esc = escape_html(cat_name or cat_query)
        if "contains" in msg:
            await safe_reply(update, f"⚠️ Cannot delete category <b>{c_esc}</b> because it contains active expenses. Only empty categories can be deleted.")
        else:
            await safe_reply(update, f"❌ Category <b>{c_esc}</b> was not found.")


async def add_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    # Syntax: /add <category> <type> <price>
    # E.g. /add food pizza 50  OR  /add "travel expenses" metro 45
    if not context.args or len(context.args) < 3:
        await safe_reply(
            update,
            "⚠️ Invalid format.\n"
            "Usage: <code>/add &lt;category&gt; &lt;item&gt; &lt;price&gt;</code>\n\n"
            "Examples:\n"
            "• <code>/add food pizza 50</code>\n"
            "• <code>/add travel auto 10</code>"
        )
        return

    # The last token should be the price
    price_str = context.args[-1].replace('₹', '').replace(',', '').strip()
    try:
        price = Decimal(price_str)
        if price <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        price_esc = escape_html(price_str)
        await safe_reply(update, f"❌ Invalid price '<code>{price_esc}</code>'. Price must be a positive number.")
        return

    # Category is the first argument, and middle arguments form the description
    category_name = context.args[0]
    exp_type = " ".join(context.args[1:-1])

    expense, alerts = await add_expense_db(user, category_name, exp_type, price)

    type_esc = escape_html(expense.type)
    cat_esc = escape_html(expense.category.name)

    response_text = (
        f"✅ <b>Expense Added!</b>\n\n"
        f"• <b>Item:</b> {type_esc}\n"
        f"• <b>Amount:</b> <code>₹{expense.amount:,.2f}</code>\n"
        f"• <b>Category:</b> {cat_esc}\n"
        f"• <b>Date:</b> {expense.date.strftime('%d %b %Y')}"
    )

    if alerts:
        response_text += "\n\n" + "\n\n".join(alerts)

    await safe_reply(update, response_text)


def build_show_page_content(expenses, total_amount, total_count, current_page, total_pages, label, page_size=25):
    safe_label = escape_html(label)
    lines = [f"📋 <b>Expenses ({safe_label})</b>", ""]

    offset = (current_page - 1) * page_size
    for idx, e in enumerate(expenses, start=offset + 1):
        type_esc = escape_html(e.type)
        cat_esc = escape_html(e.category.name)
        lines.append(f"<b>{idx}.</b> {e.date.strftime('%d %b')} • <b>{type_esc}</b> ({cat_esc}) — <code>₹{e.amount:,.2f}</code>")

    lines.append("")
    if total_pages > 1:
        lines.append(f"💰 <b>Total:</b> <code>₹{total_amount:,.2f}</code> (Page {current_page} of {total_pages} • {total_count} items)")
    else:
        lines.append(f"💰 <b>Total:</b> <code>₹{total_amount:,.2f}</code> ({total_count} items)")

    lines.append("<i>Tip: To delete an item, reply <code>/delete &lt;number&gt;</code>.</i>")
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
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    page_size = 25
    expenses, total_amount, total_count, current_page, total_pages, label = await query_expenses_page_db(
        user, filter_text, page=1, page_size=page_size
    )

    safe_label = escape_html(label)

    if not expenses:
        await safe_reply(update, f"ℹ️ No expenses found for: <b>{safe_label}</b>.")
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
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    if not context.args or not context.args[0].isdigit():
        await safe_reply(
            update,
            "⚠️ Please specify the number from your last <code>/show</code> list.\n"
            "Example: <code>/delete 1</code>"
        )
        return

    item_num = int(context.args[0])
    shown_list, _, _ = await get_session_data(chat_id)

    if not shown_list:
        await safe_reply(update, "⚠️ No active list found. Please run <code>/show</code> first to view your expenses.")
        return

    if item_num < 1 or item_num > len(shown_list) or not shown_list[item_num - 1]:
        await safe_reply(update, f"❌ Invalid item number {item_num}. Please choose a number from your <code>/show</code> list.")
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

    type_esc = escape_html(exp.type)
    cat_esc = escape_html(exp.category.name)

    await safe_reply(
        update,
        f"❓ Are you sure you want to delete:\n<b>{type_esc}</b> — <code>₹{exp.amount:,.2f}</code> ({cat_esc}) on {exp.date.strftime('%d %b %Y')}?",
        reply_markup=reply_markup
    )


async def edit_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    if not context.args or not context.args[0].isdigit():
        await safe_reply(update, "⚠️ Usage: <code>/edit &lt;number&gt;</code>\nExample: <code>/edit 1</code> (referencing the last <code>/show</code> list)")
        return

    item_num = int(context.args[0])
    shown_list, _, _ = await get_session_data(chat_id)

    if not shown_list or item_num < 1 or item_num > len(shown_list) or not shown_list[item_num - 1]:
        await safe_reply(update, "❌ Invalid item number. Please use <code>/show</code> to see your current list.")
        return

    target_id = shown_list[item_num - 1]

    def fetch_expense():
        return Expense.objects.filter(id=target_id, user=user).first()

    exp = await sync_to_async(fetch_expense)()
    if not exp:
        await safe_reply(update, "❌ Expense not found.")
        return

    await set_pending_action(chat_id, action='edit_pending', data={'expense_id': target_id})
    type_esc = escape_html(exp.type)
    await safe_reply(
        update,
        f"✏️ Editing <b>{type_esc}</b> (Current amount: <code>₹{exp.amount:,.2f}</code>).\n\n"
        "Please reply with the new description and amount:\n"
        "Format: <code>&lt;description&gt; &lt;amount&gt;</code> (e.g. <code>Pizza with cheese 60</code>)"
    )


async def total_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    total, count, label = await query_total_db(user, filter_text)

    safe_label = escape_html(label)
    msg = (
        f"📊 <b>Expense Total</b>\n\n"
        f"• <b>Scope:</b> {safe_label}\n"
        f"• <b>Total Amount:</b> <code>₹{total:,.2f}</code>\n"
        f"• <b>Transactions:</b> {count}"
    )
    await safe_reply(update, msg)


async def pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
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
        await safe_reply(update, "⚠️ Please link your account first using <code>/link &lt;code&gt;</code>.")
        return

    args = context.args

    # 1. /budget (view current)
    if not args:
        status = await get_budget_status_db(user)
        if not status['has_budget']:
            await safe_reply(
                update,
                f"ℹ️ No budget set for <b>{timezone.now().strftime('%B %Y')}</b>.\n"
                "To set a budget limit, send: <code>/budget &lt;amount&gt;</code> (e.g. <code>/budget 5000</code>)"
            )
            return

        status_icon = "🚨" if status['is_over'] else ("⚠️" if status['percent_spent'] >= 80 else "✅")
        msg = (
            f"{status_icon} <b>Monthly Budget Status ({timezone.now().strftime('%B %Y')})</b>\n\n"
            f"• <b>Budget Limit:</b> <code>₹{status['budget_amount']:,.2f}</code>\n"
            f"• <b>Total Spent:</b> <code>₹{status['total_spent']:,.2f}</code> ({status['percent_spent']}%)\n"
            f"• <b>Remaining:</b> <code>₹{status['remaining']:,.2f}</code>\n"
        )
        if status['is_over']:
            msg += f"\n🚨 <b>Over Budget by <code>₹{abs(status['remaining']):,.2f}</code>!</b>"
        await safe_reply(update, msg)
        return

    first_arg = args[0].lower()

    # 2. /budget remaining
    if first_arg == 'remaining':
        status = await get_budget_status_db(user)
        if not status['has_budget']:
            await safe_reply(update, "ℹ️ No budget set for this month yet. Set one via <code>/budget &lt;amount&gt;</code>.")
            return
        await safe_reply(update, f"💰 <b>Remaining budget for this month:</b> <code>₹{status['remaining']:,.2f}</code>")
        return

    # 3. /budget add <amount>
    if first_arg == 'add':
        if len(args) < 2:
            await safe_reply(update, "⚠️ Usage: <code>/budget add &lt;amount&gt;</code> (e.g. <code>/budget add 1000</code>)")
            return
        try:
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='add', amount_val=amt)
            await safe_reply(update, f"✅ Added <b>₹{amt:,.2f}</b>.\nNew budget for this month: <code>₹{budget.amount:,.2f}</code>")
        except (InvalidOperation, ValueError):
            await safe_reply(update, "❌ Invalid amount.")
        return

    # 4. /budget remove <amount>
    if first_arg == 'remove':
        if len(args) < 2:
            await safe_reply(update, "⚠️ Usage: <code>/budget remove &lt;amount&gt;</code> (e.g. <code>/budget remove 500</code>)")
            return
        try:
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='remove', amount_val=amt)
            await safe_reply(update, f"✅ Deducted <b>₹{amt:,.2f}</b>.\nNew budget for this month: <code>₹{budget.amount:,.2f}</code>")
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
            await safe_reply(update, f"🎯 Budget for month <b>{month_val}</b> set to <code>₹{budget.amount:,.2f}</code>.")
            return

        amt = Decimal(first_arg)
        budget = await modify_budget_db(user, action='set', amount_val=amt)
        await safe_reply(update, f"🎯 Budget for <b>{timezone.now().strftime('%B %Y')}</b> set to <code>₹{budget.amount:,.2f}</code>.")
    except (InvalidOperation, ValueError):
        await safe_reply(
            update,
            "⚠️ <b>Invalid budget command.</b>\n\n"
            "Examples:\n"
            "• <code>/budget 5000</code>\n"
            "• <code>/budget september 6000</code>\n"
            "• <code>/budget add 1000</code>\n"
            "• <code>/budget remove 500</code>\n"
            "• <code>/budget remaining</code>"
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
                desc_esc = escape_html(desc)
                await safe_reply(update, f"🗑️ Deleted <b>{desc_esc}</b>.")
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
            await safe_reply(update, f"🎯 Budget for <b>{timezone.now().strftime('%B %Y')}</b> set to <code>₹{budget.amount:,.2f}</code>!")
        except (InvalidOperation, ValueError):
            await safe_reply(update, "Please reply with a valid number for your budget, or send <code>/help</code>.")
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
                    type_esc = escape_html(exp.type)
                    await safe_reply(update, f"✅ Updated to <b>{type_esc}</b> — <code>₹{exp.amount:,.2f}</code>!")
                else:
                    await safe_reply(update, "❌ Expense not found.")
                return
            except (InvalidOperation, ValueError):
                pass
        await safe_reply(update, "⚠️ Format: <code>&lt;description&gt; &lt;amount&gt;</code> (e.g. <code>Dinner 150</code>) or type <code>/cancel</code>.")


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
            c_esc = escape_html(cat_name)
            await safe_edit_text(query, f"🗑️ Deleted empty category <b>{c_esc}</b>.")
        else:
            await safe_edit_text(query, f"⚠️ {escape_html(msg)}")
        return

    if data.startswith("del_yes_"):
        exp_id = int(data.split("_")[-1])
        success, desc = await delete_expense_by_id(user, exp_id)
        await clear_pending_action(chat_id)
        if success:
            desc_esc = escape_html(desc)
            await safe_edit_text(query, f"🗑️ Deleted <b>{desc_esc}</b>.")
        else:
            await safe_edit_text(query, "❌ Expense already deleted or not found.")
    elif data == "del_no":
        await clear_pending_action(chat_id)
        await safe_edit_text(query, "❌ Deletion cancelled.")
