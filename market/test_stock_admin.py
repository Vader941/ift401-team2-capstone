from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from trading.models import CashTransaction, Holding, Order, Portfolio

from .models import PriceHistory, Stock


User = get_user_model()


class StockAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="stockadmin",
            email="stockadmin@example.com",
            password=None,
        )
        self.customer = User.objects.create_user(username="customer")
        self.staff = User.objects.create_user(
            username="staff",
            is_staff=True,
        )
        self.stock = Stock.objects.create(
            symbol="TEST",
            company_name="Test Company",
            current_price=Decimal("10.00"),
        )
        self.add_url = reverse("admin:market_stock_add")
        self.change_url = reverse(
            "admin:market_stock_change", args=[self.stock.pk]
        )

    def stock_data(self, **overrides):
        data = {
            "symbol": "NEW",
            "company_name": "New Company",
            "initial_price": "20.00",
            "share_volume": "5000000",
            "is_active": "on",
            "_save": "Save",
        }
        data.update(overrides)
        return data

    def test_anonymous_user_cannot_create_stock(self):
        response = self.client.post(self.add_url, self.stock_data())

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
        self.assertEqual(Stock.objects.count(), 1)

    def test_customer_cannot_create_or_edit_stock(self):
        self.client.force_login(self.customer)

        for url in (self.add_url, self.change_url):
            with self.subTest(url=url):
                response = self.client.post(url, self.stock_data())
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("admin:login"), response.url)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.symbol, "TEST")
        self.assertEqual(Stock.objects.count(), 1)

    def test_staff_without_permissions_cannot_create_or_edit_stock(self):
        self.client.force_login(self.staff)

        for url in (self.add_url, self.change_url):
            with self.subTest(url=url):
                response = self.client.post(url, self.stock_data())
                self.assertEqual(response.status_code, 403)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.symbol, "TEST")
        self.assertEqual(Stock.objects.count(), 1)

    def test_authorized_admin_can_create_stock(self):
        self.client.force_login(self.admin)

        response = self.client.post(self.add_url, self.stock_data())

        self.assertEqual(response.status_code, 302)
        stock = Stock.objects.get(symbol="NEW")
        self.assertEqual(stock.company_name, "New Company")
        self.assertEqual(stock.initial_price, Decimal("20.00"))
        self.assertEqual(stock.current_price, Decimal("20.00"))
        self.assertEqual(stock.share_volume, 5_000_000)
        self.assertTrue(stock.is_active)

    def test_duplicate_symbol_is_rejected(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.add_url, self.stock_data(symbol="TEST")
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "symbol", response.context["adminform"].form.errors
        )
        self.assertEqual(Stock.objects.count(), 1)

    def test_invalid_prices_are_rejected(self):
        self.client.force_login(self.admin)

        for price in ("0", "-1", "abc", "1.234"):
            with self.subTest(price=price):
                response = self.client.post(
                    self.add_url,
                    self.stock_data(initial_price=price),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    "initial_price",
                    response.context["adminform"].form.errors,
                )
                self.assertEqual(Stock.objects.count(), 1)

    def test_invalid_symbol_and_missing_company_are_rejected(self):
        self.client.force_login(self.admin)

        for overrides, field in (
            ({"symbol": "BAD SYMBOL"}, "symbol"),
            ({"company_name": ""}, "company_name"),
        ):
            with self.subTest(field=field):
                response = self.client.post(
                    self.add_url, self.stock_data(**overrides)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    field, response.context["adminform"].form.errors
                )
                self.assertEqual(Stock.objects.count(), 1)

    def test_edit_and_deactivation_preserve_linked_records(self):
        portfolio = Portfolio.objects.create(user=self.customer)
        holding = Holding.objects.create(
            portfolio=portfolio,
            stock=self.stock,
            quantity=4,
        )
        order = Order.objects.create(
            portfolio=portfolio,
            stock=self.stock,
            side=Order.Side.BUY,
            status=Order.Status.EXECUTED,
            quantity=4,
            submission_price=Decimal("10.00"),
            execution_price=Decimal("10.00"),
        )
        entry = CashTransaction.objects.create(
            portfolio=portfolio,
            order=order,
            transaction_type=CashTransaction.TransactionType.PURCHASE,
            amount=Decimal("-40.00"),
            balance_after=Decimal("24960.00"),
        )
        history = PriceHistory.objects.create(
            stock=self.stock,
            previous_price=Decimal("9.00"),
            new_price=Decimal("10.00"),
            percentage_change=Decimal("11.1111"),
        )

        self.client.force_login(self.admin)
        data = self.stock_data(
            symbol="TEST",
            company_name="Updated Company",
        )
        del data["is_active"]

        response = self.client.post(self.change_url, data)

        self.assertEqual(response.status_code, 302)
        self.stock.refresh_from_db()
        holding.refresh_from_db()
        order.refresh_from_db()
        entry.refresh_from_db()
        history.refresh_from_db()

        self.assertEqual(self.stock.company_name, "Updated Company")
        self.assertFalse(self.stock.is_active)
        self.assertEqual(holding.stock_id, self.stock.pk)
        self.assertEqual(holding.quantity, 4)
        self.assertEqual(order.stock_id, self.stock.pk)
        self.assertEqual(order.execution_price, Decimal("10.00"))
        self.assertEqual(entry.order_id, order.pk)
        self.assertEqual(entry.amount, Decimal("-40.00"))
        self.assertEqual(history.stock_id, self.stock.pk)
        self.assertEqual(history.new_price, Decimal("10.00"))