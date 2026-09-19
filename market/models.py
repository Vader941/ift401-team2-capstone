from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q


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