import re
from datetime import datetime, date, timedelta
from dateutil import parser as date_parser
from django.utils import timezone
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


def parse_filter_args(arg_text: str, user=None) -> dict:
    """
    Parses natural filter arguments across Telegram bot and web search.
    Examples:
      - '' -> All expenses
      - 'september' -> month=9, year=current_year
      - 'september 2026' -> month=9, year=2026
      - '26 september 2026' -> exact date 2026-09-26
      - '2026-09-26' -> exact date 2026-09-26
      - 'today' -> today's date
      - 'yesterday' -> yesterday's date
      - 'food' -> category='Food'
      - 'september food' -> month=9, category='Food'
      - '26 september 2026 food' -> exact date + category='Food'
      - 'food 26 september 2026' -> exact date + category='Food'

    Returns:
      {
        'date': date or None,
        'month': int or None,
        'year': int or None,
        'category_name': str or None,
        'category': Category instance or None,
        'label': human-readable summary string
      }
    """
    result = {
        'date': None,
        'month': None,
        'year': None,
        'category_name': None,
        'category': None,
        'label': 'All expenses'
    }

    if not arg_text or not arg_text.strip():
        return result

    tokens = arg_text.strip().split()
    now = timezone.now().date()
    lower_text = arg_text.strip().lower()

    # 1. Check relative keywords: today / yesterday
    if 'today' in tokens:
        result['date'] = now
        tokens = [t for t in tokens if t.lower() != 'today']
    elif 'yesterday' in tokens:
        result['date'] = now - timedelta(days=1)
        tokens = [t for t in tokens if t.lower() != 'yesterday']

    # 2. Check full date patterns (e.g. 26 september 2026, 26-09-2026, 2026-09-26, 26/09/2026)
    if not result['date']:
        # Match ISO format or DD-MM-YYYY or DD/MM/YYYY
        date_pattern = r'(\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b)'
        match = re.search(date_pattern, arg_text)
        if match:
            date_str = match.group(0)
            try:
                # dayfirst=True for DD-MM-YYYY
                parsed_dt = date_parser.parse(date_str, dayfirst=True).date()
                result['date'] = parsed_dt
                arg_text = arg_text.replace(date_str, ' ').strip()
                tokens = arg_text.split()
            except Exception:
                pass

    if not result['date']:
        # Match "26 september 2026" or "26 september"
        date_word_pattern = r'\b(\d{1,2})\s+([a-zA-Z]+)(?:\s+(\d{4}))?\b'
        match = re.search(date_word_pattern, arg_text, re.IGNORECASE)
        if match:
            day = int(match.group(1))
            month_word = match.group(2).lower()
            year_str = match.group(3)
            if month_word in MONTH_NAMES and 1 <= day <= 31:
                month_val = MONTH_NAMES[month_word]
                year_val = int(year_str) if year_str else now.year
                try:
                    result['date'] = date(year_val, month_val, day)
                    arg_text = arg_text.replace(match.group(0), ' ').strip()
                    tokens = arg_text.split()
                except ValueError:
                    pass

    # 3. If no full date was found, check if a month (or month + year) was specified
    if not result['date']:
        # Check if any token matches month
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

    # 4. Remaining tokens represent category (or item filter)
    remaining_text = ' '.join(tokens).strip()
    if remaining_text:
        # Check if user has a category matching this name (case-insensitive)
        result['category_name'] = remaining_text.capitalize()
        if user and user.is_authenticated:
            cat = Category.objects.filter(user=user, name__iexact=remaining_text).first()
            if cat:
                result['category'] = cat
                result['category_name'] = cat.name

    # Build human label
    labels = []
    if result['date']:
        labels.append(result['date'].strftime('%d %B %Y'))
    elif result['month']:
        month_name = [k for k, v in MONTH_NAMES.items() if v == result['month'] and len(k) > 3][0].capitalize()
        labels.append(f"{month_name} {result['year']}")

    if result['category_name']:
        labels.append(f"Category: {result['category_name']}")

    if labels:
        result['label'] = ' • '.join(labels)

    return result


def apply_expense_filters(queryset, filter_dict: dict):
    """
    Applies the dictionary from parse_filter_args to an Expense QuerySet.
    """
    qs = queryset
    if filter_dict.get('date'):
        qs = qs.filter(date=filter_dict['date'])
    else:
        if filter_dict.get('year'):
            qs = qs.filter(date__year=filter_dict['year'])
        if filter_dict.get('month'):
            qs = qs.filter(date__month=filter_dict['month'])

    if filter_dict.get('category'):
        qs = qs.filter(category=filter_dict['category'])
    elif filter_dict.get('category_name'):
        qs = qs.filter(category__name__iexact=filter_dict['category_name'])

    return qs
