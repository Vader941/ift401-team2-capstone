from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from . import services
from .models import PriceHistory, Stock, StockDailyStatistic
from .services import (
    get_stock_statistics,
    market_date_for,
    update_stock_price,
)

NY = ZoneInfo("America/New_York")
# Tuesday and Wednesday, regular market hours.
TUESDAY_OPEN = datetime(2026, 10, 20, 10, 0, tzinfo=NY)
WEDNESDAY_OPEN = datetime(2026, 10, 21, 10, 0, tzinfo=NY)
TUESDAY_EVENING = datetime(2026, 10, 20, 20, 0, tzinfo=NY)


def change_of(percent):
    """A random source that always proposes the given percentage."""
    return lambda low, high: Decimal(percent)


class StockDataModelTests(TestCase):
    def test_initial_price_defaults_from_current_price(self):
        stock = Stock.objects.create(
            symbol="ABC", company_name="ABC Co", current_price=Decimal("12.50")
        )
        self.assertEqual(stock.initial_price, Decimal("12.50"))
        self.assertEqual(stock.share_volume, 1_000_000)

    def test_current_price_starts_at_initial_price(self):
        stock = Stock.objects.create(
            symbol="ABC",
            company_name="ABC Co",
            initial_price=Decimal("8.00"),
            share_volume=250,
        )
        self.assertEqual(stock.current_price, Decimal("8.00"))

    def test_market_capitalization_uses_current_price_and_decimal(self):
        stock = Stock.objects.create(
            symbol="ABC",
            company_name="ABC Co",
            initial_price=Decimal("10.00"),
            current_price=Decimal("10.15"),
            share_volume=3_000_000,
        )
        self.assertEqual(stock.market_capitalization, Decimal("30450000.00"))
        self.assertIsInstance(stock.market_capitalization, Decimal)

    def test_database_rejects_zero_volume(self):
        with self.assertRaises(IntegrityError):
            Stock.objects.create(
                symbol="ABC",
                company_name="ABC Co",
                current_price=Decimal("1.00"),
                share_volume=0,
            )

    def test_database_rejects_initial_price_below_one_cent(self):
        with self.assertRaises(IntegrityError):
            Stock.objects.create(
                symbol="ABC",
                company_name="ABC Co",
                initial_price=Decimal("0.00"),
                current_price=Decimal("1.00"),
            )


class StockAdminDataTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password=None
        )
        self.client.force_login(self.admin)
        self.add_url = reverse("admin:market_stock_add")
        self.stock = Stock.objects.create(
            symbol="OLD",
            company_name="Old Co",
            initial_price=Decimal("5.00"),
            current_price=Decimal("6.25"),
            share_volume=1000,
        )

    def data(self, **overrides):
        data = {
            "symbol": "NEW",
            "company_name": "New Co",
            "initial_price": "15.00",
            "share_volume": "2000000",
            "is_active": "on",
            "_save": "Save",
        }
        data.update(overrides)
        return data

    def test_creation_requires_explicit_share_volume(self):
        data = self.data()
        del data["share_volume"]
        response = self.client.post(self.add_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("share_volume", response.context["adminform"].form.errors)
        self.assertFalse(Stock.objects.filter(symbol="NEW").exists())

    def test_creation_rejects_invalid_volumes(self):
        for volume in ("0", "-5", "1.5", "abc"):
            with self.subTest(volume=volume):
                response = self.client.post(
                    self.add_url, self.data(share_volume=volume)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    "share_volume", response.context["adminform"].form.errors
                )
        self.assertFalse(Stock.objects.filter(symbol="NEW").exists())

    def test_creation_sets_current_price_from_initial_price(self):
        response = self.client.post(self.add_url, self.data())
        self.assertEqual(response.status_code, 302)
        stock = Stock.objects.get(symbol="NEW")
        self.assertEqual(stock.initial_price, Decimal("15.00"))
        self.assertEqual(stock.current_price, Decimal("15.00"))
        self.assertEqual(stock.share_volume, 2_000_000)

    def test_ordinary_edit_cannot_change_prices_volume_or_symbol(self):
        url = reverse("admin:market_stock_change", args=[self.stock.pk])
        response = self.client.post(
            url,
            {
                "symbol": "HACK",
                "company_name": "Renamed Co",
                "initial_price": "999.00",
                "current_price": "999.00",
                "share_volume": "1",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.company_name, "Renamed Co")
        self.assertFalse(self.stock.is_active)
        self.assertEqual(self.stock.symbol, "OLD")
        self.assertEqual(self.stock.initial_price, Decimal("5.00"))
        self.assertEqual(self.stock.current_price, Decimal("6.25"))
        self.assertEqual(self.stock.share_volume, 1000)

    def test_change_page_shows_market_capitalization(self):
        url = reverse("admin:market_stock_change", args=[self.stock.pk])
        response = self.client.get(url)
        self.assertContains(response, "$6,250.00")

    def test_daily_statistics_are_read_only_in_admin(self):
        response = self.client.get(
            reverse("admin:market_stockdailystatistic_add")
        )
        self.assertEqual(response.status_code, 403)


class DailyStatisticsTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(
            symbol="TEST",
            company_name="Test Co",
            initial_price=Decimal("10.00"),
            share_volume=1_000_000,
        )

    def update(self, at, percent):
        return update_stock_price(
            self.stock, at=at, random_source=change_of(percent)
        )

    def test_market_date_uses_market_time_zone(self):
        # 02:00 UTC on Oct 21 is still Oct 20 in New York.
        utc = datetime(2026, 10, 21, 2, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(str(market_date_for(utc)), "2026-10-20")

    def test_before_any_day_initial_price_is_the_reference(self):
        stats = get_stock_statistics(self.stock, at=TUESDAY_OPEN)
        self.assertEqual(stats["opening_price"], Decimal("10.00"))
        self.assertEqual(stats["high_price"], Decimal("10.00"))
        self.assertEqual(stats["low_price"], Decimal("10.00"))
        self.assertEqual(stats["price_change"], Decimal("0.00"))
        self.assertEqual(stats["price_change_percent"], Decimal("0.00"))
        self.assertIsNone(stats["statistics_date"])

    def test_opening_is_price_before_first_update_of_day(self):
        self.update(TUESDAY_OPEN, "1.00")  # 10.00 -> 10.10
        daily = StockDailyStatistic.objects.get(stock=self.stock)
        self.assertEqual(str(daily.market_date), "2026-10-20")
        self.assertEqual(daily.opening_price, Decimal("10.00"))
        self.assertEqual(daily.high_price, Decimal("10.10"))
        self.assertEqual(daily.low_price, Decimal("10.00"))

        # The first movement of the day counts toward the daily change.
        self.stock.refresh_from_db()
        stats = get_stock_statistics(self.stock, at=TUESDAY_OPEN)
        self.assertEqual(stats["price_change"], Decimal("0.10"))
        self.assertEqual(stats["price_change_percent"], Decimal("1.00"))

    def test_unchanged_first_update_still_establishes_opening(self):
        self.update(TUESDAY_OPEN, "0.00")
        self.assertFalse(PriceHistory.objects.exists())
        daily = StockDailyStatistic.objects.get(stock=self.stock)
        self.assertEqual(daily.opening_price, Decimal("10.00"))

    def test_update_within_interval_still_establishes_opening(self):
        PriceHistory.objects.create(
            stock=self.stock,
            previous_price=Decimal("9.90"),
            new_price=Decimal("10.00"),
            percentage_change=Decimal("1.0101"),
            effective_at=TUESDAY_OPEN - timedelta(seconds=10),
        )
        self.update(TUESDAY_OPEN, "1.00")
        self.assertEqual(PriceHistory.objects.count(), 1)
        daily = StockDailyStatistic.objects.get(stock=self.stock)
        self.assertEqual(daily.opening_price, Decimal("10.00"))

    def test_later_updates_move_high_and_low_but_not_opening(self):
        self.update(TUESDAY_OPEN, "1.00")  # opening 10.00 -> 10.10
        self.update(TUESDAY_OPEN + timedelta(minutes=1), "1.00")  # 10.20
        self.update(TUESDAY_OPEN + timedelta(minutes=2), "-1.00")  # 10.10
        self.update(TUESDAY_OPEN + timedelta(minutes=3), "-1.00")  # 10.00
        self.update(TUESDAY_OPEN + timedelta(minutes=4), "-1.00")  # 9.90

        daily = StockDailyStatistic.objects.get(stock=self.stock)
        self.assertEqual(daily.opening_price, Decimal("10.00"))
        self.assertEqual(daily.high_price, Decimal("10.20"))
        self.assertEqual(daily.low_price, Decimal("9.90"))

        self.stock.refresh_from_db()
        stats = get_stock_statistics(
            self.stock, at=TUESDAY_OPEN + timedelta(minutes=5)
        )
        self.assertEqual(stats["current_price"], Decimal("9.90"))
        self.assertEqual(stats["price_change"], Decimal("-0.10"))
        self.assertEqual(stats["price_change_percent"], Decimal("-1.00"))

    def test_closed_market_keeps_previous_day_values(self):
        self.update(TUESDAY_OPEN, "1.00")
        self.update(TUESDAY_EVENING, "1.00")  # market closed: no change

        self.assertEqual(StockDailyStatistic.objects.count(), 1)
        self.stock.refresh_from_db()
        stats = get_stock_statistics(self.stock, at=TUESDAY_EVENING)
        self.assertEqual(str(stats["statistics_date"]), "2026-10-20")
        self.assertEqual(stats["opening_price"], Decimal("10.00"))
        self.assertEqual(stats["current_price"], Decimal("10.10"))

    def test_new_market_day_starts_new_statistics(self):
        self.update(TUESDAY_OPEN, "1.00")  # Tue opening 10.00 -> 10.10
        self.update(TUESDAY_OPEN + timedelta(minutes=1), "1.00")  # 10.20
        self.update(WEDNESDAY_OPEN, "-1.00")  # Wed opening 10.20 -> 10.10

        wednesday = StockDailyStatistic.objects.get(
            stock=self.stock, market_date="2026-10-21"
        )
        self.assertEqual(wednesday.opening_price, Decimal("10.20"))
        self.assertEqual(wednesday.high_price, Decimal("10.20"))
        self.assertEqual(wednesday.low_price, Decimal("10.10"))

        tuesday = StockDailyStatistic.objects.get(
            stock=self.stock, market_date="2026-10-20"
        )
        self.assertEqual(tuesday.high_price, Decimal("10.20"))

    def test_statistics_use_stored_values_and_decimal(self):
        self.update(TUESDAY_OPEN, "1.00")
        self.stock.refresh_from_db()
        stats = self.stock.statistics
        self.assertEqual(stats["market_capitalization"], Decimal("10100000.00"))
        for key in (
            "initial_price",
            "current_price",
            "market_capitalization",
            "opening_price",
            "high_price",
            "low_price",
            "price_change",
            "price_change_percent",
        ):
            self.assertIsInstance(stats[key], Decimal, key)

    def test_history_failure_rolls_back_daily_statistics(self):
        with mock.patch.object(
            services.PriceHistory.objects,
            "create",
            side_effect=IntegrityError("boom"),
        ):
            with self.assertRaises(IntegrityError):
                self.update(TUESDAY_OPEN, "1.00")
        self.assertFalse(StockDailyStatistic.objects.exists())
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.current_price, Decimal("10.00"))


class StockDataMigrationTests(TransactionTestCase):
    """Existing stocks survive the migration with backfilled values."""

    before = [("market", "0003_pricehistory")]
    after = [("market", "0004_stock_data_statistics")]

    def test_existing_stocks_are_backfilled_not_recreated(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old_apps = executor.loader.project_state(self.before).apps
        OldStock = old_apps.get_model("market", "Stock")
        old = OldStock.objects.create(
            symbol="KEEP",
            company_name="Keep Co",
            current_price=Decimal("42.17"),
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new_apps = executor.loader.project_state(self.after).apps
        NewStock = new_apps.get_model("market", "Stock")

        stock = NewStock.objects.get(pk=old.pk)
        self.assertEqual(stock.symbol, "KEEP")
        self.assertEqual(stock.current_price, Decimal("42.17"))
        self.assertEqual(stock.initial_price, Decimal("42.17"))
        self.assertEqual(stock.share_volume, 1_000_000)

        # Return to the latest schema for the rest of the test run.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
