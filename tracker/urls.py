from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('expenses/', views.expenses_list_view, name='expenses'),
    path('expenses/add/', views.expense_create_view, name='expense_add'),
    path('expenses/<int:pk>/edit/', views.expense_edit_view, name='expense_edit'),
    path('expenses/<int:pk>/delete/', views.expense_delete_view, name='expense_delete'),
    path('export/pdf/', views.export_pdf_view, name='export_pdf'),
    path('profile/', views.profile_view, name='profile'),
    path('telegram/', views.telegram_redirect_view, name='telegram_redirect'),
    path('budget/set/', views.set_budget_view, name='set_budget'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
