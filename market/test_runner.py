from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from trading.models import CashTransaction, Order, Portfolio
from trading.services import place_buy_order

from .models import PriceHistory, Stock
from .runner import run_market_cycle


class MarketCycleTests(TestCase):
    def setUp(self):
        self.open_time = datetime(
            2026, 10, 19, 12, 0,
            tzinfo=ZoneInfo("America/New_York"),
        )
        self.closed_time = self.open_time.replace(hour=18)

        self.stock = Stock.objects.create(
            symbol="TEST",
            company_name="Test Company",
            current_price=Decimal("100.00"),
        )

        self.user = get_user_model().objects.create_user(
            username="workertrader"
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            cash_balance=Decimal("1000.00"),
        )

    def submit_pending_buy(self, user=None):
        with patch(
            "trading.services.timezone.now",
            return_value=self.closed_time,
        ):
            return place_buy_order(
                user or self.user,
                self.stock.pk,
                2,
            )

    def run_cycle_at(self, at):
        with (
            patch("market.runner.timezone.now", return_value=at),
            patch("market.services.random.uniform", return_value=1),
        ):
            return run_market_cycle()

    def test_closed_market_preserves_prices_and_pending_orders(self):
        order = self.submit_pending_buy()

        result = self.run_cycle_at(self.closed_time)

        self.stock.refresh_from_db()
        order.refresh_from_db()
        self.portfolio.refresh_from_db()

        self.assertFalse(result["market_open"])
        self.assertEqual(result["stocks_checked"], 0)
        self.assertEqual(self.stock.current_price, Decimal("100.00"))
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("200.00")
        )
        self.assertFalse(PriceHistory.objects.exists())
        self.assertFalse(CashTransaction.objects.exists())

    def test_repeated_cycle_does_not_duplicate_price_or_execution(self):
        order = self.submit_pending_buy()

        self.run_cycle_at(self.open_time)
        second = self.run_cycle_at(self.open_time)

        self.stock.refresh_from_db()
        order.refresh_from_db()
        self.portfolio.refresh_from_db()

        self.assertEqual(self.stock.current_price, Decimal("101.00"))
        self.assertEqual(PriceHistory.objects.count(), 1)
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(
            CashTransaction.objects.filter(order=order).count(), 1
        )
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("798.00")
        )
        self.assertEqual(second["prices_changed"], 0)
        self.assertEqual(second["portfolios_processed"], 0)

    def test_inactive_stock_is_not_updated(self):
        self.stock.is_active = False
        self.stock.save(update_fields=["is_active"])

        result = self.run_cycle_at(self.open_time)

        self.stock.refresh_from_db()
        self.assertEqual(result["stocks_checked"], 0)
        self.assertEqual(self.stock.current_price, Decimal("100.00"))
        self.assertFalse(PriceHistory.objects.exists())

    def test_price_failure_prevents_order_processing(self):
        order = self.submit_pending_buy()

        with (
            patch(
                "market.runner.timezone.now",
                return_value=self.open_time,
            ),
            patch(
                "market.runner.update_stock_price",
                side_effect=RuntimeError("Forced price failure"),
            ),
            patch(
                "market.runner.process_pending_orders"
            ) as process_orders,
        ):
            with self.assertRaises(RuntimeError):
                run_market_cycle()

        process_orders.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_customer_failure_rolls_back_and_other_customer_executes(self):
        first_order = self.submit_pending_buy()

        other_user = get_user_model().objects.create_user(
            username="otherworkertrader"
        )
        Portfolio.objects.create(
            user=other_user,
            cash_balance=Decimal("1000.00"),
        )
        second_order = self.submit_pending_buy(other_user)

        original_create = CashTransaction.objects.create

        def create_with_first_customer_failure(**kwargs):
            if kwargs["portfolio"].pk == self.portfolio.pk:
                raise RuntimeError("Forced ledger failure")
            return original_create(**kwargs)

        with (
            patch(
                "trading.services.CashTransaction.objects.create",
                side_effect=create_with_first_customer_failure,
            ),
            self.assertLogs("market.runner", level="ERROR"),
        ):
            result = self.run_cycle_at(self.open_time)

        first_order.refresh_from_db()
        second_order.refresh_from_db()
        self.portfolio.refresh_from_db()

        self.assertEqual(result["portfolio_errors"], 1)
        self.assertEqual(result["portfolios_processed"], 1)
        self.assertEqual(first_order.status, Order.Status.PENDING)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("200.00")
        )
        self.assertFalse(
            CashTransaction.objects.filter(order=first_order).exists()
        )
        self.assertEqual(second_order.status, Order.Status.EXECUTED)
        self.assertEqual(
            CashTransaction.objects.filter(order=second_order).count(),
            1,
        )