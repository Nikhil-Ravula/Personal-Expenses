import re
import calendar
from datetime import datetime, date, timedelta
from dateutil import parser as date_parser
from django.utils import timezone
from django.db import models
from tracker.models import Category

MONTH_NAMES = {
    'january': 1, 'jan': 1,
    'february': 2, 'feb': 2,
    'march': 3, 'mar': 3,
    'april': 4, 'apr': 4,
    'may': 5,
    'june': 6, 'jun': 6,
    'july': 7, 'jul': 7,
    'august': 8, 'aug': 8,
    'september': 9, 'sept': 9, 'sep': 9,
    'october': 10, 'oct': 10,
    'november': 11, 'nov': 11,
    'december': 12, 'dec': 12
}


def parse_filter_args(arg_text: str, user=None, default_to_current_month: bool = True) -> dict:
    """
    Parses natural filter arguments across Telegram bot and web search.
    By default (default_to_current_month=True), scopes to the current month unless
    a specific date/month or 'all' is explicitly provided.

    Examples:
      - '' (default) -> month=current_month, year=current_year (e.g. October 2026)
      - 'all' -> all-time (no month/year filtering)
      - 'food' -> month=current_month, year=current_year, category='Food'
      - 'food oct' -> month=10, year=current_year, category='Food'
      - 'food all' -> all-time, category='Food'
      - 'september' -> month=9, year=current_year
      - 'september 2026' -> month=9, year=2026
      - '26 september 2026' -> exact date 2026-09-26
      - '2026-09-26' -> exact date 2026-09-26
      - 'today' -> today's date
      - 'yesterday' -> yesterday's date
      - 'september food' -> month=9, category='Food'
      - '26 september 2026 food' -> exact date + category='Food'

    Returns:
      {
        'date': date or None,
        'month': int or None,
        'year': int or None,
        'category_name': str or None,
        'category': Category instance or None,
        'is_all_time': bool,
        'label': human-readable summary string
      }
    """
    now = timezone.localdate()
    result = {
        'date': None,
        'month': None,
        'year': None,
        'category_name': None,
        'category': None,
        'is_all_time': False,
        'label': 'All expenses'
    }

    raw_text = (arg_text or '').strip()
    if not raw_text:
        if default_to_current_month:
            result['month'] = now.month
            result['year'] = now.year
            month_name = calendar.month_name[now.month]
            result['label'] = f"{month_name} {now.year}"
        else:
            result['is_all_time'] = True
            result['label'] = "All expenses"
        return result

    tokens = raw_text.split()

    # 1. Check for 'all' / 'all-time' keywords
    is_all_time = False
    filtered_tokens = []
    for t in tokens:
        if t.lower() in ('all', 'all-time', 'alltime', 'overall'):
            is_all_time = True
        else:
            filtered_tokens.append(t)

    result['is_all_time'] = is_all_time
    tokens = filtered_tokens
    active_text = ' '.join(tokens)

    # 2. Check relative keywords: today / yesterday
    if any(t.lower() == 'today' for t in tokens):
        result['date'] = now
        tokens = [t for t in tokens if t.lower() != 'today']
        active_text = ' '.join(tokens)
    elif any(t.lower() == 'yesterday' for t in tokens):
        result['date'] = now - timedelta(days=1)
        tokens = [t for t in tokens if t.lower() != 'yesterday']
        active_text = ' '.join(tokens)

    # 3. Check full date patterns (e.g. 26 september 2026, 26-09-2026, 2026-09-26, 26/09/2026)
    if not result['date'] and active_text:
        date_pattern = r'(\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b)'
        match = re.search(date_pattern, active_text)
        if match:
            date_str = match.group(0)
            try:
                parsed_dt = date_parser.parse(date_str, dayfirst=True).date()
                result['date'] = parsed_dt
                active_text = active_text.replace(date_str, ' ').strip()
                tokens = active_text.split()
            except Exception:
                pass

    if not result['date'] and active_text:
        # Match "26 september 2026" or "26 september"
        date_word_pattern = r'\b(\d{1,2})\s+([a-zA-Z]+)(?:\s+(\d{4}))?\b'
        match = re.search(date_word_pattern, active_text, re.IGNORECASE)
        if match:
            day = int(match.group(1))
            month_word = match.group(2).lower()
            year_str = match.group(3)
            if month_word in MONTH_NAMES and 1 <= day <= 31:
                month_val = MONTH_NAMES[month_word]
                year_val = int(year_str) if year_str else now.year
                try:
                    result['date'] = date(year_val, month_val, day)
                    active_text = active_text.replace(match.group(0), ' ').strip()
                    tokens = active_text.split()
                except ValueError:
                    pass

    # 4. If no full date was found, check if a month (or month + year) was specified
    if not result['date'] and not is_all_time:
        found_month = None
        found_year = None
        remaining_tokens = []

        for token in tokens:
            t_low = token.lower()
            if t_low in MONTH_NAMES and found_month is None:
                found_month = MONTH_NAMES[t_low]
            elif token.isdigit() and len(token) == 4 and found_year is None:
                found_year = int(token)
            else:
                remaining_tokens.append(token)

        if found_month is not None:
            result['month'] = found_month
            result['year'] = found_year if found_year else now.year
            tokens = remaining_tokens
        elif found_year is not None:
            result['year'] = found_year
            tokens = remaining_tokens

    # 5. Default to current month/year if no date, month, or 'all' was specified
    if not is_all_time and result['date'] is None and result['month'] is None:
        if default_to_current_month:
            result['month'] = now.month
            result['year'] = result['year'] or now.year

    # 6. Remaining tokens represent category (or item description)
    remaining_text = ' '.join(tokens).strip()
    if remaining_text:
        result['category_name'] = remaining_text.capitalize()
        if user and getattr(user, 'is_authenticated', False):
            cat = Category.objects.filter(user=user, name__iexact=remaining_text).first()
            if cat:
                result['category'] = cat
                result['category_name'] = cat.name

    # 7. Build human-readable label
    labels = []
    if result['date']:
        labels.append(result['date'].strftime('%d %B %Y'))
    elif result['month'] and result['year']:
        month_name = calendar.month_name[result['month']]
        labels.append(f"{month_name} {result['year']}")
    elif result['month']:
        month_name = calendar.month_name[result['month']]
        labels.append(f"{month_name}")
    elif result['year']:
        labels.append(f"Year {result['year']}")
    elif is_all_time:
        labels.append("All time")

    if result['category_name']:
        labels.append(f"Category: {result['category_name']}")

    if labels:
        result['label'] = ' • '.join(labels)
    else:
        result['label'] = 'All expenses'

    return result


def apply_expense_filters(queryset, filter_dict: dict):
    """
    Applies the dictionary from parse_filter_args to an Expense QuerySet.
    """
    qs = queryset
    if filter_dict.get('date'):
        qs = qs.filter(date=filter_dict['date'])
    elif not filter_dict.get('is_all_time'):
        if filter_dict.get('year'):
            qs = qs.filter(date__year=filter_dict['year'])
        if filter_dict.get('month'):
            qs = qs.filter(date__month=filter_dict['month'])

    if filter_dict.get('category'):
        qs = qs.filter(category=filter_dict['category'])
    elif filter_dict.get('category_name'):
        cat_name = filter_dict['category_name']
        qs = qs.filter(models.Q(category__name__iexact=cat_name) | models.Q(type__icontains=cat_name))

    return qs
