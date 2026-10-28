from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import time

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone

# Simulated shares represented by a stock (not daily trading volume).
# Used for programmatic creation and for backfilling existing stocks;
# the administrator form always requires an explicit value.
DEFAULT_SHARE_VOLUME = 1_000_000


class Stock(models.Model):
    symbol = models.CharField(
        max_length=10,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Za-z][A-Za-z0-9.-]*$",
                message="Enter a valid stock symbol.",
            )
        ],
    )
    company_name = models.CharField(max_length=200)
    initial_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Starting simulated price. Preserved after creation.",
    )
    current_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    share_volume = models.PositiveBigIntegerField(
        default=DEFAULT_SHARE_VOLUME,
        validators=[MinValueValidator(1)],
        help_text=(
            "Total simulated shares represented by the stock. "
            "Not daily trading volume."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["symbol"]
        constraints = [
            models.CheckConstraint(
                condition=Q(current_price__gte=Decimal("0.01")),
                name="stock_price_at_least_one_cent",
            ),
            models.CheckConstraint(
                condition=Q(initial_price__gte=Decimal("0.01")),
                name="stock_initial_price_at_least_one_cent",
            ),
            models.CheckConstraint(
                condition=Q(share_volume__gte=1),
                name="stock_share_volume_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        self.symbol = self.symbol.strip().upper()
        self.company_name = self.company_name.strip()
        # A new stock starts trading at its initial price. Existing callers
        # that only supply current_price keep working.
        if self.initial_price is None and self.current_price is not None:
            self.initial_price = self.current_price
        if self.current_price is None and self.initial_price is not None:
            self.current_price = self.initial_price
        super().save(*args, **kwargs)

    @property
    def market_capitalization(self):
        """share_volume x current_price, in simulated dollars."""
        return Decimal(self.share_volume) * self.current_price

    @property
    def statistics(self):
        """Market statistics for templates; see market.services."""
        from .services import get_stock_statistics

        return get_stock_statistics(self)

    def __str__(self):
        return f"{self.symbol} - {self.company_name}"

class MarketException(models.Model):
    date = models.DateField(unique=True)
    is_closed = models.BooleanField(default=True)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        is_closed=True,
                        opens_at__isnull=True,
                        closes_at__isnull=True,
                    )
                    | (
                        Q(
                            is_closed=False,
                            opens_at__isnull=False,
                            closes_at__isnull=False,
                        )
                        & Q(closes_at__gt=models.F("opens_at"))
                    )
                ),
                name="valid_market_exception_hours",
            )
        ]

    def clean(self):
        super().clean()

        if self.is_closed:
            if self.opens_at is not None or self.closes_at is not None:
                raise ValidationError(
                    "A full-day closure cannot have trading hours."
                )
        elif (
            self.opens_at is None
            or self.closes_at is None
            or self.closes_at <= self.opens_at
        ):
            raise ValidationError(
                "Special hours require an opening time and a later closing time."
            )

    def __str__(self):
        if self.is_closed:
            return f"{self.date}: closed"
        return f"{self.date}: {self.opens_at}–{self.closes_at}"

class PriceHistory(models.Model):
    stock = models.ForeignKey(
        Stock,
        on_delete=models.PROTECT,
        related_name="price_history",
    )
    previous_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    new_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    percentage_change = models.DecimalField(
        max_digits=8,
        decimal_places=4,
    )
    effective_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-effective_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(previous_price__gte=Decimal("0.01")),
                name="history_previous_price_at_least_one_cent",
            ),
            models.CheckConstraint(
                condition=Q(new_price__gte=Decimal("0.01")),
                name="history_new_price_at_least_one_cent",
            ),
        ]

    def __str__(self):
        return (
            f"{self.stock.symbol}: "
            f"${self.previous_price} to ${self.new_price}"
        )


class StockDailyStatistic(models.Model):
    """Opening, high, and low price for one stock on one market day."""

    stock = models.ForeignKey(
        Stock,
        on_delete=models.PROTECT,
        related_name="daily_statistics",
    )
    market_date = models.DateField(
        help_text="Calendar date in the market time zone.",
    )
    opening_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    high_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    low_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-market_date", "stock__symbol"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock", "market_date"],
                name="unique_daily_statistic_per_stock_day",
            ),
            models.CheckConstraint(
                condition=Q(low_price__gte=Decimal("0.01")),
                name="daily_low_at_least_one_cent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(low_price__lte=models.F("opening_price"))
                    & Q(opening_price__lte=models.F("high_price"))
                ),
                name="daily_low_open_high_order",
            ),
        ]

    def __str__(self):
        return (
            f"{self.stock.symbol} {self.market_date}: "
            f"O {self.opening_price} H {self.high_price} L {self.low_price}"
        )
class MarketSchedule(models.Model):
    """One regular schedule for the simulated market."""

    id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=1,
        editable=False,
    )
    opening_time = models.TimeField(default=time(9, 30))
    closing_time = models.TimeField(default=time(16, 0))
    timezone_name = models.CharField(
        max_length=100,
        default="America/New_York",
        help_text="IANA timezone, such as America/New_York.",
    )
    monday = models.BooleanField(default=True)
    tuesday = models.BooleanField(default=True)
    wednesday = models.BooleanField(default=True)
    thursday = models.BooleanField(default=True)
    friday = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "regular market schedule"
        verbose_name_plural = "regular market schedule"
        constraints = [
            models.CheckConstraint(
                condition=Q(id=1),
                name="market_schedule_singleton",
            ),
            models.CheckConstraint(
                condition=Q(closing_time__gt=models.F("opening_time")),
                name="market_schedule_valid_hours",
            ),
            models.CheckConstraint(
                condition=(
                    Q(monday=True)
                    | Q(tuesday=True)
                    | Q(wednesday=True)
                    | Q(thursday=True)
                    | Q(friday=True)
                ),
                name="market_schedule_has_weekday",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            errors["timezone_name"] = "Enter a valid IANA timezone."

        if (
            self.opening_time is not None
            and self.closing_time is not None
            and self.closing_time <= self.opening_time
        ):
            errors["closing_time"] = (
                "Closing time must be later than opening time "
                "on the same day."
            )

        if not any((
            self.monday,
            self.tuesday,
            self.wednesday,
            self.thursday,
            self.friday,
        )):
            errors["monday"] = "Select at least one trading weekday."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"Regular market schedule ({self.timezone_name})"
        )