from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.db import IntegrityError
from tracker.models import Category, Expense, Budget, TelegramLink, TelegramSession
from tracker.services.filter_parser import parse_filter_args, apply_expense_filters
from tracker.services.budget_service import get_budget_status, check_budget_thresholds_after_expense
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

