import logging

from django.utils import timezone

from trading.models import Order, Portfolio
from trading.services import process_pending_orders

from .models import Stock
from .services import is_market_open, update_stock_price
from .schedule import get_market_schedule

logger = logging.getLogger(__name__)


def run_market_cycle():
    """Advance active stocks, then evaluate customers' pending orders."""
    at = timezone.now()
    schedule = get_market_schedule()
    result = {
        "market_open": is_market_open(at, schedule=schedule),
        "stocks_checked": 0,
        "prices_changed": 0,
        "portfolios_processed": 0,
        "portfolio_errors": 0,
    }

    if not result["market_open"]:
        return result

    # Finish the price pass before processing orders.
    # If a price update fails, let the worker report the failed cycle
    # rather than proceeding with an incomplete price pass.
    for stock in Stock.objects.filter(is_active=True).iterator():
        previous_price = stock.current_price
        current_price = update_stock_price(
            stock, at=at, schedule=schedule
        )

        result["stocks_checked"] += 1
        if current_price != previous_price:
            result["prices_changed"] += 1

    pending_portfolio_ids = (
        Order.objects.filter(status=Order.Status.PENDING)
        .order_by()
        .values_list("portfolio_id", flat=True)
        .distinct()
    )

    portfolios = (
        Portfolio.objects.filter(pk__in=pending_portfolio_ids)
        .select_related("user")
        .order_by("pk")
    )

    for portfolio in portfolios.iterator():
        try:
            process_pending_orders(
                portfolio.user, at=at, schedule=schedule
            )
        except Exception:
            # Each customer's service has its own transaction.
            # A failed customer must not prevent others being processed.
            logger.exception(
                "Pending-order processing failed for portfolio %s.",
                portfolio.pk,
            )
            result["portfolio_errors"] += 1
        else:
            result["portfolios_processed"] += 1

    return result