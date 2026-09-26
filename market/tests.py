from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from datetime import datetime, timezone as datetime_timezone
from datetime import date, time
from zoneinfo import ZoneInfo
from datetime import timedelta
from unittest.mock import patch

from .services import is_market_open, update_stock_price
from django.db.models import ProtectedError

from .models import Stock, MarketException, PriceHistory


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

class MarketExceptionModelTests(TestCase):
    def test_full_day_closure_is_valid(self):
        exception = MarketException(
            date=date(2026, 10, 5),
            is_closed=True,
        )

        exception.full_clean()
        exception.save()

        self.assertIsNone(exception.opens_at)
        self.assertIsNone(exception.closes_at)

    def test_special_hours_are_valid(self):
        exception = MarketException(
            date=date(2026, 10, 6),
            is_closed=False,
            opens_at=time(10, 0),
            closes_at=time(13, 0),
        )

        exception.full_clean()
        exception.save()

        self.assertEqual(exception.opens_at, time(10, 0))
        self.assertEqual(exception.closes_at, time(13, 0))

    def test_special_hours_require_both_times(self):
        exception = MarketException(
            date=date(2026, 10, 7),
            is_closed=False,
            opens_at=time(10, 0),
        )

        with self.assertRaises(ValidationError):
            exception.full_clean()

    def test_closing_time_must_follow_opening_time(self):
        exception = MarketException(
            date=date(2026, 10, 8),
            is_closed=False,
            opens_at=time(13, 0),
            closes_at=time(10, 0),
        )

        with self.assertRaises(ValidationError):
            exception.full_clean()

    def test_closure_cannot_also_define_hours(self):
        exception = MarketException(
            date=date(2026, 10, 9),
            is_closed=True,
            opens_at=time(10, 0),
            closes_at=time(13, 0),
        )

        with self.assertRaises(ValidationError):
            exception.full_clean()

class PriceHistoryModelTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(
            symbol="HIST",
            company_name="History Test Company",
            current_price=Decimal("101.00"),
        )

    def test_history_is_available_from_stock_newest_first(self):
        earlier = PriceHistory.objects.create(
            stock=self.stock,
            previous_price=Decimal("99.00"),
            new_price=Decimal("100.00"),
            percentage_change=Decimal("1.0101"),
            effective_at=datetime(
                2026, 10, 1, 14, 0, tzinfo=datetime_timezone.utc
            ),
        )
        later = PriceHistory.objects.create(
            stock=self.stock,
            previous_price=Decimal("100.00"),
            new_price=Decimal("101.00"),
            percentage_change=Decimal("1.0000"),
            effective_at=datetime(
                2026, 10, 1, 14, 1, tzinfo=datetime_timezone.utc
            ),
        )

        self.assertEqual(
            list(self.stock.price_history.all()),
            [later, earlier],
        )

    def test_stock_with_history_cannot_be_deleted(self):
        PriceHistory.objects.create(
            stock=self.stock,
            previous_price=Decimal("100.00"),
            new_price=Decimal("101.00"),
            percentage_change=Decimal("1.0000"),
        )

        with self.assertRaises(ProtectedError):
            self.stock.delete()

    def test_history_rejects_price_below_one_cent(self):
        history = PriceHistory(
            stock=self.stock,
            previous_price=Decimal("0.00"),
            new_price=Decimal("0.01"),
            percentage_change=Decimal("0.0000"),
        )

        with self.assertRaises(ValidationError):
            history.full_clean()

class MarketHoursServiceTests(TestCase):
    def at_new_york_time(self, year, month, day, hour, minute=0):
        return datetime(
            year, month, day, hour, minute,
            tzinfo=ZoneInfo("America/New_York"),
        )

    def test_regular_weekday_boundaries(self):
        self.assertFalse(
            is_market_open(self.at_new_york_time(2026, 10, 1, 9, 29))
        )
        self.assertTrue(
            is_market_open(self.at_new_york_time(2026, 10, 1, 9, 30))
        )
        self.assertTrue(
            is_market_open(self.at_new_york_time(2026, 10, 1, 15, 59))
        )
        self.assertFalse(
            is_market_open(self.at_new_york_time(2026, 10, 1, 16, 0))
        )

    def test_weekend_is_closed_even_with_special_hours_record(self):
        MarketException.objects.create(
            date=date(2026, 10, 3),
            is_closed=False,
            opens_at=time(10, 0),
            closes_at=time(13, 0),
        )

        self.assertFalse(
            is_market_open(self.at_new_york_time(2026, 10, 3, 11, 0))
        )

    def test_full_day_closure_overrides_regular_hours(self):
        MarketException.objects.create(
            date=date(2026, 10, 1),
            is_closed=True,
        )

        self.assertFalse(
            is_market_open(self.at_new_york_time(2026, 10, 1, 12, 0))
        )

    def test_special_hours_override_regular_hours(self):
        MarketException.objects.create(
            date=date(2026, 10, 1),
            is_closed=False,
            opens_at=time(10, 0),
            closes_at=time(13, 0),
        )

        self.assertFalse(
            is_market_open(self.at_new_york_time(2026, 10, 1, 9, 30))
        )
        self.assertTrue(
            is_market_open(self.at_new_york_time(2026, 10, 1, 10, 0))
        )
        self.assertFalse(
            is_market_open(self.at_new_york_time(2026, 10, 1, 13, 0))
        )

    def test_utc_input_converts_across_daylight_saving(self):
        # March 9 is in daylight time: 13:30 UTC is 9:30 a.m. EDT.
        self.assertTrue(
            is_market_open(
                datetime(2026, 3, 9, 13, 30, tzinfo=datetime_timezone.utc)
            )
        )
        # November 2 is in standard time: 14:30 UTC is 9:30 a.m. EST.
        self.assertTrue(
            is_market_open(
                datetime(2026, 11, 2, 14, 30, tzinfo=datetime_timezone.utc)
            )
        )

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            is_market_open(datetime(2026, 10, 1, 12, 0))

class PriceUpdateServiceTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(
            symbol="SIM",
            company_name="Simulation Test Company",
            current_price=Decimal("100.00"),
        )
        self.open_time = datetime(
            2026, 10, 1, 10, 0,
            tzinfo=ZoneInfo("America/New_York"),
        )

    def test_closed_market_does_not_update_price_or_history(self):
        closed_time = self.open_time.replace(hour=17)

        price = update_stock_price(
            self.stock,
            at=closed_time,
            random_source=lambda low, high: Decimal("1"),
        )

        self.stock.refresh_from_db()
        self.assertEqual(price, Decimal("100.00"))
        self.assertEqual(self.stock.current_price, Decimal("100.00"))
        self.assertEqual(PriceHistory.objects.count(), 0)

    def test_accepted_update_changes_stock_and_creates_history(self):
        price = update_stock_price(
            self.stock,
            at=self.open_time,
            random_source=lambda low, high: Decimal("1"),
        )

        self.stock.refresh_from_db()
        history = self.stock.price_history.get()
        self.assertEqual(price, Decimal("101.00"))
        self.assertEqual(self.stock.current_price, Decimal("101.00"))
        self.assertEqual(history.previous_price, Decimal("100.00"))
        self.assertEqual(history.new_price, Decimal("101.00"))
        self.assertEqual(history.percentage_change, Decimal("1.0000"))
        self.assertEqual(history.effective_at, self.open_time)

    def test_second_update_waits_for_sixty_seconds(self):
        update_stock_price(
            self.stock,
            at=self.open_time,
            random_source=lambda low, high: Decimal("1"),
        )

        too_soon = update_stock_price(
            self.stock,
            at=self.open_time + timedelta(seconds=59),
            random_source=lambda low, high: Decimal("-1"),
        )
        self.assertEqual(too_soon, Decimal("101.00"))
        self.assertEqual(PriceHistory.objects.count(), 1)

        eligible = update_stock_price(
            self.stock,
            at=self.open_time + timedelta(seconds=60),
            random_source=lambda low, high: Decimal("-1"),
        )
        self.assertEqual(eligible, Decimal("99.99"))
        self.assertEqual(PriceHistory.objects.count(), 2)

    def test_out_of_range_random_value_is_rejected(self):
        with self.assertRaises(ValueError):
            update_stock_price(
                self.stock,
                at=self.open_time,
                random_source=lambda low, high: Decimal("1.01"),
            )

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.current_price, Decimal("100.00"))
        self.assertEqual(PriceHistory.objects.count(), 0)

    def test_rounding_cannot_exceed_percentage_bound(self):
        self.stock.current_price = Decimal("0.50")
        self.stock.save(update_fields=["current_price", "updated_at"])

        price = update_stock_price(
            self.stock,
            at=self.open_time,
            random_source=lambda low, high: Decimal("1"),
        )

        self.assertEqual(price, Decimal("0.50"))
        self.assertEqual(PriceHistory.objects.count(), 0)

    def test_price_never_falls_below_one_cent(self):
        self.stock.current_price = Decimal("0.01")
        self.stock.save(update_fields=["current_price", "updated_at"])

        price = update_stock_price(
            self.stock,
            at=self.open_time,
            random_source=lambda low, high: Decimal("-1"),
        )

        self.assertEqual(price, Decimal("0.01"))
        self.assertEqual(PriceHistory.objects.count(), 0)

    def test_history_failure_rolls_back_stock_price(self):
        with patch(
            "market.services.PriceHistory.objects.create",
            side_effect=RuntimeError("simulated history failure"),
        ):
            with self.assertRaises(RuntimeError):
                update_stock_price(
                    self.stock,
                    at=self.open_time,
                    random_source=lambda low, high: Decimal("1"),
                )

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.current_price, Decimal("100.00"))
        self.assertEqual(PriceHistory.objects.count(), 0)

    @patch("market.services.random.uniform", return_value=0.5)
    def test_default_random_source_updates_price(self, mock_uniform):
        price = update_stock_price(self.stock, at=self.open_time)

        self.assertEqual(price, Decimal("100.50"))
        self.assertEqual(PriceHistory.objects.count(), 1)
        mock_uniform.assert_called_once_with(-1.0, 1.0)