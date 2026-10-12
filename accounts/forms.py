from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .services import available_cash, get_deposit_limit

User = get_user_model()


class CustomerRegistrationForm(UserCreationForm):
    """Public sign-up form: name, unique username, unique email, password."""

    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField(max_length=254, label="Email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "last_name", "username", "email")

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()
        if not value:
            raise forms.ValidationError("Enter your first name.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()
        if not value:
            raise forms.ValidationError("Enter your last name.")
        return value

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


AMOUNT_ERRORS = {
    "required": "Enter an amount.",
    "invalid": "Enter a valid dollar amount, such as 250.00.",
    "min_value": "Amount must be greater than $0.00.",
    "max_decimal_places": "Amount cannot have more than 2 decimal places.",
    "max_digits": "Amount is too large.",
}


class _CashAmountForm(forms.Form):
    amount = forms.DecimalField(
        label="Amount (USD)",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        error_messages=AMOUNT_ERRORS,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
    )


class DepositForm(_CashAmountForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deposit_limit = get_deposit_limit()
        self.fields["amount"].widget.attrs["max"] = str(self.deposit_limit)
        self.fields["amount"].help_text = (
            f"Maximum ${self.deposit_limit:,.2f} per deposit."
        )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount > self.deposit_limit:
            raise forms.ValidationError(
                f"Deposits cannot exceed ${self.deposit_limit:,.2f} at a time."
            )
        return amount


class WithdrawalForm(_CashAmountForm):
    """The service re-checks availability atomically; this gives early feedback."""

    def __init__(self, *args, portfolio, **kwargs):
        super().__init__(*args, **kwargs)
        self.portfolio = portfolio
        self.fields["amount"].help_text = (
            f"Available to withdraw: ${available_cash(portfolio):,.2f}."
        )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        available = available_cash(self.portfolio)
        if amount > available:
            raise forms.ValidationError(
                f"Insufficient available cash. You can withdraw up to ${available:,.2f}."
            )
        return amount
