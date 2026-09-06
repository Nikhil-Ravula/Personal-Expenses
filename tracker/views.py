import json
from decimal import Decimal
from datetime import date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Sum, Count
from django.core.paginator import Paginator
from django.conf import settings

from .models import Expense, Category, Budget, TelegramLink
from .forms import ExpenseForm, RegisterForm
from .services.filter_parser import parse_filter_args, apply_expense_filters
from .services.budget_service import get_budget_status, check_budget_thresholds_after_expense
from .services.pdf_generator import generate_expense_pdf


@login_required
def dashboard_view(request):
    user = request.user
    today = timezone.now().date()
    month = today.month
    year = today.year

    # 1. Budget & Spending Status
    status = get_budget_status(user, month=month, year=year)

    # 2. Category distribution (Current Month)
    category_qs = (
        Expense.objects.filter(user=user, date__year=year, date__month=month)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    cat_labels = [c['category__name'] for c in category_qs]
    cat_data = [float(c['total']) for c in category_qs]
    top_category = category_qs[0]['category__name'] if category_qs else "None"

    # 3. Last 6 Months Spending Trend
    trend_labels = []
    trend_data = []
    for i in range(5, -1, -1):
        # Calculate month i months ago
        first_day_current = date(year, month, 1)
        # Approximate previous month offset
        month_offset = month - i
        y = year
        m = month_offset
        while m <= 0:
            m += 12
            y -= 1

        month_name = date(y, m, 1).strftime("%b '%y")
        trend_labels.append(month_name)

        month_sum = (
            Expense.objects.filter(user=user, date__year=y, date__month=m)
            .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        )
        trend_data.append(float(month_sum))

    # 4. Recent Expenses
    recent_expenses = (
        Expense.objects.filter(user=user)
        .select_related('category')
        .order_by('-date', '-created_at')[:6]
    )

    # 5. Total Transactions this Month
    transaction_count = Expense.objects.filter(user=user, date__year=year, date__month=month).count()

    context = {
        'status': status,
        'cat_labels_json': json.dumps(cat_labels),
        'cat_data_json': json.dumps(cat_data),
        'trend_labels_json': json.dumps(trend_labels),
        'trend_data_json': json.dumps(trend_data),
        'top_category': top_category,
        'recent_expenses': recent_expenses,
        'transaction_count': transaction_count,
        'current_month_name': today.strftime("%B %Y"),
    }
    return render(request, 'tracker/dashboard.html', context)


@login_required
def expenses_list_view(request):
    user = request.user
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category')
    sort_by = request.GET.get('sort', '-date')

    qs = Expense.objects.filter(user=user).select_related('category')

    filter_label = "All Expenses"
    if query:
        filter_dict = parse_filter_args(query, user=user)
        qs = apply_expense_filters(qs, filter_dict)
        filter_label = filter_dict.get('label', query)

    if category_id:
        qs = qs.filter(category_id=category_id)
        cat = Category.objects.filter(id=category_id, user=user).first()
        if cat:
            filter_label += f" • {cat.name}"

    # Sorting
    valid_sorts = ['date', '-date', 'amount', '-amount', 'type', '-type', 'category__name', '-category__name']
    if sort_by in valid_sorts:
        qs = qs.order_by(sort_by, '-created_at')
    else:
        qs = qs.order_by('-date', '-created_at')

    # Total of filtered results
    filtered_total = qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    filtered_count = qs.count()

    # Pagination
    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    categories = Category.objects.filter(user=user).order_by('name')

    context = {
        'page_obj': page_obj,
        'categories': categories,
        'query': query,
        'selected_category': int(category_id) if category_id and category_id.isdigit() else '',
        'sort_by': sort_by,
        'filtered_total': filtered_total,
        'filtered_count': filtered_count,
        'filter_label': filter_label,
    }
    return render(request, 'tracker/expenses.html', context)


@login_required
def expense_create_view(request):
    user = request.user
    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = user
            expense.created_via = 'web'

            # Handle new category creation on the fly
            new_cat_name = form.cleaned_data.get('new_category', '').strip()
            if new_cat_name:
                category, _ = Category.objects.get_or_create(
                    user=user,
                    name=new_cat_name.capitalize()
                )
                expense.category = category
            elif not expense.category_id:
                # Fallback to default Food or first category
                first_cat = Category.objects.filter(user=user).first()
                if not first_cat:
                    first_cat = Category.objects.create(user=user, name='General')
                expense.category = first_cat

            expense.save()
            messages.success(request, f"Expense '{expense.type}' of ₹{expense.amount} added successfully!")

            # Budget threshold check
            alerts = check_budget_thresholds_after_expense(user, expense.date)
            for alert in alerts:
                # Remove markdown formatting for web flash message
                clean_alert = alert.replace('*', '')
                messages.warning(request, clean_alert)

            return redirect('expenses')
    else:
        form = ExpenseForm(user=user, initial={'date': timezone.now().date()})

    context = {
        'form': form,
        'title': 'Add New Expense',
        'button_text': 'Add Expense',
    }
    return render(request, 'tracker/expense_form.html', context)


@login_required
def expense_edit_view(request, pk):
    user = request.user
    expense = get_object_or_404(Expense, pk=pk, user=user)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense, user=user)
        if form.is_valid():
            new_cat_name = form.cleaned_data.get('new_category', '').strip()
            if new_cat_name:
                category, _ = Category.objects.get_or_create(
                    user=user,
                    name=new_cat_name.capitalize()
                )
                expense.category = category
            form.save()
            messages.success(request, f"Expense '{expense.type}' updated successfully!")
            return redirect('expenses')
    else:
        form = ExpenseForm(instance=expense, user=user)

    context = {
        'form': form,
        'title': 'Edit Expense',
        'button_text': 'Save Changes',
        'is_edit': True,
        'expense': expense,
    }
    return render(request, 'tracker/expense_form.html', context)


@login_required
def expense_delete_view(request, pk):
    user = request.user
    expense = get_object_or_404(Expense, pk=pk, user=user)
    if request.method == 'POST':
        exp_title = expense.type
        expense.delete()
        messages.info(request, f"Expense '{exp_title}' was deleted.")
        return redirect('expenses')
    return redirect('expenses')


@login_required
def export_pdf_view(request):
    user = request.user
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category')

    qs = Expense.objects.filter(user=user).select_related('category')
    filter_label = "All Expenses"

    if query:
        filter_dict = parse_filter_args(query, user=user)
        qs = apply_expense_filters(qs, filter_dict)
        filter_label = filter_dict.get('label', query)

    if category_id:
        qs = qs.filter(category_id=category_id)
        cat = Category.objects.filter(id=category_id, user=user).first()
        if cat:
            filter_label += f" • {cat.name}"

    qs = qs.order_by('-date', '-created_at')

    pdf_bytes, filename = generate_expense_pdf(
        expenses_qs=qs,
        title="Expense Report",
        filter_label=filter_label,
        user=user
    )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def telegram_redirect_view(request):
    user = request.user
    link, _ = TelegramLink.objects.get_or_create(user=user)
    bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', 'samrt_personal_tracker_bot')

    if not link.is_linked:
        if not link.link_code:
            link.generate_code()
        url = f"https://t.me/{bot_username}?start={link.link_code}"
    else:
        url = f"https://t.me/{bot_username}"

    return redirect(url)


@login_required
def profile_view(request):
    user = request.user
    link, _ = TelegramLink.objects.get_or_create(user=user)
    bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', 'samrt_personal_tracker_bot')

    # Automatically ensure link code is generated so direct Telegram deep-link is ready
    if not link.is_linked and not link.link_code:
        link.generate_code()

    if request.method == 'POST':
        if 'generate_code' in request.POST:
            code = link.generate_code()
            messages.success(request, f"New Telegram link code generated: {code}")
            return redirect('profile')
        elif 'unlink' in request.POST:
            link.chat_id = None
            link.linked_at = None
            link.save()
            messages.info(request, "Telegram account unlinked.")
            return redirect('profile')

    # Current month's budget
    now = timezone.now().date()
    current_budget = Budget.objects.filter(user=user, month=now.month, year=now.year).first()

    telegram_url = f"https://t.me/{bot_username}?start={link.link_code}" if link.link_code and not link.is_linked else f"https://t.me/{bot_username}"

    context = {
        'user': user,
        'link': link,
        'current_budget': current_budget,
        'current_month_name': now.strftime("%B %Y"),
        'bot_username': bot_username,
        'telegram_url': telegram_url,
    }
    return render(request, 'tracker/profile.html', context)


@login_required
def set_budget_view(request):
    if request.method == 'POST':
        user = request.user
        amount_str = request.POST.get('amount', '').strip()
        month_str = request.POST.get('month')
        year_str = request.POST.get('year')

        now = timezone.now().date()
        month = int(month_str) if month_str and month_str.isdigit() else now.month
        year = int(year_str) if year_str and year_str.isdigit() else now.year

        try:
            amount = Decimal(amount_str)
            if amount < 0:
                raise ValueError("Amount cannot be negative")

            budget, created = Budget.objects.update_or_create(
                user=user,
                month=month,
                year=year,
                defaults={
                    'amount': amount,
                    'notified_80': False,
                    'notified_100': False
                }
            )
            messages.success(request, f"Budget for {date(year, month, 1).strftime('%B %Y')} set to ₹{amount:,.2f}!")
        except Exception as e:
            messages.error(request, f"Invalid budget amount: {e}")

    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            # Log in immediately
            login(request, user)
            messages.success(request, f"Welcome to Smart Tracker, {user.username}! Your account is ready.")
            return redirect('dashboard')
    else:
        form = RegisterForm()

    return render(request, 'tracker/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()

    return render(request, 'tracker/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')
