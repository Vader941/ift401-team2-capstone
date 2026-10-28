from datetime import time
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase

from market.models import MarketSchedule
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal

from market.models import MarketException, Stock, StockDailyStatistic
from market.schedule import get_market_schedule
from market.services import (
    is_market_open,
    market_date_for,
    update_stock_price,
)
from market.runner import run_market_cycle
from trading.models import Order, Portfolio
from trading.models import CashTransaction, Holding
from trading.services import place_buy_order, process_pending_orders

class MarketScheduleTests(TestCase):
    def test_defaults_preserve_existing_market_schedule(self):
        schedule = MarketSchedule()
        schedule.full_clean()
        schedule.save()

        self.assertEqual(schedule.pk, 1)
        self.assertEqual(schedule.opening_time, time(9, 30))
        self.assertEqual(schedule.closing_time, time(16, 0))
        self.assertEqual(schedule.timezone_name, "America/New_York")
        self.assertTrue(all((
            schedule.monday,
            schedule.tuesday,
            schedule.wednesday,
            schedule.thursday,
            schedule.friday,
        )))

    def test_invalid_timezones_are_rejected(self):
        for name in ("Not/A_Timezone", "", "/etc/localtime", "../UTC"):
            with self.subTest(timezone_name=name):
                schedule = MarketSchedule(timezone_name=name)
                with self.assertRaises(ValidationError) as caught:
                    schedule.full_clean()
                self.assertIn(
                    "timezone_name", caught.exception.message_dict
                )

    def test_valid_alternative_timezone_is_accepted(self):
        schedule = MarketSchedule(timezone_name="America/Chicago")
        schedule.full_clean()

    def test_equal_or_overnight_hours_are_rejected(self):
        for closing in (time(9, 30), time(8, 0)):
            with self.subTest(closing_time=closing):
                schedule = MarketSchedule(
                    opening_time=time(9, 30),
                    closing_time=closing,
                )
                with self.assertRaises(ValidationError) as caught:
                    schedule.full_clean()
                self.assertIn(
                    "closing_time", caught.exception.message_dict
                )

    def test_at_least_one_weekday_is_required(self):
        schedule = MarketSchedule(
            monday=False,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
        )
        with self.assertRaises(ValidationError):
            schedule.full_clean()

        schedule.wednesday = True
        schedule.full_clean()

    def test_database_rejects_a_second_schedule_id(self):
        MarketSchedule.objects.create()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketSchedule.objects.create(id=2)

        self.assertEqual(MarketSchedule.objects.count(), 1)

    def test_database_rejects_invalid_hours_without_form_validation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketSchedule.objects.create(
                    opening_time=time(16, 0),
                    closing_time=time(9, 30),
                )

    def test_database_rejects_empty_weekdays_without_form_validation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketSchedule.objects.create(
                    monday=False,
                    tuesday=False,
                    wednesday=False,
                    thursday=False,
                    friday=False,
                )


class MarketScheduleAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="schedule_admin",
            email="schedule@example.com",
            password="schedule-test-only",
        )
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.superuser
        self.model_admin = admin.site._registry[MarketSchedule]

    def test_add_is_allowed_only_before_schedule_exists(self):
        self.assertTrue(
            self.model_admin.has_add_permission(self.request)
        )

        MarketSchedule.objects.create()

        self.assertFalse(
            self.model_admin.has_add_permission(self.request)
        )

    def test_schedule_deletion_is_disabled(self):
        schedule = MarketSchedule.objects.create()

        self.assertFalse(
            self.model_admin.has_delete_permission(
                self.request, schedule
            )
        )

    def test_admin_form_rejects_invalid_configuration(self):
        form_class = self.model_admin.get_form(self.request)
        form = form_class(data={
            "timezone_name": "Invalid/Timezone",
            "opening_time": "16:00:00",
            "closing_time": "09:30:00",
            "monday": True,
        })

        self.assertFalse(form.is_valid())
        self.assertIn("timezone_name", form.errors)
        self.assertIn("closing_time", form.errors)

    def test_staff_without_permission_cannot_add_schedule(self):
        User = get_user_model()
        self.request.user = User.objects.create_user(
            username="schedule_staff",
            is_staff=True,
        )

        self.assertFalse(
            self.model_admin.has_add_permission(self.request)
        )
class ConfiguredMarketScheduleTests(TestCase):
    def utc(self, year, month, day, hour, minute=0):
        return datetime(
            year, month, day, hour, minute,
            tzinfo=datetime_timezone.utc,
        )

    def test_missing_configuration_uses_defaults_without_creating_row(self):
        # October 26: Eastern daylight time, UTC minus four hours.
        self.assertFalse(
            is_market_open(self.utc(2026, 10, 26, 13, 29))
        )
        self.assertTrue(
            is_market_open(self.utc(2026, 10, 26, 13, 30))
        )
        self.assertTrue(
            is_market_open(self.utc(2026, 10, 26, 19, 59))
        )
        self.assertFalse(
            is_market_open(self.utc(2026, 10, 26, 20))
        )
        self.assertFalse(MarketSchedule.objects.exists())

    def test_custom_hours_and_disabled_weekday_are_used(self):
        MarketSchedule.objects.create(
            opening_time=time(10),
            closing_time=time(15),
            tuesday=False,
        )

        self.assertFalse(
            is_market_open(self.utc(2026, 10, 26, 13, 59))
        )
        self.assertTrue(
            is_market_open(self.utc(2026, 10, 26, 14))
        )
        self.assertFalse(
            is_market_open(self.utc(2026, 10, 26, 19))
        )
        self.assertFalse(
            is_market_open(self.utc(2026, 10, 27, 15))
        )

    def test_date_exceptions_override_regular_hours(self):
        at = self.utc(2026, 10, 26, 14)
        MarketSchedule.objects.create()
        exception = MarketException.objects.create(
            date=at.date(),
            is_closed=True,
        )
        self.assertFalse(is_market_open(at))

        exception.is_closed = False
        exception.opens_at = time(11)
        exception.closes_at = time(13)
        exception.save()

        self.assertFalse(is_market_open(at))
        self.assertTrue(
            is_market_open(self.utc(2026, 10, 26, 15))
        )
        self.assertFalse(
            is_market_open(self.utc(2026, 10, 26, 17))
        )

    def test_exceptions_cannot_open_weekends_or_disabled_weekdays(self):
        MarketSchedule.objects.create(monday=False)

        for day in (25, 26):  # Sunday and disabled Monday.
            with self.subTest(day=day):
                at = self.utc(2026, 10, day, 15)
                MarketException.objects.create(
                    date=at.date(),
                    is_closed=False,
                    opens_at=time(9),
                    closes_at=time(17),
                )
                self.assertFalse(is_market_open(at))

    def test_timezone_controls_hours_and_market_date(self):
        MarketSchedule.objects.create(
            timezone_name="America/Chicago"
        )

        self.assertFalse(
            is_market_open(self.utc(2026, 10, 26, 13, 30))
        )
        self.assertTrue(
            is_market_open(self.utc(2026, 10, 26, 14, 30))
        )
        self.assertEqual(
            market_date_for(self.utc(2026, 10, 26, 2)).isoformat(),
            "2026-10-25",
        )

    def test_daylight_saving_changes_utc_opening_time(self):
        MarketSchedule.objects.create()

        # Friday before and Monday after each 2026 DST transition.
        for month, day, opening_hour in (
            (3, 6, 14),
            (3, 9, 13),
            (10, 30, 13),
            (11, 2, 14),
        ):
            with self.subTest(month=month, day=day):
                self.assertFalse(is_market_open(
                    self.utc(2026, month, day, opening_hour, 29)
                ))
                self.assertTrue(is_market_open(
                    self.utc(2026, month, day, opening_hour, 30)
                ))

    def test_snapshot_stays_fixed_and_next_lookup_sees_changes(self):
        schedule = MarketSchedule.objects.create()
        snapshot = get_market_schedule()
        at = self.utc(2026, 10, 26, 14)

        schedule.opening_time = time(11)
        schedule.save()

        self.assertTrue(is_market_open(at, schedule=snapshot))
        self.assertFalse(is_market_open(at))

    def test_prices_and_daily_dates_use_configured_timezone(self):
        MarketSchedule.objects.create(
            timezone_name="Asia/Tokyo",
            opening_time=time(8),
            closing_time=time(16),
        )
        stock = Stock.objects.create(
            symbol="TZTEST",
            company_name="Timezone Test Company",
            initial_price=Decimal("100.00"),
            current_price=Decimal("100.00"),
        )
        # Sunday in UTC, Monday morning in Tokyo.
        at = self.utc(2026, 10, 25, 23, 30)

        result = update_stock_price(
            stock,
            at=at,
            random_source=lambda low, high: Decimal("1.00"),
        )

        self.assertEqual(result, Decimal("101.00"))
        daily = StockDailyStatistic.objects.get(stock=stock)
        self.assertEqual(daily.market_date.isoformat(), "2026-10-26")
        self.assertEqual(daily.opening_price, Decimal("100.00"))
        self.assertEqual(daily.high_price, Decimal("101.00"))
        self.assertEqual(daily.low_price, Decimal("100.00"))
        self.assertEqual(stock.price_history.count(), 1)

    def test_closed_configuration_prevents_price_and_history_changes(self):
        MarketSchedule.objects.create(monday=False)
        stock = Stock.objects.create(
            symbol="CLOSED",
            company_name="Closed Market Company",
            initial_price=Decimal("100.00"),
            current_price=Decimal("100.00"),
        )

        result = update_stock_price(
            stock,
            at=self.utc(2026, 10, 26, 15),
            random_source=lambda low, high: Decimal("1.00"),
        )

        self.assertEqual(result, Decimal("100.00"))
        stock.refresh_from_db()
        self.assertEqual(stock.current_price, Decimal("100.00"))
        self.assertFalse(stock.price_history.exists())
        self.assertFalse(stock.daily_statistics.exists())

    def test_naive_datetimes_are_rejected(self):
        at = datetime(2026, 10, 26, 10)

        for helper in (is_market_open, market_date_for):
            with self.subTest(helper=helper.__name__):
                with self.assertRaises(ValueError):
                    helper(at)

class ConfiguredMarketWorkerTests(TestCase):
    def setUp(self):
        self.at = datetime(
            2026, 10, 26, 14,
            tzinfo=datetime_timezone.utc,
        )
        self.schedule = MarketSchedule.objects.create()
        self.stock = Stock.objects.create(
            symbol="WORK",
            company_name="Worker Test Company",
            initial_price=Decimal("100.00"),
            current_price=Decimal("100.00"),
        )

    def test_prices_and_pending_orders_receive_same_snapshot_and_time(self):
        user = get_user_model().objects.create_user(
            username="worker_schedule_customer"
        )
        portfolio = Portfolio.objects.create(
            user=user,
            reserved_cash=Decimal("100.00"),
        )
        Order.objects.create(
            portfolio=portfolio,
            stock=self.stock,
            side=Order.Side.BUY,
            status=Order.Status.PENDING,
            quantity=1,
            submission_price=Decimal("100.00"),
            reserved_cash=Decimal("100.00"),
        )

        with (
            patch("market.runner.timezone.now", return_value=self.at),
            patch(
                "market.runner.update_stock_price",
                return_value=Decimal("100.00"),
            ) as update_price,
            patch("market.runner.process_pending_orders") as process_orders,
        ):
            result = run_market_cycle()

        self.assertTrue(result["market_open"])
        self.assertEqual(result["stocks_checked"], 1)
        self.assertEqual(result["portfolios_processed"], 1)
        update_price.assert_called_once()
        process_orders.assert_called_once()

        price_kwargs = update_price.call_args.kwargs
        order_kwargs = process_orders.call_args.kwargs

        self.assertEqual(price_kwargs["at"], self.at)
        self.assertEqual(order_kwargs["at"], self.at)
        self.assertIs(
            price_kwargs["schedule"], order_kwargs["schedule"]
        )
        self.assertEqual(
            process_orders.call_args.args[0].pk, user.pk
        )

    def test_midcycle_edit_applies_on_next_cycle(self):
        Stock.objects.create(
            symbol="WORKTWO",
            company_name="Second Worker Company",
            initial_price=Decimal("50.00"),
            current_price=Decimal("50.00"),
        )
        snapshots = []

        def update_price(stock, *, at, schedule):
            snapshots.append(schedule)
            # An admin disables Monday after the cycle has started.
            MarketSchedule.objects.filter(pk=1).update(monday=False)
            self.assertTrue(
                is_market_open(at, schedule=schedule)
            )
            return stock.current_price

        with (
            patch("market.runner.timezone.now", return_value=self.at),
            patch(
                "market.runner.update_stock_price",
                side_effect=update_price,
            ) as update_mock,
        ):
            first = run_market_cycle()
            second = run_market_cycle()

        self.assertTrue(first["market_open"])
        self.assertEqual(first["stocks_checked"], 2)
        self.assertEqual(update_mock.call_count, 2)
        self.assertIs(snapshots[0], snapshots[1])
        self.assertFalse(second["market_open"])
        self.assertEqual(second["stocks_checked"], 0)

    def test_closed_cycle_skips_prices_and_pending_processing(self):
        self.schedule.monday = False
        self.schedule.save()

        with (
            patch("market.runner.timezone.now", return_value=self.at),
            patch("market.runner.update_stock_price") as update_price,
            patch("market.runner.process_pending_orders") as process_orders,
        ):
            result = run_market_cycle()

        self.assertFalse(result["market_open"])
        update_price.assert_not_called()
        process_orders.assert_not_called()
class ConfiguredPendingOrderTests(TestCase):
    def setUp(self):
        self.at = datetime(
            2026, 10, 26, 14,
            tzinfo=datetime_timezone.utc,
        )
        self.schedule = MarketSchedule.objects.create(
            opening_time=time(11),
        )
        self.user = get_user_model().objects.create_user(
            username="configured_pending_customer"
        )
        self.portfolio = Portfolio.objects.create(user=self.user)
        self.stock = Stock.objects.create(
            symbol="PEND",
            company_name="Pending Schedule Company",
            initial_price=Decimal("100.00"),
            current_price=Decimal("100.00"),
        )

    def submit_closed_market_buy(self):
        # 14:00 UTC is 10:00 Eastern: before the configured 11:00 opening.
        with patch(
            "trading.services.timezone.now",
            return_value=self.at,
        ):
            return place_buy_order(self.user, self.stock.pk, 2)

    def test_schedule_change_allows_pending_execution_only_once(self):
        order = self.submit_closed_market_buy()
        self.assertEqual(order.status, Order.Status.PENDING)

        self.portfolio.refresh_from_db()
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("200.00")
        )
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("25000.00")
        )

        process_pending_orders(self.user, at=self.at)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertFalse(
            CashTransaction.objects.filter(order=order).exists()
        )

        self.schedule.opening_time = time(9, 30)
        self.schedule.save()

        process_pending_orders(self.user, at=self.at)
        process_pending_orders(self.user, at=self.at)

        order.refresh_from_db()
        self.portfolio.refresh_from_db()
        holding = Holding.objects.get(
            portfolio=self.portfolio,
            stock=self.stock,
        )
        ledger = CashTransaction.objects.get(order=order)

        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(order.executed_at, self.at)
        self.assertEqual(order.execution_price, Decimal("100.00"))
        self.assertEqual(order.reserved_cash, Decimal("0.00"))
        self.assertEqual(
            self.portfolio.reserved_cash, Decimal("0.00")
        )
        self.assertEqual(
            self.portfolio.cash_balance, Decimal("24800.00")
        )
        self.assertEqual(holding.quantity, 2)
        self.assertEqual(
            ledger.transaction_type,
            CashTransaction.TransactionType.PURCHASE,
        )
        self.assertEqual(ledger.amount, Decimal("-200.00"))
        self.assertEqual(ledger.balance_after, Decimal("24800.00"))

    def test_pending_execution_uses_supplied_cycle_snapshot(self):
        order = self.submit_closed_market_buy()

        self.schedule.opening_time = time(9, 30)
        self.schedule.save()
        snapshot = get_market_schedule()

        # A later admin edit closes Monday, but the started cycle
        # continues with its original configuration.
        self.schedule.monday = False
        self.schedule.save()

        self.assertFalse(is_market_open(self.at))
        self.assertTrue(
            is_market_open(self.at, schedule=snapshot)
        )

        process_pending_orders(
            self.user,
            at=self.at,
            schedule=snapshot,
        )

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(
            CashTransaction.objects.filter(order=order).count(),
            1,
        )