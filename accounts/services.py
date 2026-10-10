"""Atomic account services: registration initialization and simulated cash.

Every balance change and its CashTransaction ledger row are written in one
database transaction. Balance changes use a single conditional UPDATE with
F() expressions, so the database (not a stale Python object) decides whether
the change is allowed. A concurrent request can therefore never silently
overwrite a balance written by another request.

The Portfolio row is also locked with select_for_update() before it changes.
On PostgreSQL that serializes cash operations with any other code that locks
the same row (for example, buy-order reservation). SQLite ignores row locks
but serializes all writers, so the conditional UPDATE remains correct there.
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F

from trading.models import CashTransaction, Portfolio

STARTING_CASH = Decimal("25000.00")

# Placeholder until the team confirms the cap. Override with
# CASH_DEPOSIT_LIMIT in settings.py once agreed with Nathan.
DEFAULT_DEPOSIT_LIMIT = Decimal("100000.00")

# Largest value Portfolio.cash_balance can store (max_digits=12, places=2).
MAX_CASH_BALANCE = Decimal("9999999999.99")

CENT = Decimal("0.01")


class CashOperationError(Exception):
    """Base class for rejected cash operations. The message is user-facing."""


class InvalidAmountError(CashOperationError):
    pass


class DepositLimitError(CashOperationError):
    pass


class InsufficientFundsError(CashOperationError):
    pass


def get_deposit_limit():
    return Decimal(str(getattr(settings, "CASH_DEPOSIT_LIMIT", DEFAULT_DEPOSIT_LIMIT)))


def available_cash(portfolio):
    """Cash a customer may withdraw or commit to a new buy order."""
    return portfolio.cash_balance - portfolio.reserved_cash


def _validate_amount(amount):
    if not isinstance(amount, Decimal):
        raise InvalidAmountError("Enter a valid dollar amount.")
    if not amount.is_finite():
        raise InvalidAmountError("Enter a valid dollar amount.")
    if amount <= 0:
        raise InvalidAmountError("Amount must be greater than $0.00.")
    if amount != amount.quantize(CENT):
        raise InvalidAmountError("Amount cannot have more than 2 decimal places.")


@transaction.atomic
def create_customer_account(registration_form):
    """Create the User, Portfolio, and opening ledger entry together.

    If any step fails, the whole registration rolls back and no partial
    User, Portfolio, or CashTransaction remains.
    """
    user = registration_form.save()
    portfolio = Portfolio.objects.create(
        user=user,
        cash_balance=STARTING_CASH,
        reserved_cash=Decimal("0.00"),
    )
    CashTransaction.objects.create(
        portfolio=portfolio,
        transaction_type=CashTransaction.TransactionType.INITIAL_BALANCE,
        amount=STARTING_CASH,
        balance_after=STARTING_CASH,
        description="Opening simulated cash balance",
    )
    return user


@transaction.atomic
def deposit_cash(user, amount):
    """Add simulated cash to the user's own portfolio and record a DEPOSIT."""
    _validate_amount(amount)
    limit = get_deposit_limit()
    if amount > limit:
        raise DepositLimitError(f"Deposits cannot exceed ${limit:,.2f} at a time.")

    portfolio = Portfolio.objects.select_for_update().get(user=user)
    updated = Portfolio.objects.filter(
        pk=portfolio.pk,
        cash_balance__lte=MAX_CASH_BALANCE - amount,
    ).update(cash_balance=F("cash_balance") + amount)
    if updated != 1:
        raise DepositLimitError("This deposit would exceed the maximum account balance.")

    portfolio.refresh_from_db(fields=["cash_balance", "reserved_cash", "updated_at"])
    return CashTransaction.objects.create(
        portfolio=portfolio,
        transaction_type=CashTransaction.TransactionType.DEPOSIT,
        amount=amount,
        balance_after=portfolio.cash_balance,
        description="Simulated cash deposit",
    )


@transaction.atomic
def withdraw_cash(user, amount):
    """Remove available simulated cash and record a negative WITHDRAWAL.

    Available cash is cash_balance minus reserved_cash, evaluated by the
    database at the moment of the update.
    """
    _validate_amount(amount)

    portfolio = Portfolio.objects.select_for_update().get(user=user)
    updated = Portfolio.objects.filter(
        pk=portfolio.pk,
        cash_balance__gte=F("reserved_cash") + amount,
    ).update(cash_balance=F("cash_balance") - amount)
    if updated != 1:
        portfolio.refresh_from_db(fields=["cash_balance", "reserved_cash"])
        raise InsufficientFundsError(
            f"Insufficient available cash. You can withdraw up to "
            f"${available_cash(portfolio):,.2f}."
        )

    portfolio.refresh_from_db(fields=["cash_balance", "reserved_cash", "updated_at"])
    return CashTransaction.objects.create(
        portfolio=portfolio,
        transaction_type=CashTransaction.TransactionType.WITHDRAWAL,
        amount=-amount,
        balance_after=portfolio.cash_balance,
        description="Simulated cash withdrawal",
    )
