from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from tracker.models import Category, Expense, Budget, TelegramLink


class Command(BaseCommand):
    help = 'Seeds sample data for demonstration'

    def handle(self, *args, **options):
        username = 'demo'
        user, created = User.objects.get_or_create(username=username, defaults={'email': 'demo@example.com'})
        if created:
            user.set_password('demo1234')
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created demo user '{username}' with password 'demo1234'."))
        else:
            self.stdout.write(f"User '{username}' already exists.")

        # Ensure TelegramLink has a code
        link, _ = TelegramLink.objects.get_or_create(user=user)
        if not link.link_code:
            link.generate_code()
            self.stdout.write(f"Generated Telegram link code: {link.link_code}")

        # Set budget for current month
        today = timezone.now().date()
        budget, _ = Budget.objects.get_or_create(
            user=user,
            month=today.month,
            year=today.year,
            defaults={'amount': Decimal('25000.00')}
        )
        self.stdout.write(f"Set budget for {today.strftime('%B %Y')}: Rs. {budget.amount}")

        # Create categories
        categories_data = ['Food', 'Travel', 'Shopping', 'Bills', 'Entertainment', 'Health']
        cat_objs = {}
        for cname in categories_data:
            cat, _ = Category.objects.get_or_create(user=user, name=cname)
            cat_objs[cname] = cat

        # Sample expenses
        expenses_sample = [
            ('Food', 'Gourmet Pizza & Drinks', Decimal('850.00'), today, 'web'),
            ('Travel', 'Uber to Central Mall', Decimal('220.00'), today, 'bot'),
            ('Food', 'Grocery Shopping (Supermarket)', Decimal('2450.00'), today - timedelta(days=2), 'web'),
            ('Shopping', 'Wireless Noise-Canceling Earbuds', Decimal('3999.00'), today - timedelta(days=4), 'web'),
            ('Bills', 'High-Speed Fiber Internet Bill', Decimal('999.00'), today - timedelta(days=5), 'bot'),
            ('Entertainment', 'Weekend IMAX Movie Tickets', Decimal('700.00'), today - timedelta(days=7), 'bot'),
            ('Travel', 'Fuel Station Refill', Decimal('1500.00'), today - timedelta(days=9), 'web'),
            ('Health', 'Pharmacy Vitamins & Supplements', Decimal('650.00'), today - timedelta(days=12), 'web'),
            ('Food', 'Sushi Dinner with Colleagues', Decimal('1850.00'), today - timedelta(days=15), 'bot'),
            ('Bills', 'Apartment Electricity Bill', Decimal('1420.00'), today - timedelta(days=18), 'web'),
            # Previous month sample
            ('Food', 'Monthly Grocery Staples', Decimal('4200.00'), today - timedelta(days=35), 'web'),
            ('Travel', 'Metro Transit Card Recharge', Decimal('800.00'), today - timedelta(days=38), 'bot'),
            ('Entertainment', 'Streaming Subscription (Annual)', Decimal('1499.00'), today - timedelta(days=42), 'web'),
        ]

        # Only insert if no expenses exist
        if Expense.objects.filter(user=user).count() == 0:
            for cname, etype, amt, edate, via in expenses_sample:
                Expense.objects.create(
                    user=user,
                    category=cat_objs[cname],
                    type=etype,
                    amount=amt,
                    date=edate,
                    created_via=via
                )
            self.stdout.write(self.style.SUCCESS(f"Inserted {len(expenses_sample)} demo expenses."))
        else:
            self.stdout.write("Expenses already present for demo user.")

        self.stdout.write(self.style.SUCCESS("Sample data seeding complete!"))
