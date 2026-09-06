import re
from io import BytesIO
from decimal import Decimal, InvalidOperation
from datetime import date
from django.utils import timezone
from django.db.models import Sum
from asgiref.sync import sync_to_async
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from tracker.models import User, Category, Expense, Budget, TelegramLink, TelegramSession
from tracker.services.filter_parser import parse_filter_args, apply_expense_filters
from tracker.services.budget_service import get_budget_status, check_budget_thresholds_after_expense, get_or_create_budget
from tracker.services.pdf_generator import generate_expense_pdf


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
    return True, f"✅ Successfully linked your Telegram account with user **{link.user.username}**! You can now use all commands."


@sync_to_async
def create_user_category(user, cat_name: str):
    name_clean = cat_name.strip().capitalize()
    cat, created = Category.objects.get_or_create(user=user, name=name_clean)
    return cat, created


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
def query_expenses_db(user, filter_text: str):
    filter_dict = parse_filter_args(filter_text, user=user)
    qs = Expense.objects.filter(user=user).select_related('category')
    qs = apply_expense_filters(qs, filter_dict).order_by('-date', '-created_at')[:30]
    expenses = list(qs)
    total = sum((e.amount for e in expenses), Decimal('0.00'))
    return expenses, total, filter_dict['label']


@sync_to_async
def store_shown_list(chat_id: int, expense_ids: list):
    session, _ = TelegramSession.objects.get_or_create(chat_id=chat_id)
    session.last_shown_list = expense_ids
    session.save(update_fields=['last_shown_list', 'updated_at'])


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
        await update.message.reply_text(reply, parse_mode='Markdown')
        return

    # 2. Normal /start command
    if user:
        msg = (
            f"👋 Welcome back, **{user.username}**!\n\n"
            "Your Telegram account is connected to **Smart Expense Tracker**.\n\n"
            "💡 Type `/help` to see the full list of commands.\n"
            "Quick example: `/add food pizza 150`"
        )
    else:
        msg = (
            "👋 Welcome to **Smart Expense Tracker Bot**!\n\n"
            "To link your Telegram account with your web dashboard:\n"
            "1. Log into your dashboard on the website.\n"
            "2. Navigate to your **Profile** page and click **Direct Redirect to Telegram**.\n"
            "3. Or send the command: `/link <YOUR_CODE>` (e.g. `/link A7X92B`)\n\n"
            "Once linked, all your expenses and reports will sync in real time!"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📊 **Smart Expense Tracker - Available Commands**\n\n"
        "🔗 **Account Linking**\n"
        "• `/link <code>` — Connect your Telegram to your web account\n\n"
        "💸 **Adding Expenses**\n"
        "• `/add <category> <type> <price>`\n"
        "  _Examples:_ `/add food pizza 50` • `/add travel auto 20`\n\n"
        "📋 **Viewing Expenses**\n"
        "• `/show` — Show recent expenses\n"
        "• `/show <month>` — e.g. `/show september`\n"
        "• `/show <date>` — e.g. `/show 26 september 2026`\n\n"
        "🗑️ **Deleting & Editing**\n"
        "• `/delete <number>` — Delete item at that position from the last `/show` list\n"
        "• `/edit <number>` — Modify description/amount of item from the last `/show` list\n\n"
        "💰 **Totals & Analytics**\n"
        "• `/total` — Total of all expenses\n"
        "• `/total <month>` — Total for that month\n"
        "• `/total <category>` — Total for that category\n"
        "• `/total <month> <category>` — Category total for that month\n\n"
        "🏷️ **Categories**\n"
        "• `/create <category>` — Create custom category (e.g. `/create shopping`)\n\n"
        "🎯 **Monthly Budget**\n"
        "• `/budget` — View current budget status, spent & remaining\n"
        "• `/budget <amount>` — Set budget limit for current month\n"
        "• `/budget add <amount>` — Add amount to current budget\n"
        "• `/budget remove <amount>` — Subtract amount from budget\n"
        "• `/budget remaining` — Show only remaining budget\n\n"
        "📄 **PDF Reports**\n"
        "• `/pdf` — Download PDF of all expenses\n"
        "• `/pdf <month>` — PDF for that month (e.g. `/pdf september`)\n"
        "• `/pdf <category>` — PDF for that category\n"
        "• `/pdf <month> <category>` — PDF for category within that month"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide your 6-digit link code.\n"
            "Format: `/link <code>` (e.g. `/link 4B9K2A`)\n"
            "Generate your code from the web Profile page.",
            parse_mode='Markdown'
        )
        return

    code = context.args[0]
    success, reply = await link_chat_id_with_code(chat_id, code)
    await update.message.reply_text(reply, parse_mode='Markdown')


async def create_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    if not context.args:
        await update.message.reply_text("⚠️ Please specify a category name.\nFormat: `/create <category>` (e.g. `/create Books`)", parse_mode='Markdown')
        return

    cat_name = " ".join(context.args).strip()
    cat, created = await create_user_category(user, cat_name)
    if created:
        await update.message.reply_text(f"✅ Category **{cat.name}** created successfully!", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"ℹ️ Category **{cat.name}** already exists.", parse_mode='Markdown')


async def add_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    # Syntax: /add <category> <type> <price>
    # E.g. /add food pizza 50  OR  /add "travel expenses" metro 45
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "⚠️ Invalid format.\n"
            "Usage: `/add <category> <type> <price>`\n"
            "Examples:\n"
            "• `/add food pizza 50`\n"
            "• `/add travel auto 10`",
            parse_mode='Markdown'
        )
        return

    # The last token should be the price
    price_str = context.args[-1].replace('₹', '').replace(',', '').strip()
    try:
        price = Decimal(price_str)
        if price <= 0:
            raise ValueError()
    except (InvalidOperation, ValueError):
        await update.message.reply_text(f"❌ Invalid price '{price_str}'. Price must be a positive number.", parse_mode='Markdown')
        return

    # Category is the first argument, and middle arguments form the description
    category_name = context.args[0]
    exp_type = " ".join(context.args[1:-1])

    expense, alerts = await add_expense_db(user, category_name, exp_type, price)

    response_text = (
        f"✅ **Expense Added!**\n"
        f"• **Item:** {expense.type}\n"
        f"• **Amount:** ₹{expense.amount:,.2f}\n"
        f"• **Category:** {expense.category.name}\n"
        f"• **Date:** {expense.date.strftime('%d %b %Y')}"
    )

    if alerts:
        response_text += "\n\n" + "\n\n".join(alerts)

    await update.message.reply_text(response_text, parse_mode='Markdown')


async def show_expenses_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    expenses, total, label = await query_expenses_db(user, filter_text)

    if not expenses:
        await update.message.reply_text(f"ℹ️ No expenses found for: **{label}**.", parse_mode='Markdown')
        return

    # Store shown IDs in session for /delete and /edit
    expense_ids = [e.id for e in expenses]
    await store_shown_list(chat_id, expense_ids)

    lines = [f"📋 **Expenses ({label})**", ""]
    for idx, e in enumerate(expenses, start=1):
        lines.append(f"`{idx}.` {e.date.strftime('%d %b')} • **{e.type}** ({e.category.name}) — `₹{e.amount:,.2f}`")

    lines.append("")
    lines.append(f"💰 **Total:** `₹{total:,.2f}` ({len(expenses)} items)")
    lines.append("_Tip: To delete an item, reply `/delete <number>`._")

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


async def delete_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "⚠️ Please specify the number from your last `/show` list.\n"
            "Example: `/delete 1`",
            parse_mode='Markdown'
        )
        return

    item_num = int(context.args[0])
    shown_list, _, _ = await get_session_data(chat_id)

    if not shown_list:
        await update.message.reply_text("⚠️ No active list found. Please run `/show` first to view your expenses.", parse_mode='Markdown')
        return

    if item_num < 1 or item_num > len(shown_list):
        await update.message.reply_text(f"❌ Invalid item number {item_num}. Please choose between 1 and {len(shown_list)}.", parse_mode='Markdown')
        return

    target_id = shown_list[item_num - 1]

    # Look up expense details to confirm
    def fetch_expense():
        return Expense.objects.filter(id=target_id, user=user).select_related('category').first()

    exp = await sync_to_async(fetch_expense)()
    if not exp:
        await update.message.reply_text("❌ Expense not found (it may have already been deleted).", parse_mode='Markdown')
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

    await update.message.reply_text(
        f"❓ Are you sure you want to delete:\n**{exp.type}** — ₹{exp.amount:,.2f} ({exp.category.name}) on {exp.date.strftime('%d %b %Y')}?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def edit_expense_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: `/edit <number>`\nExample: `/edit 1` (referencing the last `/show` list)", parse_mode='Markdown')
        return

    item_num = int(context.args[0])
    shown_list, _, _ = await get_session_data(chat_id)

    if not shown_list or item_num < 1 or item_num > len(shown_list):
        await update.message.reply_text("❌ Invalid item number. Please use `/show` to see your current list.", parse_mode='Markdown')
        return

    target_id = shown_list[item_num - 1]

    def fetch_expense():
        return Expense.objects.filter(id=target_id, user=user).first()

    exp = await sync_to_async(fetch_expense)()
    if not exp:
        await update.message.reply_text("❌ Expense not found.", parse_mode='Markdown')
        return

    await set_pending_action(chat_id, action='edit_pending', data={'expense_id': target_id})
    await update.message.reply_text(
        f"✏️ Editing **{exp.type}** (Current amount: ₹{exp.amount}).\n\n"
        "Please reply with the new description and amount:\n"
        "Format: `<description> <amount>` (e.g. `Pizza with cheese 60`)",
        parse_mode='Markdown'
    )


async def total_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    total, count, label = await query_total_db(user, filter_text)

    msg = (
        f"📊 **Expense Total**\n"
        f"• **Scope:** {label}\n"
        f"• **Total Amount:** `₹{total:,.2f}`\n"
        f"• **Transactions:** {count}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    filter_text = " ".join(context.args).strip() if context.args else ""
    status_msg = await update.message.reply_text("⏳ Generating your PDF report...", parse_mode='Markdown')

    try:
        pdf_bytes, filename = await generate_pdf_for_user(user, filter_text)
        await context.bot.send_document(
            chat_id=chat_id,
            document=BytesIO(pdf_bytes),
            filename=filename,
            caption=f"📄 Expense Report • Smart Tracker"
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Failed to generate PDF: {str(e)}")


async def budget_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("⚠️ Please link your account first using `/link <code>`.", parse_mode='Markdown')
        return

    args = context.args

    # 1. /budget (view current)
    if not args:
        status = await get_budget_status_db(user)
        if not status['has_budget']:
            await update.message.reply_text(
                f"ℹ️ No budget set for {timezone.now().strftime('%B %Y')}.\n"
                "To set a budget limit, send: `/budget <amount>` (e.g. `/budget 5000`)",
                parse_mode='Markdown'
            )
            return

        status_icon = "🚨" if status['is_over'] else ("⚠️" if status['percent_spent'] >= 80 else "✅")
        msg = (
            f"{status_icon} **Monthly Budget Status ({timezone.now().strftime('%B %Y')})**\n\n"
            f"• **Budget Limit:** ₹{status['budget_amount']:,.2f}\n"
            f"• **Total Spent:** ₹{status['total_spent']:,.2f} ({status['percent_spent']}%)\n"
            f"• **Remaining:** ₹{status['remaining']:,.2f}\n"
        )
        if status['is_over']:
            msg += f"\n🚨 **Over Budget by ₹{abs(status['remaining']):,.2f}!**"
        await update.message.reply_text(msg, parse_mode='Markdown')
        return

    first_arg = args[0].lower()

    # 2. /budget remaining
    if first_arg == 'remaining':
        status = await get_budget_status_db(user)
        if not status['has_budget']:
            await update.message.reply_text("ℹ️ No budget set for this month yet. Set one via `/budget <amount>`.", parse_mode='Markdown')
            return
        await update.message.reply_text(f"💰 Remaining budget for this month: **₹{status['remaining']:,.2f}**", parse_mode='Markdown')
        return

    # 3. /budget add <amount>
    if first_arg == 'add':
        if len(args) < 2:
            await update.message.reply_text("⚠️ Usage: `/budget add <amount>` (e.g. `/budget add 1000`)", parse_mode='Markdown')
            return
        try:
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='add', amount_val=amt)
            await update.message.reply_text(f"✅ Added ₹{amt:,.2f}. New budget for this month: **₹{budget.amount:,.2f}**", parse_mode='Markdown')
        except (InvalidOperation, ValueError):
            await update.message.reply_text("❌ Invalid amount.", parse_mode='Markdown')
        return

    # 4. /budget remove <amount>
    if first_arg == 'remove':
        if len(args) < 2:
            await update.message.reply_text("⚠️ Usage: `/budget remove <amount>` (e.g. `/budget remove 500`)", parse_mode='Markdown')
            return
        try:
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='remove', amount_val=amt)
            await update.message.reply_text(f"✅ Deducted ₹{amt:,.2f}. New budget for this month: **₹{budget.amount:,.2f}**", parse_mode='Markdown')
        except (InvalidOperation, ValueError):
            await update.message.reply_text("❌ Invalid amount.", parse_mode='Markdown')
        return

    # 5. /budget <amount> OR /budget <month> <amount>
    try:
        # Check if first arg is month name
        parsed = parse_filter_args(first_arg)
        if parsed['month'] and len(args) >= 2:
            month_val = parsed['month']
            amt = Decimal(args[1])
            budget = await modify_budget_db(user, action='set', amount_val=amt, month=month_val)
            await update.message.reply_text(f"🎯 Budget for month {month_val} set to **₹{budget.amount:,.2f}**.", parse_mode='Markdown')
            return

        amt = Decimal(first_arg)
        budget = await modify_budget_db(user, action='set', amount_val=amt)
        await update.message.reply_text(f"🎯 Budget for {timezone.now().strftime('%B %Y')} set to **₹{budget.amount:,.2f}**.", parse_mode='Markdown')
    except (InvalidOperation, ValueError):
        await update.message.reply_text(
            "⚠️ Invalid budget command.\n"
            "Examples:\n"
            "• `/budget 5000`\n"
            "• `/budget september 6000`\n"
            "• `/budget add 1000`\n"
            "• `/budget remove 500`\n"
            "• `/budget remaining`",
            parse_mode='Markdown'
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
                await update.message.reply_text(f"🗑️ Deleted **{desc}**.", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Expense already deleted or not found.", parse_mode='Markdown')
        elif text.lower() in ['no', 'n', 'cancel']:
            await clear_pending_action(chat_id)
            await update.message.reply_text("❌ Deletion cancelled.", parse_mode='Markdown')
        return

    if pending_action == 'set_monthly_budget':
        # Auto-prompt reply on 1st of month: a plain numeric reply saves as budget
        try:
            amt = Decimal(text.replace('₹', '').replace(',', '').strip())
            budget = await modify_budget_db(user, action='set', amount_val=amt)
            await clear_pending_action(chat_id)
            await update.message.reply_text(f"🎯 Budget for {timezone.now().strftime('%B %Y')} set to **₹{budget.amount:,.2f}**!", parse_mode='Markdown')
        except (InvalidOperation, ValueError):
            await update.message.reply_text("Please reply with a valid number for your budget, or send `/help`.", parse_mode='Markdown')
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
                    await update.message.reply_text(f"✅ Updated to **{exp.type}** — ₹{exp.amount:,.2f}!", parse_mode='Markdown')
                else:
                    await update.message.reply_text("❌ Expense not found.", parse_mode='Markdown')
                return
            except (InvalidOperation, ValueError):
                pass
        await update.message.reply_text("⚠️ Format: `<description> <amount>` (e.g. `Dinner 150`) or type `/cancel`.", parse_mode='Markdown')


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user = await get_user_by_chat_id(chat_id)
    if not user:
        return

    data = query.data
    if data.startswith("del_yes_"):
        exp_id = int(data.split("_")[-1])
        success, desc = await delete_expense_by_id(user, exp_id)
        await clear_pending_action(chat_id)
        if success:
            await query.edit_message_text(f"🗑️ Deleted **{desc}**.", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Expense already deleted or not found.", parse_mode='Markdown')
    elif data == "del_no":
        await clear_pending_action(chat_id)
        await query.edit_message_text("❌ Deletion cancelled.")
