"""Buy-order processing for the simulated trading system."""

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from market.models import Stock
from market.services import is_market_open

from .models import CashTransaction, Holding, Order, Portfolio


MAX_QUANTITY = 2_147_483_647


class BuyOrderError(Exception):
    """A rejected buy request with a user-facing explanation."""


@transaction.atomic
def place_buy_order(user, stock_id, quantity):
    """Execute an open-market buy or reserve cash for a pending buy.

    The Portfolio is locked first, matching the cash-operation services.
    All changes roll back together if any part of the operation fails.
    """
    if not user.is_authenticated:
        raise BuyOrderError("Log in to place a buy order.")

    # Forms will convert valid input to int before calling this service.
    # Reject bool explicitly because Python treats it as an integer.
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
        or quantity > MAX_QUANTITY
    ):
        raise BuyOrderError("Enter a valid positive whole-share quantity.")

    try:
        portfolio = Portfolio.objects.select_for_update().get(user=user)
    except Portfolio.DoesNotExist:
        raise BuyOrderError("This account has no trading portfolio.") from None

    try:
        stock = Stock.objects.select_for_update().get(pk=stock_id)
    except Stock.DoesNotExist:
        raise BuyOrderError("This stock is no longer available.") from None

    if not stock.is_active:
        raise BuyOrderError("This stock is not available for trading.")

    # Read the current stored price while the Stock row is locked.
    price = stock.current_price
    cost = price * quantity
    available = portfolio.cash_balance - portfolio.reserved_cash

    if cost > available:
        raise BuyOrderError(
            f"Insufficient available cash. "
            f"This order costs ${cost:,.2f}; "
            f"you have ${available:,.2f} available."
        )

    submitted_at = timezone.now()
    market_open = is_market_open(submitted_at)

    # The conditional update checks funds again in the database.
    # F expressions avoid overwriting balances using stale values.
    eligible_portfolio = Portfolio.objects.filter(
        pk=portfolio.pk,
        cash_balance__gte=F("reserved_cash") + cost,
    )

    if market_open:
        updated = eligible_portfolio.update(
            cash_balance=F("cash_balance") - cost,
            updated_at=submitted_at,
        )
    else:
        updated = eligible_portfolio.update(
            reserved_cash=F("reserved_cash") + cost,
            updated_at=submitted_at,
        )

    if updated != 1:
        raise BuyOrderError(
            "Available cash changed. Please review your balance and try again."
        )

    order = Order.objects.create(
        portfolio=portfolio,
        stock=stock,
        side=Order.Side.BUY,
        status=(
            Order.Status.EXECUTED
            if market_open
            else Order.Status.PENDING
        ),
        quantity=quantity,
        submission_price=price,
        reserved_cash=Decimal("0.00") if market_open else cost,
        execution_price=price if market_open else None,
        executed_at=submitted_at if market_open else None,
    )

    if market_open:
        holding, _ = Holding.objects.select_for_update().get_or_create(
            portfolio=portfolio,
            stock=stock,
            defaults={"quantity": 0},
        )

        if holding.quantity + quantity > MAX_QUANTITY:
            raise BuyOrderError(
                "This purchase would exceed the supported holding quantity."
            )

        holding.quantity += quantity
        holding.save(update_fields=["quantity", "updated_at"])

        portfolio.refresh_from_db(
            fields=["cash_balance", "reserved_cash"]
        )

        CashTransaction.objects.create(
            portfolio=portfolio,
            order=order,
            transaction_type=CashTransaction.TransactionType.PURCHASE,
            amount=-cost,
            balance_after=portfolio.cash_balance,
            description=f"Bought {quantity} shares of {stock.symbol}",
        )

    return order