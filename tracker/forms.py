from django import forms
from django.contrib.auth.models import User
from .models import Expense, Category, Budget


class ExpenseForm(forms.ModelForm):
    new_category = forms.CharField(
        required=False,
        max_length=100,
        label="Or Create New Category",
        widget=forms.TextInput(attrs={
            'class': 'form-control glass-input',
            'placeholder': 'e.g. Health, Gadgets, Gaming'
        })
    )

    class Meta:
        model = Expense
        fields = ['category', 'type', 'amount', 'date']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-select glass-input'}),
            'type': forms.TextInput(attrs={'class': 'form-control glass-input', 'placeholder': 'e.g. Pizza with friends, Auto fare'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control glass-input', 'placeholder': '0.00', 'step': '0.01'}),
            'date': forms.DateInput(attrs={'class': 'form-control glass-input', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['category'].queryset = Category.objects.filter(user=user)
            self.fields['category'].required = False  # can be satisfied by new_category


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['month', 'year', 'amount']
        widgets = {
            'month': forms.Select(
                choices=[(i, forms.DateField().default_error_messages.get(str(i), f"Month {i}")) for i in range(1, 13)],
                attrs={'class': 'form-select glass-input'}
            ),
            'year': forms.NumberInput(attrs={'class': 'form-control glass-input'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control glass-input', 'step': '0.01'}),
        }


class RegisterForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control glass-input', 'placeholder': 'Create a password'})
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control glass-input', 'placeholder': 'Confirm your password'})
    )

    class Meta:
        model = User
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control glass-input', 'placeholder': 'Choose username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control glass-input', 'placeholder': 'name@example.com'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('confirm_password')
        if p1 and p2 and p1 != p2:
            self.add_error('confirm_password', "Passwords do not match.")
        return cleaned_data
