from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone

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
    current_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
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
            )
        ]

    def save(self, *args, **kwargs):
        self.symbol = self.symbol.strip().upper()
        self.company_name = self.company_name.strip()
        super().save(*args, **kwargs)

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