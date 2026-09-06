from django.contrib import admin
from .models import Category, Expense, Budget, TelegramSession, TelegramLink


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'user', 'created_at')
    search_fields = ('name', 'user__username')
    list_filter = ('user',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'type', 'category', 'amount', 'date', 'created_via', 'created_at')
    list_filter = ('category', 'created_via', 'date', 'user')
    search_fields = ('type', 'user__username', 'category__name')
    date_hierarchy = 'date'


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'month', 'year', 'amount', 'notified_80', 'notified_100', 'updated_at')
    list_filter = ('year', 'month', 'user')


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'chat_id', 'link_code', 'code_created_at', 'linked_at')
    search_fields = ('user__username', 'chat_id', 'link_code')


@admin.register(TelegramSession)
class TelegramSessionAdmin(admin.ModelAdmin):
    list_display = ('chat_id', 'pending_action', 'updated_at')
