from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Stock


class StockModelTests(TestCase):
    def test_stock_defaults_to_active_and_normalizes_text(self):
        stock = Stock.objects.create(
            symbol="able",
            company_name="  Able Test Company  ",
            current_price=Decimal("100.00"),
        )

        self.assertEqual(stock.symbol, "ABLE")
        self.assertEqual(stock.company_name, "Able Test Company")
        self.assertTrue(stock.is_active)

    def test_stock_price_must_be_at_least_one_cent(self):
        stock = Stock(
            symbol="TEST",
            company_name="Test Company",
            current_price=Decimal("0.00"),
        )

        with self.assertRaises(ValidationError):
            stock.full_clean()

    def test_stock_string_representation(self):
        stock = Stock(
            symbol="ABLE",
            company_name="Able Test Company",
            current_price=Decimal("100.00"),
        )

        self.assertEqual(str(stock), "ABLE - Able Test Company")


class StockViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="marketuser",
            password="temporary-test-password",
        )
        cls.active_stock = Stock.objects.create(
            symbol="ABLE",
            company_name="Able Test Company",
            current_price=Decimal("100.00"),
        )
        cls.inactive_stock = Stock.objects.create(
            symbol="OLD",
            company_name="Inactive Test Company",
            current_price=Decimal("50.00"),
            is_active=False,
        )

    def test_anonymous_user_is_redirected_from_stock_list(self):
        response = self.client.get(reverse("market:stock-list"))

        expected_url = f"{reverse('login')}?next={reverse('market:stock-list')}"
        self.assertRedirects(response, expected_url)

    def test_stock_list_displays_only_active_stocks(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("market:stock-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ABLE")
        self.assertNotContains(response, "Inactive Test Company")

    def test_stock_detail_displays_selected_stock(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "market:stock-detail",
                kwargs={"pk": self.active_stock.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Able Test Company")
        self.assertContains(response, "$100.00")