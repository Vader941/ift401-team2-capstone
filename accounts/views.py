from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from trading.models import Portfolio

from .forms import CustomerRegistrationForm, DepositForm, WithdrawalForm
from .services import (
    CashOperationError,
    available_cash,
    create_customer_account,
    deposit_cash,
    withdraw_cash,
)

RECENT_TRANSACTION_COUNT = 10


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("trading:dashboard")

    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            user = create_customer_account(form)
            login(request, user)
            messages.success(
                request,
                "Welcome! Your account is ready with $25,000.00 in simulated cash.",
            )
            return redirect("trading:dashboard")
    else:
        form = CustomerRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def _get_own_portfolio(request):
    """Cash routes never accept a portfolio id; they only use request.user."""
    try:
        return Portfolio.objects.get(user=request.user)
    except Portfolio.DoesNotExist:
        return None


def _cash_context(portfolio, form, operation):
    return {
        "form": form,
        "operation": operation,
        "portfolio": portfolio,
        "cash_balance": portfolio.cash_balance,
        "reserved_cash": portfolio.reserved_cash,
        "available_cash": available_cash(portfolio),
        "recent_transactions": portfolio.cash_transactions.all()[:RECENT_TRANSACTION_COUNT],
    }


def _no_portfolio_response(request):
    messages.error(
        request,
        "This login has no trading portfolio. Register a customer account to use cash features.",
    )
    return redirect("trading:dashboard")


@login_required
@require_http_methods(["GET", "POST"])
def deposit(request):
    portfolio = _get_own_portfolio(request)
    if portfolio is None:
        return _no_portfolio_response(request)

    if request.method == "POST":
        form = DepositForm(request.POST)
        if form.is_valid():
            try:
                entry = deposit_cash(request.user, form.cleaned_data["amount"])
            except CashOperationError as exc:
                form.add_error("amount", str(exc))
            else:
                messages.success(
                    request,
                    f"Deposited ${entry.amount:,.2f}. New cash balance: "
                    f"${entry.balance_after:,.2f}.",
                )
                return redirect("accounts:deposit")
    else:
        form = DepositForm()

    portfolio.refresh_from_db()
    return render(
        request, "accounts/cash_operation.html", _cash_context(portfolio, form, "deposit")
    )


@login_required
@require_http_methods(["GET", "POST"])
def withdraw(request):
    portfolio = _get_own_portfolio(request)
    if portfolio is None:
        return _no_portfolio_response(request)

    if request.method == "POST":
        form = WithdrawalForm(request.POST, portfolio=portfolio)
        if form.is_valid():
            try:
                entry = withdraw_cash(request.user, form.cleaned_data["amount"])
            except CashOperationError as exc:
                form.add_error("amount", str(exc))
            else:
                messages.success(
                    request,
                    f"Withdrew ${-entry.amount:,.2f}. New cash balance: "
                    f"${entry.balance_after:,.2f}.",
                )
                return redirect("accounts:withdraw")
    else:
        form = WithdrawalForm(portfolio=portfolio)

    portfolio.refresh_from_db()
    return render(
        request, "accounts/cash_operation.html", _cash_context(portfolio, form, "withdraw")
    )
