"""Read-only queries for stored simulated market observations."""

from datetime import timezone as datetime_timezone
from zoneinfo import ZoneInfo

from .models import PriceHistory


EASTERN = ZoneInfo("America/New_York")


def _timestamp_values(moment):
    return {
        "timestamp": moment.astimezone(
            datetime_timezone.utc
        ).isoformat(),
        "display_timestamp": moment.astimezone(EASTERN).isoformat(),
    }


def get_stock_price_history(stock, *, limit=180):
    """Return existing observations without generating prices or writes.

    Prices are decimal strings. UTC timestamps identify instants;
    Eastern timestamps include their DST-aware numeric offset.
    """
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 1000
    ):
        raise ValueError("limit must be an integer from 1 to 1000.")

    observations = list(
        PriceHistory.objects.filter(stock=stock)
        .order_by("-effective_at", "-pk")[:limit]
    )
    observations.reverse()

    points = [
        {
            "observation_id": observation.pk,
            **_timestamp_values(observation.effective_at),
            "price": str(observation.new_price),
        }
        for observation in observations
    ]

    latest = points[-1] if points else None

    return {
        "stock_id": stock.pk,
        "symbol": stock.symbol,
        "timezone": "America/New_York",
        "timezone_label": "ET",
        "limit": limit,
        "points": points,
        "last_observed_price": latest["price"] if latest else None,
        "data_as_of": latest["timestamp"] if latest else None,
        "display_data_as_of": (
            latest["display_timestamp"] if latest else None
        ),
    }