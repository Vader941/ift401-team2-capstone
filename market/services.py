import random
from datetime import time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from .models import MarketException, PriceHistory, Stock


MARKET_TIME_ZONE = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def is_market_open(at=None):
    """Return whether the simulated market is open at an aware datetime."""
    at = timezone.now() if at is None else at
    if timezone.is_naive(at):
        raise ValueError("Market checks require a timezone-aware datetime.")

    local_at = at.astimezone(MARKET_TIME_ZONE)

    # Weekend trading is outside the current project requirements.
    if local_at.weekday() >= 5:
        return False

    exception = MarketException.objects.filter(date=local_at.date()).first()
    if exception is not None:
        if exception.is_closed:
            return False
        opens_at, closes_at = exception.opens_at, exception.closes_at
    else:
        opens_at, closes_at = REGULAR_OPEN, REGULAR_CLOSE

    # Opening is inclusive; closing is exclusive.
    return opens_at <= local_at.time() < closes_at



def update_stock_price(
    stock,
    *,
    at=None,
    random_source=None,
    minimum_interval=timedelta(seconds=60),
    max_change_percent=Decimal("1.00"),
):
    """Update one stock when the market is open and its interval has elapsed.

    Return the stored price. random_source, when supplied, receives the
    negative and positive percentage bounds and returns a percentage.
    """
    at = timezone.now() if at is None else at
    if timezone.is_naive(at):
        raise ValueError("Price updates require a timezone-aware datetime.")
    if minimum_interval < timedelta(0):
        raise ValueError("The minimum interval cannot be negative.")

    max_change_percent = Decimal(str(max_change_percent))
    if max_change_percent < 0:
        raise ValueError("The maximum percentage change cannot be negative.")

    if not is_market_open(at):
        return Stock.objects.get(pk=stock.pk).current_price

    if random_source is None:
        def source(low, high):
            return Decimal(str(random.uniform(float(low), float(high))))
    else:
        source = random_source

    with transaction.atomic():
        locked_stock = Stock.objects.select_for_update().get(pk=stock.pk)
        previous_price = locked_stock.current_price
        latest = locked_stock.price_history.first()

        if latest is not None and at - latest.effective_at < minimum_interval:
            return previous_price

        proposed_change = Decimal(
            str(source(-max_change_percent, max_change_percent))
        )
        if (
            not proposed_change.is_finite()
            or abs(proposed_change) > max_change_percent
        ):
            raise ValueError("Random percentage is outside the allowed range.")

        new_price = (
            previous_price
            * (Decimal("1") + proposed_change / Decimal("100"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        new_price = max(new_price, Decimal("0.01"))

        # A proposed change that rounds to the existing cent is not recorded
        # as a price change.
        if new_price == previous_price:
            return previous_price

        actual_change = (
            (new_price - previous_price)
            / previous_price
            * Decimal("100")
        )
        if abs(actual_change) > max_change_percent:
            return previous_price

        actual_change = actual_change.quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )
        locked_stock.current_price = new_price
        locked_stock.save(update_fields=["current_price", "updated_at"])
        PriceHistory.objects.create(
            stock=locked_stock,
            previous_price=previous_price,
            new_price=new_price,
            percentage_change=actual_change,
            effective_at=at,
        )

    stock.current_price = new_price
    return new_price
