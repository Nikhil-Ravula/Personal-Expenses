from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum
from tracker.models import Budget, Expense


def get_or_create_budget(user, month=None, year=None, default_amount=Decimal('0.00')):
    now = timezone.now().date()
    month = month or now.month
    year = year or now.year

    budget, created = Budget.objects.get_or_create(
        user=user,
        month=month,
        year=year,
        defaults={'amount': default_amount}
    )
    return budget, created


def get_budget_status(user, month=None, year=None):
    """
    Returns spending status and budget analytics for the user for the given month/year.
    """
    now = timezone.now().date()
    month = month or now.month
    year = year or now.year

    budget = Budget.objects.filter(user=user, month=month, year=year).first()
    budget_amount = budget.amount if budget else Decimal('0.00')

    total_spent_data = Expense.objects.filter(
        user=user,
        date__year=year,
        date__month=month
    ).aggregate(total=Sum('amount'))

    total_spent = total_spent_data['total'] or Decimal('0.00')
    remaining = budget_amount - total_spent

    percent = 0.0
    if budget_amount > 0:
        percent = float((total_spent / budget_amount) * 100)

    is_over = total_spent > budget_amount if budget_amount > 0 else False

    return {
        'budget': budget,
        'budget_amount': budget_amount,
        'has_budget': budget is not None and budget_amount > 0,
        'total_spent': total_spent,
        'remaining': remaining,
        'percent_spent': round(percent, 1),
        'is_over': is_over,
        'month': month,
        'year': year
    }


def check_budget_thresholds_after_expense(user, expense_date=None):
    """
    Checks if spending crossed 80% or 100% threshold for the expense's month.
    Returns:
      list of alert message strings to send the user (if any threshold was just crossed)
    """
    date_val = expense_date or timezone.now().date()
    budget = Budget.objects.filter(user=user, month=date_val.month, year=date_val.year).first()

    if not budget or budget.amount <= 0:
        return []

    status = get_budget_status(user, month=date_val.month, year=date_val.year)
    spent = status['total_spent']
    limit = budget.amount
    alerts = []

    # 100% threshold
    if spent >= limit:
        if not budget.notified_100:
            budget.notified_100 = True
            budget.notified_80 = True  # Ensure 80 flag is also marked so it won't fire retroactively
            budget.save(update_fields=['notified_100', 'notified_80'])
            over_amount = spent - limit
            alerts.append(
                f"🚨 **Budget Limit Exceeded!**\n"
                f"You have spent **₹{spent:,.2f}** of your **₹{limit:,.2f}** limit for {date_val.strftime('%B %Y')}.\n"
                f"You are over budget by **₹{over_amount:,.2f}**."
            )
    # 80% threshold
    elif spent >= (limit * Decimal('0.80')):
        if not budget.notified_80:
            budget.notified_80 = True
            budget.save(update_fields=['notified_80'])
            alerts.append(
                f"⚠️ **Budget Alert (80% Reached)**\n"
                f"You have spent **₹{spent:,.2f}** (80%+) of your **₹{limit:,.2f}** monthly budget for {date_val.strftime('%B %Y')}.\n"
                f"Remaining budget: **₹{status['remaining']:,.2f}**."
            )

    return alerts
