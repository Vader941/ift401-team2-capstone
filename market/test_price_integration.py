from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import PriceHistory, Stock


class MarketPriceIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="marketviewer"
        )
        self.client.force_login(self.user)
        self.stock = Stock.objects.create(
            symbol="TEST",
            company_name="Test Company",
            current_price=Decimal("100.00"),
        )
        self.open_time = datetime(
            2026, 10, 19, 12, 0,
            tzinfo=ZoneInfo("America/New_York"),
        )

    def assert_page_displays_stored_price(self, url):
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
            response = self.client.get(url)

        self.stock.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.stock.current_price, Decimal("100.00")
        )
        self.assertContains(response, "$100.00")
        self.assertFalse(
            PriceHistory.objects.filter(stock=self.stock).exists()
        )
        random_source.assert_not_called()

    def test_stock_list_displays_price_without_changing_it(self):
        self.assert_page_displays_stored_price(
            reverse("market:stock-list")
        )

    def test_stock_detail_displays_price_without_changing_it(self):
        self.assert_page_displays_stored_price(
            reverse(
                "market:stock-detail",
                args=[self.stock.pk],
            )
        )
