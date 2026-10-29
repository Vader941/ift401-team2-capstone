"""Read-only, account-scoped portfolio and history queries."""

from decimal import Decimal

from accounts.services import available_cash
from trading.models import Portfolio, CashTransaction, Order

from django.core.paginator import Paginator

def get_portfolio_summary(user):
    """Return the user's balances and holdings without changing data.

    Monetary values are Decimal objects.
    Missing portfolios return None balances and an empty holdings list.
    """
    portfolio = Portfolio.objects.filter(user=user).first()

    if portfolio is None:
        return {
            "has_portfolio": False,
            "cash_balance": None,
            "reserved_cash": None,
            "available_cash": None,
            "holdings_value": None,
            "total_account_value": None,
            "holdings": [],
            "has_unknown_cost_basis": False,
            "unrealized_gain_loss": None,
        }

    holdings = []
    holdings_value = Decimal("0.00")
    unrealized_total = Decimal("0.00")
    has_unknown_cost_basis = False

    positions = (
        portfolio.holdings
        .filter(quantity__gt=0)
        .select_related("stock")
        .order_by("stock__symbol", "pk")
    )

    for holding in positions:
        stock = holding.stock
        position_value = stock.current_price * holding.quantity
        holdings_value += position_value
        cost_basis = holding.cost_basis
        average_cost = None
        unrealized_gain_loss = None
        unrealized_gain_loss_percent = None

        if cost_basis is None:
            has_unknown_cost_basis = True
        else:
            average_cost = cost_basis / holding.quantity
            unrealized_gain_loss = position_value - cost_basis
            unrealized_total += unrealized_gain_loss

            if cost_basis > 0:
                unrealized_gain_loss_percent = (
                    unrealized_gain_loss / cost_basis * Decimal("100")
                )

        holdings.append({
            "stock_id": stock.pk,
            "symbol": stock.symbol,
            "company_name": stock.company_name,
            "quantity": holding.quantity,
            "reserved_quantity": holding.reserved_quantity,
            "available_quantity": (
                holding.quantity - holding.reserved_quantity
            ),
            "current_price": stock.current_price,
            "position_value": position_value,
            "cost_basis": cost_basis,
            "average_cost": average_cost,
            "unrealized_gain_loss": unrealized_gain_loss,
            "unrealized_gain_loss_percent": unrealized_gain_loss_percent,
            "is_active": stock.is_active,
        })

    return {
        "has_portfolio": True,
        "cash_balance": portfolio.cash_balance,
        "reserved_cash": portfolio.reserved_cash,
        "available_cash": available_cash(portfolio),
        "holdings_value": holdings_value,
        "total_account_value": (
            portfolio.cash_balance + holdings_value
        ),
        "has_unknown_cost_basis": has_unknown_cost_basis,
        "unrealized_gain_loss": (
            None if has_unknown_cost_basis else unrealized_total
        ),
        "holdings": holdings,
    }

def get_account_history(user, *, page=1, per_page=25):
    """Return a paginated, newest-first history for the user's account.

    Executed trades appear through cash transactions only.
    Cancellations have no cash amount or resulting balance.
    Equal timestamps sort by source name, then source ID, descending.
    """
    if (
        isinstance(per_page, bool)
        or not isinstance(per_page, int)
        or per_page < 1
    ):
        raise ValueError("per_page must be a positive integer.")

    events = []

    cash_transactions = (
        CashTransaction.objects
        .filter(portfolio__user=user)
        .select_related("order__stock")
    )

    for entry in cash_transactions:
        order = entry.order
        is_trade = entry.transaction_type in (
            CashTransaction.TransactionType.PURCHASE,
            CashTransaction.TransactionType.SALE,
        )

        events.append({
            "event_id": f"cash:{entry.pk}",
            "event_type": entry.transaction_type,
            "occurred_at": entry.created_at,
            "amount": entry.amount,
            "balance_after": entry.balance_after,
            "order_id": entry.order_id,
            "symbol": order.stock.symbol if order else None,
            "quantity": order.quantity if order else None,
            "execution_price": (
                order.execution_price if order and is_trade else None
            ),
            "description": entry.description,
            "_source": "cash",
            "_source_id": entry.pk,
        })

    cancelled_orders = (
        Order.objects
        .filter(
            portfolio__user=user,
            status=Order.Status.CANCELLED,
        )
        .select_related("stock")
    )

    for order in cancelled_orders:
        if order.cancelled_at is None:
            raise ValueError(
                f"Cancelled order {order.pk} has no cancellation timestamp."
            )

        events.append({
            "event_id": f"cancelled_order:{order.pk}",
            "event_type": "CANCELLATION",
            "occurred_at": order.cancelled_at,
            "amount": None,
            "balance_after": None,
            "order_id": order.pk,
            "symbol": order.stock.symbol,
            "quantity": order.quantity,
            "execution_price": None,
            "description": order.cancellation_reason,
            "_source": "cancelled_order",
            "_source_id": order.pk,
        })

    events.sort(
        key=lambda event: (
            event["occurred_at"],
            event["_source"],
            event["_source_id"],
        ),
        reverse=True,
    )

    for event in events:
        del event["_source"]
        del event["_source_id"]

    return Paginator(events, per_page).get_page(page)