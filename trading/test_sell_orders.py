from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.db import IntegrityError

from market.models import Stock

from .models import CashTransaction, Holding, Order, Portfolio
from .services import SellOrderError, place_sell_order


class SellOrderServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="seller"
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

    def sell_at(self, at, quantity=4):
        with patch("trading.services.timezone.now", return_value=at):
            return place_sell_order(
                self.user, self.stock.pk, quantity
            )

    def test_open_market_sale_updates_cash_shares_and_ledger(self):
        order = self.sell_at(self.open_time)

        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(order.execution_price, Decimal("25.00"))
        self.assertEqual(order.executed_at, self.open_time)
        self.assertEqual(order.reserved_shares, 0)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1100.00")
        )
        self.assertEqual(self.holding.quantity, 6)
        self.assertEqual(self.holding.reserved_quantity, 0)

        entry = CashTransaction.objects.get(order=order)
        self.assertEqual(
            entry.transaction_type,
            CashTransaction.TransactionType.SALE,
        )
        self.assertEqual(entry.amount, Decimal("100.00"))
        self.assertEqual(entry.balance_after, Decimal("1100.00"))

    def test_closed_market_sale_only_reserves_shares(self):
        order = self.sell_at(self.closed_time)

        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.reserved_shares, 4)
        self.assertIsNone(order.execution_price)
        self.assertIsNone(order.executed_at)
        self.assertEqual(self.holding.quantity, 10)
        self.assertEqual(self.holding.reserved_quantity, 4)
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertFalse(CashTransaction.objects.exists())

    def test_reserved_shares_cannot_be_sold_again(self):
        self.sell_at(self.closed_time, quantity=7)

        with self.assertRaises(SellOrderError):
            self.sell_at(self.open_time, quantity=4)

        self.holding.refresh_from_db()
        self.assertEqual(self.holding.quantity, 10)
        self.assertEqual(self.holding.reserved_quantity, 7)
        self.assertEqual(Order.objects.count(), 1)
        self.assertFalse(CashTransaction.objects.exists())

    def test_invalid_quantities_leave_account_unchanged(self):
        for quantity in (0, -1, True, "4", 1.5, 2_147_483_648, 11):
            with self.subTest(quantity=quantity):
                with self.assertRaises(SellOrderError):
                    self.sell_at(self.open_time, quantity=quantity)

        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(self.holding.quantity, 10)
        self.assertEqual(self.holding.reserved_quantity, 0)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(CashTransaction.objects.exists())

    def test_ledger_failure_rolls_back_entire_sale(self):
        with patch(
            "trading.services.CashTransaction.objects.create",
            side_effect=IntegrityError("Forced ledger failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.sell_at(self.open_time)

        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()

        self.assertEqual(
            self.portfolio.cash_balance, Decimal("1000.00")
        )
        self.assertEqual(self.holding.quantity, 10)
        self.assertEqual(self.holding.reserved_quantity, 0)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(CashTransaction.objects.exists())