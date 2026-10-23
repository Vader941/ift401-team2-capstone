from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from market.models import PriceHistory, Stock

from .forms import SellOrderForm
from .models import Holding, Order, Portfolio


User = get_user_model()
NEW_YORK = ZoneInfo("America/New_York")


class SellOrderFormTests(TestCase):
    def test_accepts_positive_whole_share_quantity(self):
        form = SellOrderForm({"quantity": "3"})

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["quantity"], 3)

    def test_rejects_zero_negative_decimal_and_overflow_quantities(self):
        for quantity in ("0", "-1", "1.5", "2147483648", ""):
            with self.subTest(quantity=quantity):
                form = SellOrderForm({"quantity": quantity})
                self.assertFalse(form.is_valid())


class CustomerOrderViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="seller",
            password="temporary-test-password",
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
            2026, 10, 19, 12, 0, tzinfo=NEW_YORK
        )
        self.closed_time = datetime(
            2026, 10, 19, 18, 0, tzinfo=NEW_YORK
        )
        self.client.force_login(self.user)

    def make_pending_order(self, *, user=None, side=Order.Side.SELL):
        user = user or self.user
        portfolio = self.portfolio if user == self.user else Portfolio.objects.create(user=user)
        order = Order.objects.create(
            portfolio=portfolio,
            stock=self.stock,
            side=side,
            status=Order.Status.PENDING,
            quantity=2,
            submission_price=Decimal("25.00"),
            reserved_shares=2 if side == Order.Side.SELL else 0,
            reserved_cash=Decimal("50.00") if side == Order.Side.BUY else Decimal("0.00"),
        )
        if side == Order.Side.SELL and portfolio == self.portfolio:
            self.holding.reserved_quantity = 2
            self.holding.save(update_fields=["reserved_quantity"])
        if side == Order.Side.BUY and portfolio == self.portfolio:
            portfolio.reserved_cash = Decimal("50.00")
            portfolio.save(update_fields=["reserved_cash"])
        return order

    def test_anonymous_user_is_redirected_from_sell_pending_and_cancel_pages(self):
        self.client.logout()
        urls = [
            reverse("trading:sell", args=[self.stock.pk]),
            reverse("trading:pending-orders"),
            reverse("trading:cancel-order", args=[1]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_sell_page_shows_available_shares_and_live_estimate_control(self):
        response = self.client.get(
            reverse("trading:sell", args=[self.stock.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["available_shares"], 10)
        self.assertContains(response, "Available shares")
        self.assertContains(response, "id=\"sale-estimate\"")
        self.assertContains(response, "max=\"10\"")

    @patch("market.services.random.uniform", return_value=0)
    @patch("trading.services.is_market_open", return_value=True)
    @patch("trading.services.timezone.now")

    def test_open_market_sell_executes_and_redirects(
        self, service_now, _market_open, _random
    ):
        service_now.return_value = self.open_time
        response = self.client.post(
            reverse("trading:sell", args=[self.stock.pk]),
            {"quantity": "4"},
        )

        self.assertRedirects(
            response,
            reverse("trading:sell", args=[self.stock.pk]),
        )
        order = Order.objects.get(side=Order.Side.SELL)
        self.portfolio.refresh_from_db()
        self.holding.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(self.portfolio.cash_balance, Decimal("1100.00"))
        self.assertEqual(self.holding.quantity, 6)
        self.assertEqual(self.holding.reserved_quantity, 0)

    @patch("market.services.random.uniform", return_value=0)
    @patch("trading.services.is_market_open", return_value=False)
    @patch("trading.services.timezone.now")

    def test_closed_market_sell_creates_pending_order_and_reserves_shares(
        self, service_now, _market_open, _random
    ):
        service_now.return_value = self.closed_time
        response = self.client.post(
            reverse("trading:sell", args=[self.stock.pk]),
            {"quantity": "4"},
        )

        self.assertRedirects(
            response,
            reverse("trading:sell", args=[self.stock.pk]),
        )
        order = Order.objects.get(side=Order.Side.SELL)
        self.holding.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.reserved_shares, 4)
        self.assertEqual(self.holding.quantity, 10)
        self.assertEqual(self.holding.reserved_quantity, 4)

    @patch("trading.services.place_sell_order")

    def test_invalid_sell_input_does_not_call_service(self, place_sell):
        response = self.client.post(
            reverse("trading:sell", args=[self.stock.pk]),
            {"quantity": "1.5"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(place_sell.called)
        self.holding.refresh_from_db()
        self.assertEqual(self.holding.quantity, 10)

    def test_pending_orders_are_owned_and_include_estimated_value(self):
        own_order = self.make_pending_order()
        other_user = User.objects.create_user(username="another-trader")
        other_order = self.make_pending_order(
            user=other_user,
            side=Order.Side.BUY,
        )
        executed = Order.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            side=Order.Side.BUY,
            status=Order.Status.EXECUTED,
            quantity=1,
            submission_price=Decimal("25.00"),
        )

        response = self.client.get(reverse("trading:pending-orders"))

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(
            response.context["orders"], [own_order], transform=lambda order: order
        )
        self.assertContains(response, "$50.00")
        self.assertContains(response, "At submission price")
        self.assertEqual(len(response.context["orders"]), 1)

    def test_pending_orders_shows_an_empty_state(self):
        response = self.client.get(reverse("trading:pending-orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No pending orders")

    def test_cancel_get_is_confirmation_only_and_post_cancels(self):
        order = self.make_pending_order()
        cancel_url = reverse("trading:cancel-order", args=[order.pk])

        confirmation = self.client.get(cancel_url)
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, "Confirm cancellation")
        self.assertContains(confirmation, "csrfmiddlewaretoken")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

        response = self.client.post(cancel_url)
        self.assertRedirects(
            response,
            reverse("trading:pending-orders"),
        )
        order.refresh_from_db()
        self.holding.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.reserved_shares, 0)
        self.assertEqual(self.holding.reserved_quantity, 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_foreign_order_cannot_be_cancelled(self):
        other_user = User.objects.create_user(username="foreign-trader")
        order = self.make_pending_order(user=other_user)
        cancel_url = reverse("trading:cancel-order", args=[order.pk])

        self.assertEqual(self.client.get(cancel_url).status_code, 404)
        response = self.client.post(cancel_url)

        self.assertRedirects(response, reverse("trading:pending-orders"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_cancel_confirmation_is_not_available_for_an_executed_order(self):
        order = Order.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            side=Order.Side.SELL,
            status=Order.Status.EXECUTED,
            quantity=1,
            submission_price=Decimal("25.00"),
            execution_price=Decimal("25.00"),
        )

        response = self.client.get(
            reverse("trading:cancel-order", args=[order.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_cancel_endpoint_rejects_other_http_methods(self):
        order = self.make_pending_order()

        response = self.client.delete(
            reverse("trading:cancel-order", args=[order.pk])
        )

        self.assertEqual(response.status_code, 405)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
    def test_inactive_sell_page_does_not_change_price_or_history(self):
        self.stock.is_active = False
        self.stock.save(update_fields=["is_active"])

        with (
            patch(
                "market.services.timezone.now",
                return_value=self.open_time,
            ),
            patch(
                "market.services.random.uniform",
                return_value=1,
            ) as random_source,
        ):
            response = self.client.get(
                reverse("trading:sell", args=[self.stock.pk])
            )

        self.stock.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This stock is not available for simulated trading.",
        )
        self.assertEqual(
            self.stock.current_price, Decimal("25.00")
        )
        self.assertFalse(
            PriceHistory.objects.filter(stock=self.stock).exists()
        )
        random_source.assert_not_called()

class CancellationCsrfTests(TestCase):
    def test_cancel_post_requires_csrf_token(self):
        user = User.objects.create_user(username="csrf-trader")
        portfolio = Portfolio.objects.create(user=user)
        stock = Stock.objects.create(
            symbol="CSRF",
            company_name="CSRF Test Company",
            current_price=Decimal("10.00"),
        )
        order = Order.objects.create(
            portfolio=portfolio,
            stock=stock,
            side=Order.Side.BUY,
            status=Order.Status.PENDING,
            quantity=1,
            submission_price=Decimal("10.00"),
            reserved_cash=Decimal("10.00"),
        )
        portfolio.reserved_cash = Decimal("10.00")
        portfolio.save(update_fields=["reserved_cash"])

        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.post(
            reverse("trading:cancel-order", args=[order.pk])
        )

        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
