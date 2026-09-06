import secrets
import string
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.functions import Lower


class Category(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'),
                'user',
                name='unique_category_per_user_case_insensitive'
            )
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Normalize category name: stripped and Title-cased for presentation
        if self.name:
            self.name = self.name.strip().capitalize()
        super().save(*args, **kwargs)


class Expense(models.Model):
    VIA_CHOICES = (
        ('web', 'Web'),
        ('bot', 'Telegram Bot'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expenses')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='expenses')
    type = models.CharField(max_length=200, help_text="Item description/type, e.g., pizza, auto")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    created_via = models.CharField(max_length=10, choices=VIA_CHOICES, default='web')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.type} - {self.amount} ({self.category.name})"


class Budget(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budgets')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    month = models.PositiveSmallIntegerField()  # 1 to 12
    year = models.PositiveSmallIntegerField()
    notified_80 = models.BooleanField(default=False)
    notified_100 = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'year', 'month')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.user.username}'s Budget ({self.month}/{self.year}): {self.amount}"


class TelegramSession(models.Model):
    chat_id = models.BigIntegerField(primary_key=True)
    last_shown_list = models.JSONField(default=list, blank=True)
    pending_action = models.CharField(max_length=64, blank=True, null=True)
    pending_data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session for chat {self.chat_id} (action: {self.pending_action})"


class TelegramLink(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='telegram_link')
    chat_id = models.BigIntegerField(unique=True, null=True, blank=True)
    link_code = models.CharField(max_length=16, unique=True, null=True, blank=True)
    code_created_at = models.DateTimeField(null=True, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        if self.chat_id:
            return f"{self.user.username} -> Telegram Chat {self.chat_id}"
        return f"{self.user.username} (Unlinked, code: {self.link_code})"

    @property
    def is_linked(self):
        return self.chat_id is not None

    def generate_code(self):
        chars = string.ascii_uppercase + string.digits
        # 6-character memorable code
        new_code = ''.join(secrets.choice(chars) for _ in range(6))
        self.link_code = new_code
        self.code_created_at = timezone.now()
        self.save(update_fields=['link_code', 'code_created_at'])
        return new_code


from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def handle_user_post_save(sender, instance, created, **kwargs):
    if created:
        TelegramLink.objects.get_or_create(user=instance)
        # Seed friendly starter categories
        default_cats = ['Food', 'Travel', 'Shopping', 'Bills', 'Entertainment', 'Health']
        for cat_name in default_cats:
            Category.objects.get_or_create(user=instance, name=cat_name)

