import random
from datetime import time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from .models import MarketException, PriceHistory, Stock, StockDailyStatistic


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




def market_date_for(at=None):
    """Return the calendar date of an aware datetime in the market time zone."""
    at = timezone.now() if at is None else at
    if timezone.is_naive(at):
        raise ValueError("Market dates require a timezone-aware datetime.")
    return at.astimezone(MARKET_TIME_ZONE).date()


def record_daily_price(stock, price, at):
    """Fold an established price into the stock's statistics for that day.

    The first price recorded on a market day becomes the opening price.
    update_stock_price records the price in effect before its first change
    of the day, so the opening reflects the start of trading. Every
    recorded price, including the opening, updates the high and low.
    Call while the Stock row is locked. Returns the price.
    """
    daily, created = StockDailyStatistic.objects.get_or_create(
        stock=stock,
        market_date=market_date_for(at),
        defaults={
            "opening_price": price,
            "high_price": price,
            "low_price": price,
        },
    )
    if not created and (price > daily.high_price or price < daily.low_price):
        daily.high_price = max(daily.high_price, price)
        daily.low_price = min(daily.low_price, price)
        daily.save(update_fields=["high_price", "low_price", "updated_at"])
    return price


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
        # The price in effect when the market day's first update is
        # evaluated becomes that day's opening, so the daily change covers
        # the full movement from the start of trading.
        record_daily_price(locked_stock, previous_price, at)
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
        record_daily_price(locked_stock, new_price, at)

    stock.current_price = new_price
    return new_price


PERCENT = Decimal("0.01")


def get_stock_statistics(stock, *, at=None):
    """Return the documented market-data values for one stock.

    Values come from stored data only; this function never changes prices.
    The reference day is the most recent recorded market day on or before
    ``at``. Before any recorded day, the initial price is used as the
    opening, high, and low reference.
    """
    at = timezone.now() if at is None else at
    daily = (
        StockDailyStatistic.objects.filter(
            stock_id=stock.pk,
            market_date__lte=market_date_for(at),
        )
        .order_by("-market_date")
        .first()
    )
    current = stock.current_price
    if daily is None:
        opening = high = low = stock.initial_price
        market_date = None
    else:
        opening, high, low = daily.opening_price, daily.high_price, daily.low_price
        market_date = daily.market_date

    change = current - opening
    change_percent = (change / opening * Decimal("100")).quantize(
        PERCENT, rounding=ROUND_HALF_UP
    )
    return {
        "symbol": stock.symbol,
        "company_name": stock.company_name,
        "initial_price": stock.initial_price,
        "current_price": current,
        "share_volume": stock.share_volume,
        "market_capitalization": Decimal(stock.share_volume) * current,
        "opening_price": opening,
        "high_price": high,
        "low_price": low,
        "price_change": change,
        "price_change_percent": change_percent,
        "statistics_date": market_date,
    }
