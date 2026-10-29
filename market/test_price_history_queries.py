from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase

from market.models import PriceHistory, Stock
from market.queries import get_stock_price_history
from trading.models import CashTransaction, Order, Portfolio


class StockPriceHistoryQueryTests(TestCase):
    def setUp(self):
        self.stock = self.make_stock("GRAPH")
        self.other_stock = self.make_stock("OTHER")
        self.at = datetime(2026, 10, 29, 16, tzinfo=timezone.utc)

    def make_stock(self, symbol):
        return Stock.objects.create(
            symbol=symbol,
            company_name=f"{symbol} Company",
            initial_price=Decimal("10.00"),
            current_price=Decimal("10.00"),
            is_active=True,
        )

    def observation(self, *, stock=None, at=None, price="10.00"):
        return PriceHistory.objects.create(
            stock=self.stock if stock is None else stock,
            previous_price=Decimal("10.00"),
            new_price=Decimal(price),
            percentage_change=Decimal("0.0000"),
            effective_at=self.at if at is None else at,
        )

    def test_latest_observations_return_in_chronological_order(self):
        self.observation(
            at=self.at - timedelta(minutes=1), price="9.00"
        )
        first = self.observation(price="10.00")
        second = self.observation(price="11.00")
        last = self.observation(
            at=self.at + timedelta(minutes=1), price="12.00"
        )
        self.observation(stock=self.other_stock, price="99.00")

        result = get_stock_price_history(self.stock, limit=3)

        self.assertEqual(
            [point["observation_id"] for point in result["points"]],
            [first.pk, second.pk, last.pk],
        )
        self.assertEqual(
            [point["price"] for point in result["points"]],
            ["10.00", "11.00", "12.00"],
        )
        self.assertEqual(result["stock_id"], self.stock.pk)
        self.assertEqual(result["symbol"], "GRAPH")
        self.assertEqual(result["limit"], 3)
        self.assertEqual(result["last_observed_price"], "12.00")
        self.assertEqual(
            result["data_as_of"], last.effective_at.isoformat()
        )
        self.assertEqual(
            result["data_as_of"], result["points"][-1]["timestamp"]
        )

    def test_empty_history_does_not_invent_current_price_point(self):
        result = get_stock_price_history(self.stock)

        self.assertEqual(result["points"], [])
        self.assertIsNone(result["last_observed_price"])
        self.assertIsNone(result["data_as_of"])
        self.assertIsNone(result["display_data_as_of"])

    def test_eastern_timestamps_distinguish_repeated_dst_hour(self):
        self.observation(
            at=datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
        )
        self.observation(
            at=datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
        )

        result = get_stock_price_history(self.stock)
        first, second = result["points"]

        self.assertEqual(
            first["display_timestamp"], "2026-11-01T01:30:00-04:00"
        )
        self.assertEqual(
            second["display_timestamp"], "2026-11-01T01:30:00-05:00"
        )
        self.assertEqual(
            result["display_data_as_of"], second["display_timestamp"]
        )
        self.assertEqual(result["timezone"], "America/New_York")
        self.assertEqual(result["timezone_label"], "ET")

    def test_invalid_limits_are_rejected(self):
        for limit in (True, 0, -1, 1001, "180", None):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    get_stock_price_history(self.stock, limit=limit)

    def test_repeated_reads_do_not_change_stored_records(self):
        self.observation()

        models = (
            PriceHistory,
            Stock,
            Order,
            CashTransaction,
            Portfolio,
        )
        before = {
            model._meta.label: list(
                model.objects.order_by("pk").values()
            )
            for model in models
        }

        get_stock_price_history(self.stock)
        get_stock_price_history(self.stock)

        after = {
            model._meta.label: list(
                model.objects.order_by("pk").values()
            )
            for model in models
        }
        self.assertEqual(after, before)