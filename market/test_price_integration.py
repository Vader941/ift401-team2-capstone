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

    def test_stock_list_updates_and_displays_price(self):
        with (
            patch(
                "market.services.timezone.now",
                return_value=self.open_time,
            ),
            patch(
                "market.services.random.uniform",
                return_value=1,
            ),
        ):
            response = self.client.get(
                reverse("market:stock-list")
            )

        self.stock.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.stock.current_price, Decimal("101.00")
        )
        self.assertContains(response, "$101.00")
        self.assertEqual(
            PriceHistory.objects.filter(stock=self.stock).count(),
            1,
        )

    def test_stock_detail_updates_and_displays_price(self):
        with (
            patch(
                "market.services.timezone.now",
                return_value=self.open_time,
            ),
            patch(
                "market.services.random.uniform",
                return_value=-1,
            ),
        ):
            response = self.client.get(
                reverse(
                    "market:stock-detail",
                    args=[self.stock.pk],
                )
            )

        self.stock.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.stock.current_price, Decimal("99.00")
        )
        self.assertContains(response, "$99.00")