
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Portfolio(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='portfolio',
    )
    cash_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('25000.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    reserved_cash = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cash_balance__gte=Decimal('0.00')),
                name='cash_balance_not_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_cash__gte=Decimal('0.00')),
                name='reserved_cash_not_negative',
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_cash__lte=models.F('cash_balance')),
                name='reserved_cash_not_exceed_cash_balance',
            ),
        ]    

    def __str__(self):
        return f"{self.user} portfolio (${self.cash_balance})"

class Holding(models.Model):
    portfolio = models.ForeignKey(
        Portfolio,
        on_delete=models.CASCADE,
        related_name='holdings',
    )
    stock = models.ForeignKey(
        'market.Stock',
        on_delete=models.PROTECT,
        related_name='holdings',
    )
    quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['portfolio', 'stock'],
                name='unique_holding_per_portfolio_stock',
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_quantity__lte=models.F('quantity')),
                name='reserved_quantity_not_exceed_quantity',
            ),
        ]

    def __str__(self):
        return f"{self.portfolio.user} holds {self.quantity} {self.stock.symbol}"
