from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from market.models import MarketException, Stock

from .models import CashTransaction, Holding, Order, Portfolio
from .services import BuyOrderError, place_buy_order


User = get_user_model()
NEW_YORK = ZoneInfo("America/New_York")


class BuyOrderServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buyer")
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            cash_balance=Decimal("1000.00"),
        )
        self.stock = Stock.objects.create(
            symbol="TEST",
            company_name="Test Company",
            current_price=Decimal("25.00"),
        )
        self.open_time = datetime(
            2026, 10, 7, 12, 0, tzinfo=NEW_YORK
        )
        self.closed_time = datetime(
            2026, 10, 7, 18, 0, tzinfo=NEW_YORK
        )

    def buy_at(self, at, quantity=4):
        with patch("trading.services.timezone.now", return_value=at):
            return place_buy_order(
                self.user, self.stock.pk, quantity
            )

    def assert_no_trade_changes(self):
        self.portfolio.refresh_from_db()
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("0.00")
        )
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Holding.objects.exists())
        self.assertFalse(CashTransaction.objects.exists())

    def test_open_market_buy_executes_and_records_purchase(self):
        order = self.buy_at(self.open_time)

        self.portfolio.refresh_from_db()
        self.assertEqual(order.side, Order.Side.BUY)
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(order.submission_price, Decimal("25.00"))
        self.assertEqual(order.execution_price, Decimal("25.00"))
        self.assertEqual(order.executed_at, self.open_time)
        self.assertEqual(order.reserved_cash, Decimal("0.00"))
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("900.00")
        )

        holding = Holding.objects.get(
            portfolio=self.portfolio, stock=self.stock
        )
        self.assertEqual(holding.quantity, 4)

        entry = CashTransaction.objects.get(order=order)
        self.assertEqual(
            entry.transaction_type,
            CashTransaction.TransactionType.PURCHASE,
        )
        self.assertEqual(entry.amount, Decimal("-100.00"))
        self.assertEqual(entry.balance_after, Decimal("900.00"))

    def test_closed_market_buy_reserves_cash_only(self):
        order = self.buy_at(self.closed_time)

        self.portfolio.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.reserved_cash, Decimal("100.00"))
        self.assertIsNone(order.execution_price)
        self.assertIsNone(order.executed_at)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("100.00")
        )
        self.assertFalse(Holding.objects.exists())
        self.assertFalse(CashTransaction.objects.exists())

    def test_open_market_buy_adds_to_existing_holding(self):
        holding = Holding.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            quantity=6,
            reserved_quantity=2,
        )

        self.buy_at(self.open_time)

        holding.refresh_from_db()
        self.assertEqual(holding.quantity, 10)
        self.assertEqual(holding.reserved_quantity, 2)
        self.assertEqual(Holding.objects.count(), 1)

    def test_buy_cannot_spend_cash_reserved_by_pending_order(self):
        self.buy_at(self.closed_time, quantity=36)

        with self.assertRaises(BuyOrderError):
            self.buy_at(self.open_time, quantity=5)

        self.portfolio.refresh_from_db()
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("900.00")
        )
        self.assertEqual(Order.objects.count(), 1)
        self.assertFalse(Holding.objects.exists())
        self.assertFalse(CashTransaction.objects.exists())

    def test_buy_can_spend_exactly_the_available_cash(self):
        self.buy_at(self.closed_time, quantity=36)
        order = self.buy_at(self.open_time, quantity=4)

        self.portfolio.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("900.00")
        )
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("900.00")
        )

    def test_insufficient_funds_leaves_no_changes(self):
        with self.assertRaises(BuyOrderError):
            self.buy_at(self.open_time, quantity=41)

        self.assert_no_trade_changes()

    def test_invalid_quantities_leave_no_changes(self):
        for quantity in (0, -1, 1.5, "4", True, 2_147_483_648):
            with self.subTest(quantity=quantity):
                with self.assertRaises(BuyOrderError):
                    self.buy_at(self.open_time, quantity=quantity)

                self.assert_no_trade_changes()

    def test_inactive_stock_leaves_no_changes(self):
        self.stock.is_active = False
        self.stock.save(update_fields=["is_active"])

        with self.assertRaises(BuyOrderError):
            self.buy_at(self.open_time)

        self.assert_no_trade_changes()

    def test_service_uses_current_stored_price(self):
        Stock.objects.filter(pk=self.stock.pk).update(
            current_price=Decimal("30.00")
        )

        order = self.buy_at(self.open_time)

        self.portfolio.refresh_from_db()
        self.assertEqual(order.submission_price, Decimal("30.00"))
        self.assertEqual(order.execution_price, Decimal("30.00"))
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("880.00")
        )

    def test_market_closure_creates_pending_order(self):
        MarketException.objects.create(
            date=self.open_time.date(),
            is_closed=True,
        )

        order = self.buy_at(self.open_time)

        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertFalse(CashTransaction.objects.exists())

    def test_ledger_failure_rolls_back_entire_purchase(self):
        with patch(
            "trading.services.CashTransaction.objects.create",
            side_effect=IntegrityError("Forced ledger failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.buy_at(self.open_time)

        self.assert_no_trade_changes()