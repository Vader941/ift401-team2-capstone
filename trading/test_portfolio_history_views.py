from decimal import Decimal
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from market.models import PriceHistory, Stock, StockDailyStatistic
from trading.models import CashTransaction, Holding, Order, Portfolio


class PortfolioAndHistoryViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="page_owner")
        self.other_user = User.objects.create_user(username="page_other")
        self.portfolio = Portfolio.objects.create(
            user=self.user,
            cash_balance=Decimal("20000.00"),
            reserved_cash=Decimal("1000.00"),
        )
        self.other_portfolio = Portfolio.objects.create(
            user=self.other_user,
            cash_balance=Decimal("90000.00"),
        )
        self.active_stock = Stock.objects.create(
            symbol="LIVE",
            company_name="Live Company",
            initial_price=Decimal("40.00"),
            current_price=Decimal("42.50"),
        )
        self.inactive_stock = Stock.objects.create(
            symbol="OLD",
            company_name="Inactive Company",
            initial_price=Decimal("12.00"),
            current_price=Decimal("13.25"),
            is_active=False,
        )
        self.client.force_login(self.user)

    def test_portfolio_shows_helper_values_and_active_sell_action(self):
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=self.active_stock,
            quantity=5,
            reserved_quantity=2,
        )
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=self.inactive_stock,
            quantity=3,
            reserved_quantity=1,
        )

        response = self.client.get(reverse("trading:portfolio"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "trading/portfolio.html")
        summary = response.context["summary"]
        self.assertEqual(summary["cash_balance"], Decimal("20000.00"))
        self.assertEqual(summary["reserved_cash"], Decimal("1000.00"))
        self.assertEqual(summary["available_cash"], Decimal("19000.00"))
        self.assertEqual(summary["holdings_value"], Decimal("252.25"))
        self.assertEqual(summary["total_account_value"], Decimal("20252.25"))
        self.assertContains(response, "LIVE")
        self.assertContains(response, "OLD")
        self.assertContains(response, "13.25")
        self.assertContains(response, "Basis unavailable")
        self.assertContains(
            response,
            reverse("trading:sell", args=[self.active_stock.pk]),
        )
        self.assertNotContains(
            response,
            reverse("trading:sell", args=[self.inactive_stock.pk]),
        )
        self.assertNotContains(
            response,
            reverse("market:stock-detail", args=[self.inactive_stock.pk]),
        )

    def test_portfolio_ignores_foreign_account_query_parameters(self):
        Holding.objects.create(
            portfolio=self.other_portfolio,
            stock=self.active_stock,
            quantity=99,
        )

        response = self.client.get(
            reverse("trading:portfolio"), {"user": self.other_user.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["holdings"], [])
        self.assertNotContains(response, "90,000.00")
        self.assertNotContains(response, "99 shares")

    @patch("trading.views.get_portfolio_summary")
    def test_portfolio_renders_contract_performance_fields(self, summary_query):
        summary_query.return_value = {
            "has_portfolio": True,
            "cash_balance": Decimal("20000.00"),
            "reserved_cash": Decimal("0.00"),
            "available_cash": Decimal("20000.00"),
            "holdings_value": Decimal("300.00"),
            "total_account_value": Decimal("20300.00"),
            "has_unknown_cost_basis": False,
            "has_unknown_realized_basis": False,
            "realized_gain_loss": Decimal("25.00"),
            "unrealized_gain_loss": Decimal("75.00"),
            "overall_gain_loss": Decimal("100.00"),
            "holdings": [{
                "stock_id": self.active_stock.pk,
                "symbol": "LIVE",
                "company_name": "Live Company",
                "quantity": 15,
                "reserved_quantity": 0,
                "available_quantity": 15,
                "current_price": Decimal("20.00"),
                "position_value": Decimal("300.00"),
                "average_cost": Decimal("15.00"),
                "unrealized_gain_loss": Decimal("75.00"),
                "unrealized_gain_loss_percent": Decimal("33.333333"),
                "is_active": True,
            }],
        }
        response = self.client.get(reverse("trading:portfolio"))
        self.assertContains(response, "$15.00")
        self.assertContains(response, "Gain +$75.00")
        self.assertContains(response, "Gain +33.33%")
        self.assertContains(response, "+$100.00")
        self.assertContains(response, "Realized plus unrealized")

    def test_missing_portfolio_has_clear_empty_state(self):
        missing_user = get_user_model().objects.create_user(
            username="no_portfolio"
        )
        self.client.force_login(missing_user)

        response = self.client.get(reverse("trading:portfolio"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["summary"]["has_portfolio"])
        self.assertContains(response, "No simulated portfolio is linked")
        self.assertFalse(Portfolio.objects.filter(user=missing_user).exists())

    def test_anonymous_users_are_redirected_from_both_pages(self):
        self.client.logout()

        for name in ("trading:portfolio", "trading:account-history"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(
                    response,
                    f"{reverse('login')}?next={reverse(name)}",
                )

    def test_dashboard_links_to_portfolio_history_and_pending_orders(self):
        response = self.client.get(reverse("trading:dashboard"))

        self.assertEqual(response.status_code, 200)
        for name in (
            "trading:portfolio",
            "trading:account-history",
            "trading:pending-orders",
        ):
            self.assertContains(response, reverse(name))

    def test_history_uses_normalized_events_and_eastern_time(self):
        at = timezone.now() - timedelta(hours=2)
        order = Order.objects.create(
            portfolio=self.portfolio,
            stock=self.active_stock,
            side=Order.Side.BUY,
            status=Order.Status.EXECUTED,
            quantity=2,
            submission_price=Decimal("40.00"),
            execution_price=Decimal("42.50"),
            executed_at=at,
        )
        trade = CashTransaction.objects.create(
            portfolio=self.portfolio,
            order=order,
            transaction_type=CashTransaction.TransactionType.PURCHASE,
            amount=Decimal("-85.00"),
            balance_after=Decimal("19915.00"),
            description="Bought 2 shares of LIVE",
        )
        CashTransaction.objects.filter(pk=trade.pk).update(created_at=at)
        cancelled = Order.objects.create(
            portfolio=self.portfolio,
            stock=self.active_stock,
            side=Order.Side.SELL,
            status=Order.Status.CANCELLED,
            quantity=1,
            submission_price=Decimal("42.50"),
            cancelled_at=at + timedelta(minutes=1),
            cancellation_reason="Cancelled by customer.",
        )

        response = self.client.get(reverse("trading:account-history"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "trading/account_history.html")
        self.assertContains(response, "Purchase")
        self.assertContains(response, "Cancellation")
        self.assertContains(response, "Executed")
        self.assertContains(response, "Cancelled")
        self.assertContains(response, "LIVE")
        self.assertContains(response, "2 shares")
        self.assertContains(response, "42.50")
        self.assertContains(response, "ET")
        self.assertContains(response, "—")
        self.assertEqual(response.context["event_timezone_label"], "Eastern Time (ET)")
        self.assertEqual(response.context["history_page"].paginator.count, 2)
        self.assertEqual(cancelled.status, Order.Status.CANCELLED)

    def test_history_is_account_scoped_and_ignores_user_query_parameter(self):
        own = CashTransaction.objects.create(
            portfolio=self.portfolio,
            transaction_type=CashTransaction.TransactionType.DEPOSIT,
            amount=Decimal("100.00"),
            balance_after=Decimal("20100.00"),
        )
        CashTransaction.objects.create(
            portfolio=self.other_portfolio,
            transaction_type=CashTransaction.TransactionType.DEPOSIT,
            amount=Decimal("900.00"),
            balance_after=Decimal("90900.00"),
        )

        response = self.client.get(
            reverse("trading:account-history"),
            {"user": self.other_user.pk},
        )

        self.assertEqual(response.status_code, 200)
        page = response.context["history_page"]
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(page.object_list[0]["event_id"], f"cash:{own.pk}")
        self.assertContains(response, "100.00")
        self.assertNotContains(response, "90,900.00")

    def test_history_pagination_keeps_older_events_accessible(self):
        for index in range(26):
            CashTransaction.objects.create(
                portfolio=self.portfolio,
                transaction_type=CashTransaction.TransactionType.DEPOSIT,
                amount=Decimal("1.00"),
                balance_after=Decimal("20000.00"),
                description=f"Deposit event {index:02d}",
            )

        first = self.client.get(reverse("trading:account-history"))
        second = self.client.get(
            reverse("trading:account-history"), {"page": "2"}
        )
        invalid = self.client.get(
            reverse("trading:account-history"), {"page": "invalid"}
        )

        self.assertEqual(first.context["history_page"].number, 1)
        self.assertTrue(first.context["history_page"].has_next())
        self.assertEqual(second.context["history_page"].number, 2)
        self.assertTrue(second.context["history_page"].has_previous())
        self.assertEqual(len(second.context["history_page"].object_list), 1)
        self.assertContains(first, "?page=2")
        self.assertEqual(invalid.context["history_page"].number, 1)

    def test_history_filters_by_type_and_eastern_date_and_preserves_pagination(self):
        # UTC 03:30 is the prior calendar date in New York during EDT.
        at = datetime(2026, 10, 30, 3, 30, tzinfo=dt_timezone.utc)
        own = CashTransaction.objects.create(
            portfolio=self.portfolio,
            transaction_type=CashTransaction.TransactionType.DEPOSIT,
            amount=Decimal("10.00"), balance_after=Decimal("20010.00"),
        )
        CashTransaction.objects.filter(pk=own.pk).update(created_at=at)
        later = CashTransaction.objects.create(
            portfolio=self.portfolio,
            transaction_type=CashTransaction.TransactionType.WITHDRAWAL,
            amount=Decimal("-5.00"), balance_after=Decimal("20005.00"),
        )
        CashTransaction.objects.filter(pk=later.pk).update(
            created_at=at + timedelta(days=1)
        )

        response = self.client.get(reverse("trading:account-history"), {
            "event_type": "DEPOSIT", "start_date": "2026-10-29", "end_date": "2026-10-29",
        })
        self.assertEqual(response.context["history_page"].paginator.count, 1)
        self.assertContains(response, "Filters active")
        self.assertContains(response, "Deposit")
        self.assertEqual(
            response.context["history_page"].object_list[0]["event_type"],
            CashTransaction.TransactionType.DEPOSIT,
        )
        self.assertContains(response, "Oct 29, 2026")
        self.assertContains(response, "11:30")

    def test_history_invalid_date_range_is_reported(self):
        response = self.client.get(reverse("trading:account-history"), {
            "start_date": "2026-10-31", "end_date": "2026-10-30",
        })
        self.assertContains(response, "Start date must be on or before end date.")
        self.assertEqual(response.context["filter_error"], "Start date must be on or before end date.")
        self.assertContains(response, "Your submitted filters were not applied.")
        self.assertNotContains(response, "No activity matches these filters")

    def test_history_pagination_retains_active_filters(self):
        for index in range(26):
            entry = CashTransaction.objects.create(
                portfolio=self.portfolio,
                transaction_type=CashTransaction.TransactionType.DEPOSIT,
                amount=Decimal("1.00"),
                balance_after=Decimal("20000.00"),
                description=f"Filtered deposit {index}",
            )
            CashTransaction.objects.filter(pk=entry.pk).update(
                created_at=datetime(2026, 10, 29, 16, tzinfo=dt_timezone.utc)
            )
        response = self.client.get(reverse("trading:account-history"), {
            "event_type": "DEPOSIT", "start_date": "2026-10-29", "end_date": "2026-10-29",
        })
        self.assertTrue(response.context["history_page"].has_next())
        self.assertContains(response, "event_type=DEPOSIT&amp;start_date=2026-10-29&amp;end_date=2026-10-29&amp;page=2")

    def test_history_labels_both_sides_of_eastern_dst_fall_back(self):
        for timestamp, description in (
            (datetime(2026, 11, 1, 5, 30, tzinfo=dt_timezone.utc), "Before fallback"),
            (datetime(2026, 11, 1, 6, 30, tzinfo=dt_timezone.utc), "After fallback"),
        ):
            entry = CashTransaction.objects.create(
                portfolio=self.portfolio,
                transaction_type=CashTransaction.TransactionType.DEPOSIT,
                amount=Decimal("1.00"), balance_after=Decimal("20000.00"),
                description=description,
            )
            CashTransaction.objects.filter(pk=entry.pk).update(created_at=timestamp)
        response = self.client.get(reverse("trading:account-history"), {
            "start_date": "2026-11-01", "end_date": "2026-11-01",
        })
        self.assertContains(response, "1:30 a.m. EST")
        self.assertContains(response, "1:30 a.m. EDT")

    def test_empty_history_and_missing_portfolio_states_are_distinct(self):
        empty = self.client.get(reverse("trading:account-history"))
        self.assertContains(empty, "No account activity yet")

        missing_user = get_user_model().objects.create_user(
            username="history_without_portfolio"
        )
        self.client.force_login(missing_user)
        missing = self.client.get(reverse("trading:account-history"))
        self.assertContains(missing, "No simulated portfolio is linked")
        self.assertFalse(missing.context["has_portfolio"])

    def test_filtered_history_has_a_clear_no_match_state(self):
        response = self.client.get(
            reverse("trading:account-history"),
            {"event_type": "SALE"},
        )
        self.assertContains(response, "No activity matches these filters")

    def test_get_requests_do_not_change_account_or_market_data(self):
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=self.active_stock,
            quantity=5,
            reserved_quantity=2,
        )
        Order.objects.create(
            portfolio=self.portfolio,
            stock=self.active_stock,
            side=Order.Side.BUY,
            status=Order.Status.PENDING,
            quantity=1,
            submission_price=Decimal("42.50"),
            reserved_cash=Decimal("42.50"),
        )
        before = (
            self.portfolio.cash_balance,
            self.portfolio.reserved_cash,
            CashTransaction.objects.count(),
            Order.objects.count(),
            PriceHistory.objects.count(),
            StockDailyStatistic.objects.count(),
            self.active_stock.current_price,
        )

        self.client.get(reverse("trading:portfolio"))
        self.client.get(reverse("trading:account-history"))

        self.portfolio.refresh_from_db()
        self.active_stock.refresh_from_db()
        after = (
            self.portfolio.cash_balance,
            self.portfolio.reserved_cash,
            CashTransaction.objects.count(),
            Order.objects.count(),
            PriceHistory.objects.count(),
            StockDailyStatistic.objects.count(),
            self.active_stock.current_price,
        )
        self.assertEqual(after, before)
