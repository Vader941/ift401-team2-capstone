from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from market.models import Stock
from trading.models import Holding, Portfolio
from trading.queries import get_portfolio_summary
from trading.models import CashTransaction, Order
from trading.queries import get_account_history

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
    def test_known_basis_exposes_unrealized_performance(self):
        stock = self.make_stock("GAIN", "20.00")
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=stock,
            quantity=15,
            reserved_quantity=5,
            cost_basis=Decimal("225.00"),
        )

        result = get_portfolio_summary(self.user)
        position = result["holdings"][0]

        self.assertEqual(position["cost_basis"], Decimal("225.00"))
        self.assertEqual(position["average_cost"], Decimal("15.00"))
        self.assertEqual(position["position_value"], Decimal("300.00"))
        self.assertEqual(
            position["unrealized_gain_loss"], Decimal("75.00")
        )
        self.assertEqual(
            position["unrealized_gain_loss_percent"],
            Decimal("75") / Decimal("225") * Decimal("100"),
        )
        self.assertFalse(result["has_unknown_cost_basis"])
        self.assertEqual(
            result["unrealized_gain_loss"], Decimal("75.00")
        )

    def test_unknown_basis_withholds_complete_unrealized_total(self):
        known = self.make_stock("KNOWN", "10.00")
        unknown = self.make_stock("UNKNOWN", "20.00")
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=known,
            quantity=2,
            cost_basis=Decimal("15.00"),
        )
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=unknown,
            quantity=3,
            cost_basis=None,
        )

        result = get_portfolio_summary(self.user)
        positions = {
            item["symbol"]: item for item in result["holdings"]
        }

        self.assertTrue(result["has_unknown_cost_basis"])
        self.assertIsNone(result["unrealized_gain_loss"])
        self.assertEqual(
            positions["KNOWN"]["unrealized_gain_loss"], Decimal("5.00")
        )
        for field in (
            "cost_basis",
            "average_cost",
            "unrealized_gain_loss",
            "unrealized_gain_loss_percent",
        ):
            self.assertIsNone(positions["UNKNOWN"][field])
        self.assertEqual(result["holdings_value"], Decimal("80.00"))

    def test_zero_basis_allows_dollar_gain_without_percentage(self):
        stock = self.make_stock("ZERO", "10.00")
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=stock,
            quantity=2,
            cost_basis=Decimal("0.00"),
        )

        result = get_portfolio_summary(self.user)
        position = result["holdings"][0]

        self.assertEqual(position["average_cost"], Decimal("0.00"))
        self.assertEqual(
            position["unrealized_gain_loss"], Decimal("20.00")
        )
        self.assertIsNone(position["unrealized_gain_loss_percent"])
        self.assertFalse(result["has_unknown_cost_basis"])

class AccountHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="history_owner")
        self.other_user = User.objects.create_user(username="history_other")
        self.portfolio = Portfolio.objects.create(user=self.user)
        self.other_portfolio = Portfolio.objects.create(
            user=self.other_user
        )
        self.stock = Stock.objects.create(
            symbol="HIST",
            company_name="History Company",
            initial_price=Decimal("100.00"),
            current_price=Decimal("100.00"),
        )
        self.at = timezone.now()

    def make_cash(
        self,
        event_type,
        amount,
        *,
        portfolio=None,
        order=None,
        at=None,
    ):
        entry = CashTransaction.objects.create(
            portfolio=(
                self.portfolio if portfolio is None else portfolio
            ),
            order=order,
            transaction_type=event_type,
            amount=Decimal(amount),
            balance_after=Decimal("25000.00"),
            description=f"{event_type} example",
        )
        CashTransaction.objects.filter(pk=entry.pk).update(
            created_at=self.at if at is None else at
        )
        entry.refresh_from_db()
        return entry

    def make_order(self, *, cancelled=False, portfolio=None, at=None):
        return Order.objects.create(
            portfolio=(
                self.portfolio if portfolio is None else portfolio
            ),
            stock=self.stock,
            side=Order.Side.BUY,
            status=(
                Order.Status.CANCELLED
                if cancelled
                else Order.Status.EXECUTED
            ),
            quantity=2,
            submission_price=Decimal("100.00"),
            execution_price=(
                None if cancelled else Decimal("101.25")
            ),
            executed_at=None if cancelled else self.at,
            cancelled_at=(
                (self.at if at is None else at)
                if cancelled else None
            ),
            cancellation_reason=(
                "Cancelled by customer." if cancelled else ""
            ),
        )

    def test_cash_events_preserve_values_and_original_timestamps(self):
        examples = [
            ("INITIAL_BALANCE", "25000.00"),
            ("DEPOSIT", "500.00"),
            ("WITHDRAWAL", "-100.00"),
        ]
        entries = [
            self.make_cash(
                event_type,
                amount,
                at=self.at + timedelta(seconds=index),
            )
            for index, (event_type, amount) in enumerate(examples)
        ]

        result = get_account_history(self.user)

        self.assertEqual(result.paginator.count, 3)
        by_id = {event["event_id"]: event for event in result}
        for entry in entries:
            event = by_id[f"cash:{entry.pk}"]
            self.assertEqual(event["event_type"], entry.transaction_type)
            self.assertEqual(event["occurred_at"], entry.created_at)
            self.assertEqual(event["amount"], entry.amount)
            self.assertEqual(event["balance_after"], entry.balance_after)
            self.assertEqual(event["description"], entry.description)
            for field in (
                "order_id", "symbol", "quantity", "execution_price"
            ):
                self.assertIsNone(event[field])

    def test_executed_trades_appear_once_through_cash_records(self):
        buy = self.make_order()
        sell = self.make_order()
        sell.side = Order.Side.SELL
        sell.save(update_fields=["side"])

        purchase = self.make_cash("PURCHASE", "-202.50", order=buy)
        sale = self.make_cash("SALE", "202.50", order=sell)

        result = get_account_history(self.user)

        self.assertEqual(result.paginator.count, 2)
        by_id = {event["event_id"]: event for event in result}
        for entry, order in ((purchase, buy), (sale, sell)):
            event = by_id[f"cash:{entry.pk}"]
            self.assertEqual(event["event_type"], entry.transaction_type)
            self.assertEqual(event["order_id"], order.pk)
            self.assertEqual(event["symbol"], "HIST")
            self.assertEqual(event["quantity"], 2)
            self.assertEqual(
                event["execution_price"], Decimal("101.25")
            )
            self.assertEqual(event["amount"], entry.amount)

    def test_cancellation_preserves_timestamp_without_cash_effects(self):
        order = self.make_order(
            cancelled=True,
            at=self.at + timedelta(minutes=5),
        )

        result = get_account_history(self.user)

        self.assertEqual(result.paginator.count, 1)
        event = result[0]
        self.assertEqual(
            event["event_id"], f"cancelled_order:{order.pk}"
        )
        self.assertEqual(event["event_type"], "CANCELLATION")
        self.assertEqual(event["occurred_at"], order.cancelled_at)
        self.assertEqual(event["order_id"], order.pk)
        self.assertEqual(event["symbol"], "HIST")
        self.assertEqual(event["quantity"], 2)
        self.assertEqual(
            event["description"], "Cancelled by customer."
        )
        self.assertIsNone(event["amount"])
        self.assertIsNone(event["balance_after"])
        self.assertIsNone(event["execution_price"])

    def test_other_accounts_and_pending_orders_are_excluded(self):
        own_entry = self.make_cash("DEPOSIT", "100.00")
        self.make_cash(
            "DEPOSIT", "500.00", portfolio=self.other_portfolio
        )
        self.make_order(
            cancelled=True, portfolio=self.other_portfolio
        )
        Order.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            side=Order.Side.BUY,
            status=Order.Status.PENDING,
            quantity=1,
            submission_price=Decimal("100.00"),
            reserved_cash=Decimal("100.00"),
        )

        result = get_account_history(self.user)

        self.assertEqual(
            [event["event_id"] for event in result],
            [f"cash:{own_entry.pk}"],
        )

    def test_ordering_and_pagination_are_stable_for_tied_events(self):
        older = self.make_cash(
            "DEPOSIT", "10.00",
            at=self.at - timedelta(minutes=1),
        )
        first = self.make_cash("DEPOSIT", "20.00")
        second = self.make_cash("DEPOSIT", "30.00")
        cancelled = self.make_order(cancelled=True)
        expected = [
            f"cash:{second.pk}",
            f"cash:{first.pk}",
            f"cancelled_order:{cancelled.pk}",
            f"cash:{older.pk}",
        ]

        first_page = get_account_history(
            self.user, page=1, per_page=2
        )
        second_page = get_account_history(
            self.user, page=2, per_page=2
        )

        self.assertEqual(
            [event["event_id"] for event in first_page]
            + [event["event_id"] for event in second_page],
            expected,
        )
        self.assertEqual(first_page.paginator.count, 4)
        self.assertEqual(first_page.paginator.num_pages, 2)
        self.assertTrue(first_page.has_next())
        self.assertTrue(second_page.has_previous())
        self.assertEqual(
            [event["event_id"] for event in get_account_history(self.user)],
            expected,
        )
        self.assertEqual(
            get_account_history(self.user, page="invalid", per_page=2).number,
            1,
        )
        self.assertEqual(
            get_account_history(self.user, page=999, per_page=2).number,
            2,
        )
        self.assertTrue(
            all(
                not key.startswith("_")
                for event in first_page
                for key in event
            )
        )

    def test_empty_and_missing_portfolios_return_empty_pages(self):
        User = get_user_model()
        missing = User.objects.create_user(username="history_missing")

        for user in (self.user, missing):
            with self.subTest(user=user.username):
                result = get_account_history(user)
                self.assertEqual(list(result), [])
                self.assertEqual(result.paginator.count, 0)
                self.assertEqual(result.number, 1)

        self.assertFalse(
            Portfolio.objects.filter(user=missing).exists()
        )

    def test_invalid_page_sizes_are_rejected(self):
        for value in (0, -1, True, "25", 2.5, None):
            with self.subTest(per_page=value):
                with self.assertRaisesMessage(
                    ValueError, "per_page must be a positive integer."
                ):
                    get_account_history(self.user, per_page=value)

    def test_missing_cancellation_timestamp_is_not_fabricated(self):
        order = self.make_order(cancelled=True)
        Order.objects.filter(pk=order.pk).update(cancelled_at=None)

        with self.assertRaisesMessage(
            ValueError,
            f"Cancelled order {order.pk} has no cancellation timestamp.",
        ):
            get_account_history(self.user)

    def test_reading_history_does_not_write_to_database(self):
        self.make_cash("DEPOSIT", "100.00")
        self.make_order(cancelled=True)

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            list(get_account_history(self.user))
            list(get_account_history(self.user))

        statements = [
            query["sql"].lstrip().upper()
            for query in captured.captured_queries
        ]
        self.assertTrue(statements)
        self.assertTrue(
            all(statement.startswith("SELECT") for statement in statements),
            statements,
        )