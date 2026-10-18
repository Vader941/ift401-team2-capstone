from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from market.models import Stock

from .models import CashTransaction, Holding, Order, Portfolio
from .services import (
    CancellationError,
    cancel_pending_order,
    place_buy_order,
    place_sell_order,
)


class CancellationServiceTests(TestCase):
    def setUp(self):
        price_patch = patch(
            "market.services.random.uniform",
            return_value=0,
        )
        price_patch.start()
        self.addCleanup(price_patch.stop)

        self.user = get_user_model().objects.create_user(
            username="trader"
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            cash_balance=Decimal("1000.00"),
        )
        self.stock = Stock.objects.create(
            symbol="TEST",
            company_name="Test Company",
            current_price=Decimal("25.00"),
        )
        self.holding = Holding.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            quantity=10,
        )
        self.closed_time = datetime(
            2026, 10, 19, 18, 0,
            tzinfo=ZoneInfo("America/New_York"),
        )

    def pending_order(self, sell=False):
        service = place_sell_order if sell else place_buy_order
        with patch(
            "trading.services.timezone.now",
            return_value=self.closed_time,
        ):
            return service(self.user, self.stock.pk, 4)

    def test_cancel_buy_releases_cash(self):
        order = self.pending_order()

        cancel_pending_order(self.user, order.pk)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.reserved_cash, Decimal("0.00"))
        self.assertIsNotNone(order.cancelled_at)
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("0.00")
        )
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertFalse(CashTransaction.objects.exists())

    def test_cancel_sell_releases_shares(self):
        order = self.pending_order(sell=True)

        cancel_pending_order(self.user, order.pk)

        order.refresh_from_db()
        self.holding.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.reserved_shares, 0)
        self.assertEqual(self.holding.quantity, 10)
        self.assertEqual(self.holding.reserved_quantity, 0)
        self.assertFalse(CashTransaction.objects.exists())

    def test_other_customer_cannot_cancel_order(self):
        order = self.pending_order()
        other_user = get_user_model().objects.create_user(
            username="other"
        )
        Portfolio.objects.create(user=other_user)

        with self.assertRaises(CancellationError):
            cancel_pending_order(other_user, order.pk)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("100.00")
        )

    def test_order_cannot_be_cancelled_twice(self):
        order = self.pending_order()
        cancel_pending_order(self.user, order.pk)

        with self.assertRaises(CancellationError):
            cancel_pending_order(self.user, order.pk)

        self.portfolio.refresh_from_db()
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("0.00")
        )
        self.assertEqual(Order.objects.count(), 1)

    def test_executed_order_cannot_be_cancelled(self):
        open_time = self.closed_time.replace(hour=12)
        with patch(
            "trading.services.timezone.now",
            return_value=open_time,
        ):
            order = place_buy_order(
                self.user, self.stock.pk, 4
            )

        with self.assertRaises(CancellationError):
            cancel_pending_order(self.user, order.pk)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("900.00")
        )
        self.assertEqual(
            CashTransaction.objects.filter(order=order).count(), 1
        )