from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from market.models import Stock
from trading.models import Holding, Portfolio
from trading.queries import get_portfolio_summary


class PortfolioSummaryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="summary_owner")
        self.other_user = User.objects.create_user(username="other_owner")
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            cash_balance=Decimal("20000.00"),
            reserved_cash=Decimal("1000.00"),
        )

    def make_stock(self, symbol, price, *, active=True):
        return Stock.objects.create(
            symbol=symbol,
            company_name=f"{symbol} Company",
            initial_price=Decimal(price),
            current_price=Decimal(price),
            is_active=active,
        )

    def test_existing_portfolio_without_holdings(self):
        result = get_portfolio_summary(self.user)

        self.assertTrue(result["has_portfolio"])
        self.assertEqual(result["holdings"], [])
        self.assertEqual(result["holdings_value"], Decimal("0.00"))
        self.assertEqual(result["total_account_value"], Decimal("20000.00"))
        self.assertEqual(result["available_cash"], Decimal("19000.00"))

    def test_reservations_do_not_reduce_total_account_value(self):
        stock = self.make_stock("TEST", "100.00")
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=stock,
            quantity=50,
            reserved_quantity=10,
        )

        result = get_portfolio_summary(self.user)
        position = result["holdings"][0]

        self.assertEqual(result["cash_balance"], Decimal("20000.00"))
        self.assertEqual(result["reserved_cash"], Decimal("1000.00"))
        self.assertEqual(result["available_cash"], Decimal("19000.00"))
        self.assertEqual(result["holdings_value"], Decimal("5000.00"))
        self.assertEqual(result["total_account_value"], Decimal("25000.00"))
        self.assertEqual(position["quantity"], 50)
        self.assertEqual(position["reserved_quantity"], 10)
        self.assertEqual(position["available_quantity"], 40)
        self.assertEqual(position["position_value"], Decimal("5000.00"))

    def test_other_users_holdings_are_excluded(self):
        other_portfolio = Portfolio.objects.create(user=self.other_user)
        stock = self.make_stock("OTHER", "250.00")
        Holding.objects.create(
            portfolio=other_portfolio,
            stock=stock,
            quantity=100,
        )

        result = get_portfolio_summary(self.user)

        self.assertEqual(result["holdings"], [])
        self.assertEqual(result["holdings_value"], Decimal("0.00"))
        self.assertEqual(result["total_account_value"], Decimal("20000.00"))

    def test_inactive_holdings_are_included_and_zero_holdings_excluded(self):
        inactive = self.make_stock("INACT", "12.34", active=False)
        empty = self.make_stock("EMPTY", "50.00")
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=inactive,
            quantity=3,
            reserved_quantity=1,
        )
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=empty,
            quantity=0,
        )

        result = get_portfolio_summary(self.user)

        self.assertEqual(len(result["holdings"]), 1)
        position = result["holdings"][0]
        self.assertEqual(position["stock_id"], inactive.pk)
        self.assertEqual(position["symbol"], "INACT")
        self.assertEqual(position["company_name"], "INACT Company")
        self.assertFalse(position["is_active"])
        self.assertEqual(position["available_quantity"], 2)
        self.assertEqual(position["current_price"], Decimal("12.34"))
        self.assertEqual(result["holdings_value"], Decimal("37.02"))
        self.assertEqual(result["total_account_value"], Decimal("20037.02"))

    def test_holdings_are_sorted_by_symbol_and_use_current_prices(self):
        zebra = self.make_stock("ZZZ", "10.00")
        alpha = self.make_stock("AAA", "20.00")
        Stock.objects.filter(pk=alpha.pk).update(
            current_price=Decimal("21.25")
        )
        Holding.objects.create(
            portfolio=self.portfolio, stock=zebra, quantity=2
        )
        Holding.objects.create(
            portfolio=self.portfolio, stock=alpha, quantity=4
        )

        result = get_portfolio_summary(self.user)

        self.assertEqual(
            [position["symbol"] for position in result["holdings"]],
            ["AAA", "ZZZ"],
        )
        self.assertEqual(result["holdings_value"], Decimal("105.00"))
        for field in (
            "cash_balance",
            "reserved_cash",
            "available_cash",
            "holdings_value",
            "total_account_value",
        ):
            self.assertIsInstance(result[field], Decimal)

    def test_missing_portfolio_returns_none_balances_without_creating_one(self):
        result = get_portfolio_summary(self.other_user)

        self.assertFalse(result["has_portfolio"])
        self.assertEqual(result["holdings"], [])
        for field in (
            "cash_balance",
            "reserved_cash",
            "available_cash",
            "holdings_value",
            "total_account_value",
        ):
            self.assertIsNone(result[field])
        self.assertFalse(
            Portfolio.objects.filter(user=self.other_user).exists()
        )

    def test_summary_does_not_change_balances_prices_or_execute_pending_order(self):
        from trading.models import CashTransaction, Order
        from market.models import PriceHistory, StockDailyStatistic

        stock = self.make_stock("READ", "100.00")
        holding = Holding.objects.create(
            portfolio=self.portfolio,
            stock=stock,
            quantity=50,
            reserved_quantity=10,
        )
        order = Order.objects.create(
            portfolio=self.portfolio,
            stock=stock,
            side=Order.Side.SELL,
            status=Order.Status.PENDING,
            quantity=10,
            submission_price=Decimal("100.00"),
            reserved_shares=10,
        )
        portfolio_before = (
            self.portfolio.cash_balance,
            self.portfolio.reserved_cash,
            self.portfolio.updated_at,
        )
        counts_before = (
            CashTransaction.objects.count(),
            PriceHistory.objects.count(),
            StockDailyStatistic.objects.count(),
        )

        get_portfolio_summary(self.user)
        get_portfolio_summary(self.user)

        self.portfolio.refresh_from_db()
        holding.refresh_from_db()
        stock.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(
            (
                self.portfolio.cash_balance,
                self.portfolio.reserved_cash,
                self.portfolio.updated_at,
            ),
            portfolio_before,
        )
        self.assertEqual(holding.quantity, 50)
        self.assertEqual(holding.reserved_quantity, 10)
        self.assertEqual(stock.current_price, Decimal("100.00"))
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.reserved_shares, 10)
        self.assertEqual(
            (
                CashTransaction.objects.count(),
                PriceHistory.objects.count(),
                StockDailyStatistic.objects.count(),
            ),
            counts_before,
        )