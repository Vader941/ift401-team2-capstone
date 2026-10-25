"""Read-only, account-scoped portfolio and history queries."""

from decimal import Decimal

from accounts.services import available_cash
from trading.models import Portfolio


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
        }

    holdings = []
    holdings_value = Decimal("0.00")

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
        "holdings": holdings,
    }