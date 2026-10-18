from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db import IntegrityError
from django.urls import reverse

from market.models import Stock

from .models import CashTransaction, Holding, Order, Portfolio
from .services import (
    place_buy_order,
    place_sell_order,
    process_pending_orders,
)


class PendingOrderServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pendingtrader"
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
        self.open_time = datetime(
            2026, 10, 19, 12, 0,
            tzinfo=ZoneInfo("America/New_York"),
        )
        self.closed_time = self.open_time.replace(hour=18)

    def submit_pending(self, sell=False, quantity=4):
        service = place_sell_order if sell else place_buy_order
        with patch(
            "trading.services.timezone.now",
            return_value=self.closed_time,
        ):
            return service(
                self.user, self.stock.pk, quantity
            )

    def process_at(self, at):
        with patch(
            "trading.services.timezone.now",
            return_value=at,
        ):
            return process_pending_orders(self.user)

    def test_pending_buy_uses_current_price_and_executes_once(self):
        order = self.submit_pending()
        Stock.objects.filter(pk=self.stock.pk).update(
            current_price=Decimal("30.00")
        )

        self.process_at(self.open_time)
        self.process_at(self.open_time)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(order.execution_price, Decimal("30.00"))
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("880.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("0.00")
        )
        self.assertEqual(self.holding.quantity, 14)

        entry = CashTransaction.objects.get(order=order)
        self.assertEqual(entry.amount, Decimal("-120.00"))
        self.assertEqual(entry.balance_after, Decimal("880.00"))

    def test_pending_sale_uses_current_price_and_releases_shares(self):
        order = self.submit_pending(sell=True)
        Stock.objects.filter(pk=self.stock.pk).update(
            current_price=Decimal("30.00")
        )

        self.process_at(self.open_time)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(order.reserved_shares, 0)
        self.assertEqual(self.holding.quantity, 6)
        self.assertEqual(self.holding.reserved_quantity, 0)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1120.00")
        )

        entry = CashTransaction.objects.get(order=order)
        self.assertEqual(entry.amount, Decimal("120.00"))

    def test_closed_market_leaves_order_pending(self):
        order = self.submit_pending()

        result = self.process_at(self.closed_time)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()

        self.assertEqual(result, [])
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("100.00")
        )
        self.assertFalse(CashTransaction.objects.exists())

    def test_insufficient_cash_cancels_order_and_releases_reservation(self):
        order = self.submit_pending(quantity=40)
        Stock.objects.filter(pk=self.stock.pk).update(
            current_price=Decimal("30.00")
        )

        self.process_at(self.open_time)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(
            order.cancellation_reason,
            "Insufficient available cash at execution price.",
        )
        self.assertIsNotNone(order.cancelled_at)
        self.assertEqual(order.reserved_cash, Decimal("0.00"))
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("0.00")
        )
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(self.holding.quantity, 10)
        self.assertFalse(CashTransaction.objects.exists())

    def test_repricing_protects_other_orders_reserved_cash(self):
        first = self.submit_pending(quantity=20)
        second = self.submit_pending(quantity=20)
        Stock.objects.filter(pk=self.stock.pk).update(
            current_price=Decimal("30.00")
        )

        self.process_at(self.open_time)

        first.refresh_from_db()
        second.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(first.status, Order.Status.CANCELLED)
        self.assertEqual(second.status, Order.Status.EXECUTED)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("400.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("0.00")
        )
        self.assertEqual(self.holding.quantity, 30)
        self.assertEqual(CashTransaction.objects.count(), 1)

    def test_ledger_failure_rolls_back_pending_execution(self):
        order = self.submit_pending()

        with patch(
            "trading.services.CashTransaction.objects.create",
            side_effect=IntegrityError("Forced ledger failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.process_at(self.open_time)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertIsNone(order.execution_price)
        self.assertIsNone(order.executed_at)
        self.assertEqual(order.reserved_cash, Decimal("100.00"))
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("100.00")
        )
        self.assertEqual(self.holding.quantity, 10)
        self.assertFalse(CashTransaction.objects.exists())

    def test_dashboard_executes_pending_order_and_shows_updated_cash(self):
        order = self.submit_pending()
        self.client.force_login(self.user)

        with patch(
            "trading.services.timezone.now",
            return_value=self.open_time,
        ):
            response = self.client.get(
                reverse("trading:dashboard")
            )

        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(self.holding.quantity, 14)
        self.assertEqual(
            response.context["cash_balance"],
            Decimal("900.00"),
        )
        self.assertEqual(
            response.context["reserved_cash"],
            Decimal("0.00"),
        )
        self.assertEqual(
            CashTransaction.objects.filter(order=order).count(),
            1,
        )