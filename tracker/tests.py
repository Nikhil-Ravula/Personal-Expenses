from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.db import IntegrityError
from tracker.models import Category, Expense, Budget, TelegramLink, TelegramSession
from tracker.services.filter_parser import parse_filter_args, apply_expense_filters
from tracker.services.budget_service import get_budget_status, get_all_time_budget_status, check_budget_thresholds_after_expense
from tracker.services.pdf_generator import generate_expense_pdf


class ExpenseTrackerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='nikhil', password='testpassword123')

    def test_category_case_insensitivity_and_defaults(self):
        # Default starter categories should be created by signal
        food_cat = Category.objects.filter(user=self.user, name='Food').first()
        self.assertIsNotNone(food_cat)

        # Attempting to create duplicate category with different casing should raise IntegrityError
        with self.assertRaises(IntegrityError):
            Category.objects.create(user=self.user, name='food')

    def test_telegram_link_signal(self):
        link = TelegramLink.objects.filter(user=self.user).first()
        self.assertIsNotNone(link)
        self.assertFalse(link.is_linked)

        code = link.generate_code()
        self.assertEqual(len(code), 6)
        self.assertEqual(link.link_code, code)

    def test_filter_parser(self):
        from django.utils import timezone
        now = timezone.localdate()

        # 1. Month filter
        res1 = parse_filter_args('september', user=self.user)
        self.assertEqual(res1['month'], 9)
        self.assertIsNone(res1['date'])

        # 2. Exact date filter
        res2 = parse_filter_args('26 september 2026', user=self.user)
        self.assertEqual(res2['date'], date(2026, 9, 26))

        # 3. Category + month
        res3 = parse_filter_args('september food', user=self.user)
        self.assertEqual(res3['month'], 9)
        self.assertEqual(res3['category_name'], 'Food')

        # 4. Exact date + category
        res4 = parse_filter_args('26 september 2026 food', user=self.user)
        self.assertEqual(res4['date'], date(2026, 9, 26))
        self.assertEqual(res4['category_name'], 'Food')

        # 5. Default to current month when no date/month is given
        res_default = parse_filter_args('', user=self.user)
        self.assertEqual(res_default['month'], now.month)
        self.assertEqual(res_default['year'], now.year)

        # 6. /show food defaults to current month
        res_food = parse_filter_args('food', user=self.user)
        self.assertEqual(res_food['month'], now.month)
        self.assertEqual(res_food['category_name'], 'Food')

        # 7. /show food oct specifies month
        res_food_oct = parse_filter_args('food oct', user=self.user)
        self.assertEqual(res_food_oct['month'], 10)
        self.assertEqual(res_food_oct['category_name'], 'Food')

        # 8. /show food all is all-time
        res_food_all = parse_filter_args('food all', user=self.user)
        self.assertTrue(res_food_all['is_all_time'])
        self.assertIsNone(res_food_all['month'])
        self.assertEqual(res_food_all['category_name'], 'Food')

        # 9. /show all is all-time
        res_all = parse_filter_args('all', user=self.user)
        self.assertTrue(res_all['is_all_time'])
        self.assertIsNone(res_all['month'])

        # 10. Web search explicitly opting out of current month default
        res_web = parse_filter_args('food', user=self.user, default_to_current_month=False)
        self.assertIsNone(res_web['month'])
        self.assertEqual(res_web['category_name'], 'Food')

    def test_all_time_budget_status(self):
        food_cat = Category.objects.filter(user=self.user, name='Food').first()
        Expense.objects.create(user=self.user, category=food_cat, type='Item 1', amount=Decimal('200.00'), date=date(2026, 9, 1))
        Expense.objects.create(user=self.user, category=food_cat, type='Item 2', amount=Decimal('300.00'), date=date(2026, 10, 1))
        Budget.objects.create(user=self.user, month=9, year=2026, amount=Decimal('500.00'))
        Budget.objects.create(user=self.user, month=10, year=2026, amount=Decimal('1000.00'))

        status = get_all_time_budget_status(self.user)
        self.assertEqual(status['total_spent'], Decimal('500.00'))
        self.assertEqual(status['total_count'], 2)
        self.assertEqual(status['total_budget'], Decimal('1500.00'))
        self.assertEqual(status['remaining'], Decimal('1000.00'))
        self.assertEqual(status['first_date'], date(2026, 9, 1))
        self.assertEqual(status['last_date'], date(2026, 10, 1))

    def test_previous_remaining_budget_rollover(self):
        # Create budget for September 2026: 5000
        Budget.objects.create(user=self.user, month=9, year=2026, amount=Decimal('5000.00'))
        food_cat = Category.objects.filter(user=self.user, name='Food').first()
        Expense.objects.create(user=self.user, category=food_cat, type='Sep Dinners', amount=Decimal('2000.00'), date=date(2026, 9, 10))

        # Check status for September 2026
        sep_status = get_budget_status(self.user, month=9, year=2026)
        self.assertTrue(sep_status['has_budget'])
        self.assertEqual(sep_status['remaining'], Decimal('3000.00'))

        # Create budget for October 2026: 4000
        oct_budget, _ = Budget.objects.get_or_create(user=self.user, month=10, year=2026, defaults={'amount': Decimal('4000.00')})

        # Add remaining budget (3000) from September to October
        oct_budget.amount += sep_status['remaining']
        oct_budget.save()

        oct_status = get_budget_status(self.user, month=10, year=2026)
        self.assertEqual(oct_status['budget_amount'], Decimal('7000.00'))

    def test_budget_threshold_alerts(self):
        # Set a budget of 1000 for September 2026
        budget = Budget.objects.create(
            user=self.user,
            amount=Decimal('1000.00'),
            month=9,
            year=2026
        )
        food_cat = Category.objects.filter(user=self.user, name='Food').first()

        # Add expense of 500 (50%) -> No alert
        Expense.objects.create(
            user=self.user,
            category=food_cat,
            type='Groceries',
            amount=Decimal('500.00'),
            date=date(2026, 9, 5)
        )
        alerts = check_budget_thresholds_after_expense(self.user, date(2026, 9, 5))
        self.assertEqual(len(alerts), 0)

        # Add expense of 350 (total 850, 85%) -> 80% alert should trigger
        Expense.objects.create(
            user=self.user,
            category=food_cat,
            type='Dinner',
            amount=Decimal('350.00'),
            date=date(2026, 9, 10)
        )
        alerts = check_budget_thresholds_after_expense(self.user, date(2026, 9, 10))
        self.assertEqual(len(alerts), 1)
        self.assertIn("80%", alerts[0])

        # Second check should not duplicate 80% alert
        alerts_repeat = check_budget_thresholds_after_expense(self.user, date(2026, 9, 10))
        self.assertEqual(len(alerts_repeat), 0)

        # Add expense of 200 (total 1050, 105%) -> 100% alert should trigger
        Expense.objects.create(
            user=self.user,
            category=food_cat,
            type='Party',
            amount=Decimal('200.00'),
            date=date(2026, 9, 15)
        )
        alerts_100 = check_budget_thresholds_after_expense(self.user, date(2026, 9, 15))
        self.assertEqual(len(alerts_100), 1)
        self.assertIn("Exceeded", alerts_100[0])

    def test_pdf_generation(self):
        food_cat = Category.objects.filter(user=self.user, name='Food').first()
        Expense.objects.create(
            user=self.user,
            category=food_cat,
            type='Pizza',
            amount=Decimal('150.00'),
            date=date(2026, 9, 1)
        )
        qs = Expense.objects.filter(user=self.user)
        pdf_bytes, filename = generate_expense_pdf(qs, user=self.user, filter_label="September 2026")
        self.assertTrue(len(pdf_bytes) > 500)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertTrue(filename.endswith('.pdf'))


class WebViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='password123')
        self.client.login(username='tester', password='password123')
        self.cat = Category.objects.filter(user=self.user, name='Food').first()

    def test_dashboard_renders(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome, tester')
        self.assertContains(response, 'Total Spent')

    def test_expenses_list_renders_and_filters(self):
        Expense.objects.create(user=self.user, category=self.cat, type='Burger', amount=Decimal('120.00'), date=date.today())
        response = self.client.get('/expenses/?q=food')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Burger')
        self.assertContains(response, '120.00')

    def test_expense_create_flow(self):
        response = self.client.post('/expenses/add/', {
            'category': self.cat.id,
            'type': 'Cinema Tickets',
            'amount': '300.00',
            'date': str(date.today()),
            'new_category': ''
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Expense.objects.filter(user=self.user, type='Cinema Tickets').exists())

    def test_export_pdf_view(self):
        Expense.objects.create(user=self.user, category=self.cat, type='Coffee', amount=Decimal('60.00'), date=date.today())
        response = self.client.get('/export/pdf/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_profile_link_code_generation(self):
        response = self.client.post('/profile/', {'generate_code': '1'})
        self.assertEqual(response.status_code, 302)
        link = TelegramLink.objects.get(user=self.user)
        self.assertIsNotNone(link.link_code)
        self.assertEqual(len(link.link_code), 6)

    def test_telegram_redirect_view(self):
        response = self.client.get('/telegram/')
        self.assertEqual(response.status_code, 302)
        link = TelegramLink.objects.get(user=self.user)
        self.assertIsNotNone(link.link_code)
        self.assertIn('https://t.me/', response['Location'])
        self.assertIn(link.link_code, response['Location'])


    def test_categories_view_renders_and_identifies_empty(self):
        # self.cat is 'Food'. Create an expense under it.
        Expense.objects.create(user=self.user, category=self.cat, type='Snacks', amount=Decimal('50.00'), date=date.today())
        # 'Shopping' is already a starter category with 0 expenses
        empty_cat = Category.objects.filter(user=self.user, name='Shopping').first()
        self.assertIsNotNone(empty_cat)

        # 1. View all categories
        res_all = self.client.get('/categories/')
        self.assertEqual(res_all.status_code, 200)
        self.assertContains(res_all, 'Food')
        self.assertContains(res_all, 'Shopping')

        # 2. View empty only
        res_empty = self.client.get('/categories/?filter=empty')
        self.assertEqual(res_empty.status_code, 200)
        self.assertContains(res_empty, 'Shopping')
        self.assertNotIn('Food', [c.name for c in res_empty.context['categories']])

    def test_category_delete_flow(self):
        empty_cat = Category.objects.create(user=self.user, name='UniqueCustomEmpty')
        active_cat = Category.objects.filter(user=self.user, name='Bills').first()
        Expense.objects.create(user=self.user, category=active_cat, type='Electricity', amount=Decimal('100.00'), date=date.today())

        # 1. Delete empty category -> Should succeed
        del_empty_res = self.client.post(f'/categories/{empty_cat.id}/delete/')
        self.assertEqual(del_empty_res.status_code, 302)
        self.assertFalse(Category.objects.filter(id=empty_cat.id).exists())

        # 2. Attempt to delete active category with expenses -> Should be blocked
        del_active_res = self.client.post(f'/categories/{active_cat.id}/delete/')
        self.assertEqual(del_active_res.status_code, 302)
        self.assertTrue(Category.objects.filter(id=active_cat.id).exists())


class TelegramBotCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='botuser', password='password123')
        self.food = Category.objects.filter(user=self.user, name='Food').first()
        Expense.objects.create(user=self.user, category=self.food, type='Lunch', amount=Decimal('80.00'), date=date.today())
        self.empty = Category.objects.create(user=self.user, name='daily_items')

    async def test_bot_category_helpers(self):
        from tracker.bot.handlers import get_user_categories_data, delete_user_category_by_id_or_name

        active, empty = await get_user_categories_data(self.user)
        active_names = [c['name'] for c in active]
        empty_names = [c['name'] for c in empty]

        self.assertIn('Food', active_names)
        self.assertIn('Daily_items', empty_names)

        # Attempt to delete active category -> should fail
        success_active, _, msg_active = await delete_user_category_by_id_or_name(self.user, 'Food')
        self.assertFalse(success_active)
        self.assertIn('Cannot delete', msg_active)

        # Delete empty category -> should succeed
        success_empty, name_empty, _ = await delete_user_category_by_id_or_name(self.user, 'daily_items')
        self.assertTrue(success_empty)
        self.assertEqual(name_empty, 'Daily_items')


class TelegramBotHtmlFormatTests(TestCase):
    def test_escape_html_helper(self):
        from tracker.bot.handlers import escape_html, escape_md, strip_html
        # In HTML mode, underscores remain natural and clean without breaking parser
        self.assertEqual(escape_html("daily_items"), "daily_items")
        self.assertEqual(escape_html("dharani_gita"), "dharani_gita")
        # HTML special chars are safely escaped
        self.assertEqual(escape_html("<script>alert('test')</script>"), "&lt;script&gt;alert('test')&lt;/script&gt;")
        self.assertEqual(escape_html("Tom & Jerry"), "Tom &amp; Jerry")
        self.assertEqual(escape_html(None), "")
        # Backward-compatibility alias
        self.assertEqual(escape_md("<test>"), "&lt;test&gt;")

    def test_strip_html_helper(self):
        from tracker.bot.handlers import strip_html
        self.assertEqual(strip_html("<b>Bold</b> and <code>code</code>"), "Bold and code")
        self.assertEqual(strip_html("No tags"), "No tags")
        self.assertEqual(strip_html(None), "")


class TelegramBotPaginationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pagination_user', password='password123')
        self.cat = Category.objects.filter(user=self.user, name='Food').first()
        for i in range(1, 32):
            Expense.objects.create(
                user=self.user,
                category=self.cat,
                type=f"Item {i}",
                amount=Decimal('10.00'),
                date=date.today()
            )

    async def test_pagination_pages(self):
        from tracker.bot.handlers import query_expenses_page_db, build_show_page_content

        # Page 1 (25 items)
        p1_exp, total, count, cur_p, total_p, label = await query_expenses_page_db(
            self.user, '', page=1, page_size=25
        )
        self.assertEqual(len(p1_exp), 25)
        self.assertEqual(count, 31)
        self.assertEqual(cur_p, 1)
        self.assertEqual(total_p, 2)
        self.assertEqual(total, Decimal('310.00'))

        text1, kb1 = build_show_page_content(p1_exp, total, count, cur_p, total_p, label, page_size=25)
        self.assertIn("Page 1 of 2", text1)
        self.assertIsNotNone(kb1)
        self.assertIn("showpage_2", str(kb1))

        # Page 2 (6 remaining items)
        p2_exp, total, count, cur_p, total_p, label = await query_expenses_page_db(
            self.user, '', page=2, page_size=25
        )
        self.assertEqual(len(p2_exp), 6)
        self.assertEqual(cur_p, 2)
        self.assertEqual(total_p, 2)

        text2, kb2 = build_show_page_content(p2_exp, total, count, cur_p, total_p, label, page_size=25)
        self.assertIn("Page 2 of 2", text2)
        self.assertIn("26.", text2)
        self.assertIn("31.", text2)
        self.assertIn("showpage_1", str(kb2))

    async def test_telegram_webhook_get_and_post(self):
        import json
        from django.test import AsyncClient
        client = AsyncClient()

        # GET request returns webhook status info
        resp_get = await client.get('/telegram/webhook/')
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn(b"Telegram Webhook Endpoint", resp_get.content)

        # POST request with mock payload returns 200 OK
        resp_post = await client.post(
            '/telegram/webhook/',
            data=json.dumps({"update_id": 9999}),
            content_type='application/json'
        )
        self.assertEqual(resp_post.status_code, 200)
        self.assertEqual(resp_post.content, b"OK")


