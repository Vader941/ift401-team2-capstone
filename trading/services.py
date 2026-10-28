"""Buy-order processing for the simulated trading system."""

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.services import available_cash
from market.models import Stock
from market.services import is_market_open

from .models import CashTransaction, Holding, Order, Portfolio


MAX_QUANTITY = 2_147_483_647


class BuyOrderError(Exception):
    """A rejected buy request with a user-facing explanation."""

class SellOrderError(Exception):
    """A rejected sell request with a user-facing explanation."""

class CancellationError(Exception):
    """A rejected cancellation with a user-facing explanation."""

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

    # Use the latest stored market price while the Stock row is locked.
    price = stock.current_price
    cost = price * quantity
    available = available_cash(portfolio)

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

@transaction.atomic
def place_sell_order(user, stock_id, quantity):
    """Execute a sale or reserve shares while the market is closed."""
    if not user.is_authenticated:
        raise SellOrderError("Log in to place a sell order.")

    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
        or quantity > MAX_QUANTITY
    ):
        raise SellOrderError(
            "Enter a valid positive whole-share quantity."
        )

    try:
        portfolio = Portfolio.objects.select_for_update().get(user=user)
    except Portfolio.DoesNotExist:
        raise SellOrderError(
            "This account has no trading portfolio."
        ) from None

    try:
        stock = Stock.objects.select_for_update().get(pk=stock_id)
    except Stock.DoesNotExist:
        raise SellOrderError(
            "This stock is no longer available."
        ) from None

    if not stock.is_active:
        raise SellOrderError("This stock is not available for trading.")

    holding = Holding.objects.select_for_update().filter(
        portfolio=portfolio,
        stock=stock,
    ).first()

    if (
        holding is None
        or quantity > holding.quantity - holding.reserved_quantity
    ):
        raise SellOrderError("Insufficient available shares.")

    submitted_at = timezone.now()
    market_open = is_market_open(submitted_at)
    price = stock.current_price
    proceeds = price * quantity

    if (
        market_open
        and portfolio.cash_balance + proceeds
        > Decimal("9999999999.99")
    ):
        raise SellOrderError(
            "This sale would exceed the maximum account balance."
        )

    order = Order.objects.create(
        portfolio=portfolio,
        stock=stock,
        side=Order.Side.SELL,
        status=(
            Order.Status.EXECUTED
            if market_open
            else Order.Status.PENDING
        ),
        quantity=quantity,
        submission_price=price,
        reserved_shares=0 if market_open else quantity,
        execution_price=price if market_open else None,
        executed_at=submitted_at if market_open else None,
    )

    if market_open:
        holding.quantity -= quantity
        portfolio.cash_balance += proceeds
        portfolio.save(
            update_fields=["cash_balance", "updated_at"]
        )

        CashTransaction.objects.create(
            portfolio=portfolio,
            order=order,
            transaction_type=CashTransaction.TransactionType.SALE,
            amount=proceeds,
            balance_after=portfolio.cash_balance,
            description=f"Sold {quantity} shares of {stock.symbol}",
        )
    else:
        holding.reserved_quantity += quantity

    holding.save(
        update_fields=[
            "quantity",
            "reserved_quantity",
            "updated_at",
        ]
    )

    return order

@transaction.atomic
def cancel_pending_order(
    user,
    order_id,
    *,
    reason="Cancelled by customer.",
):
    """Cancel the customer's own pending order and release its reservation."""
    if not user.is_authenticated:
        raise CancellationError("Log in to cancel an order.")

    try:
        portfolio = Portfolio.objects.select_for_update().get(
            user=user
        )
    except Portfolio.DoesNotExist:
        raise CancellationError(
            "This account has no trading portfolio."
        ) from None

    try:
        order = Order.objects.select_for_update().get(
            pk=order_id,
            portfolio=portfolio,
        )
    except Order.DoesNotExist:
        raise CancellationError(
            "This order is unavailable."
        ) from None

    if order.status != Order.Status.PENDING:
        raise CancellationError(
            "Only pending orders can be cancelled."
        )

    if order.side == Order.Side.BUY:
        portfolio.reserved_cash -= order.reserved_cash
        portfolio.save(
            update_fields=["reserved_cash", "updated_at"]
        )
    else:
        holding = Holding.objects.select_for_update().get(
            portfolio=portfolio,
            stock_id=order.stock_id,
        )
        holding.reserved_quantity -= order.reserved_shares
        holding.save(
            update_fields=["reserved_quantity", "updated_at"]
        )

    order.status = Order.Status.CANCELLED
    order.reserved_cash = Decimal("0.00")
    order.reserved_shares = 0
    order.cancelled_at = timezone.now()
    order.cancellation_reason = reason
    order.save(
        update_fields=[
            "status",
            "reserved_cash",
            "reserved_shares",
            "cancelled_at",
            "cancellation_reason",
            "updated_at",
        ]
    )

    return order

@transaction.atomic
def process_pending_orders(user, *, at=None, schedule=None):
    """Evaluate a customer's pending orders, oldest first."""
    if not user.is_authenticated:
        raise CancellationError("Log in to process orders.")

    portfolio = Portfolio.objects.select_for_update().filter(
        user=user
    ).first()

    if portfolio is None:
        return []

    evaluated_at = timezone.now() if at is None else at
    if not is_market_open(evaluated_at, schedule=schedule):
        return []

    orders = list(
        Order.objects.select_for_update()
        .filter(
            portfolio=portfolio,
            status=Order.Status.PENDING,
        )
        .order_by("created_at", "pk")
    )

    for order in orders:
        stock = Stock.objects.select_for_update().get(
            pk=order.stock_id
        )
        holding = Holding.objects.select_for_update().filter(
            portfolio=portfolio,
            stock=stock,
        ).first()

        execution_price = stock.current_price
        total = execution_price * order.quantity
        cancellation_reason = None

        if not stock.is_active:
            cancellation_reason = "Stock is no longer active."
        elif order.side == Order.Side.BUY:
            spendable_cash = (
                available_cash(portfolio) + order.reserved_cash
            )

            if total > spendable_cash:
                cancellation_reason = (
                    "Insufficient available cash at execution price."
                )
            elif (
                (holding.quantity if holding else 0)
                + order.quantity
                > MAX_QUANTITY
            ):
                cancellation_reason = (
                    "Purchase would exceed the supported holding quantity."
                )
        elif (
            portfolio.cash_balance + total
            > Decimal("9999999999.99")
        ):
            cancellation_reason = (
                "Sale would exceed the maximum account balance."
            )

        if cancellation_reason:
            cancel_pending_order(
                user,
                order.pk,
                reason=cancellation_reason,
            )
            portfolio.refresh_from_db()
            order.refresh_from_db()
            continue

        if order.side == Order.Side.BUY:
            if holding is None:
                holding = Holding.objects.create(
                    portfolio=portfolio,
                    stock=stock,
                    quantity=0,
                )

            portfolio.reserved_cash -= order.reserved_cash
            portfolio.cash_balance -= total
            holding.quantity += order.quantity
            transaction_type = CashTransaction.TransactionType.PURCHASE
            amount = -total
        else:
            holding.reserved_quantity -= order.reserved_shares
            holding.quantity -= order.quantity
            portfolio.cash_balance += total
            transaction_type = CashTransaction.TransactionType.SALE
            amount = total

        portfolio.save(
            update_fields=[
                "cash_balance",
                "reserved_cash",
                "updated_at",
            ]
        )
        holding.save(
            update_fields=[
                "quantity",
                "reserved_quantity",
                "updated_at",
            ]
        )

        order.status = Order.Status.EXECUTED
        order.execution_price = execution_price
        order.executed_at = evaluated_at
        order.reserved_cash = Decimal("0.00")
        order.reserved_shares = 0
        order.save(
            update_fields=[
                "status",
                "execution_price",
                "executed_at",
                "reserved_cash",
                "reserved_shares",
                "updated_at",
            ]
        )

        CashTransaction.objects.create(
            portfolio=portfolio,
            order=order,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=portfolio.cash_balance,
            description=(
                f"Executed {order.side.lower()} of "
                f"{order.quantity} shares of {stock.symbol}"
            ),
        )

    return orders
