"""Reconciliation and regression scenarios for cash, shares, and history.

Each scenario performs real customer operations through the services, then
checks that every stored record agrees with every other one and with the
read-only portfolio/history helpers (see docs/portfolio-history.md):

- cash balance  = sum of all ledger amounts (the opening balance is a
  real INITIAL_BALANCE ledger record created at registration)
- last ledger balance_after = cash balance
- reserved cash = sum of pending buy reservations
- reserved shares = sum of pending sell reservations, per stock
- holding quantity = executed buys - executed sells, per stock
- every executed order has exactly one ledger entry; pending and
  cancelled orders have none
- summary: available cash, position values, available shares, and
  total account value follow the documented formulas
- history: one event per ledger entry plus one per cancelled order,
  unique event ids, no duplicated trades, no other customer's records

A single fake clock drives every timestamp (registration, ledger
created_at, market-hours checks), starting Monday 2026-10-19 08:00
America/New_York and only moving forward. Prices are set explicitly and the
random source is fixed, so every expected value is deterministic.
"""

import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db.models import Sum
from django.test import TestCase

from accounts.forms import CustomerRegistrationForm
from accounts.services import create_customer_account, deposit_cash, withdraw_cash
from market.models import Stock, StockDailyStatistic
from market.runner import run_market_cycle
from market.services import get_stock_statistics

from .models import CashTransaction, Holding, Order, Portfolio
from .queries import get_account_history, get_portfolio_summary
from .services import (
    CancellationError,
    cancel_pending_order,
    place_buy_order,
    place_sell_order,
    process_pending_orders,
)

NY = ZoneInfo("America/New_York")
OPEN = datetime(2026, 10, 19, 12, 0, tzinfo=NY)     # Monday, market open
CLOSED = datetime(2026, 10, 19, 18, 0, tzinfo=NY)   # Monday, after close
NEXT_OPEN = datetime(2026, 10, 20, 9, 30, tzinfo=NY)  # Tuesday opening bell
START = Decimal("25000.00")
CLOCK_START = datetime(2026, 10, 19, 8, 0, tzinfo=NY)  # before the bell


class FakeClock:
    """Monotonic clock: each read advances one millisecond."""

    def __init__(self, start):
        self.current = start

    def __call__(self):
        self.current += timedelta(milliseconds=1)
        return self.current

    def move_to(self, moment):
        assert moment >= self.current, "the test clock only moves forward"
        self.current = moment


def register(username):
    """Create a customer through the real registration path."""
    password = secrets.token_urlsafe(16) + "Aa1"
    form = CustomerRegistrationForm(
        data={
            "first_name": "Test",
            "last_name": username.title(),
            "username": username,
            "email": f"{username}@example.com",
            "password1": password,
            "password2": password,
        }
    )
    assert form.is_valid(), form.errors
    return create_customer_account(form)


class ReconciliationMixin:
    def start_clock(self):
        self.clock = FakeClock(CLOCK_START)
        clock_patch = patch("django.utils.timezone.now", self.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def at(self, moment):
        if moment > self.clock.current:
            self.clock.move_to(moment)

    def buy(self, user, stock, quantity, moment=OPEN):
        self.at(moment)
        return place_buy_order(user, stock.pk, quantity)

    def sell(self, user, stock, quantity, moment=OPEN):
        self.at(moment)
        return place_sell_order(user, stock.pk, quantity)

    def process(self, user, moment=OPEN):
        self.at(moment)
        return process_pending_orders(user)

    def set_price(self, stock, price):
        Stock.objects.filter(pk=stock.pk).update(current_price=Decimal(price))

    def assertReconciles(self, user):
        """Check every cross-record invariant for one customer."""
        portfolio = Portfolio.objects.get(user=user)
        ledger = CashTransaction.objects.filter(portfolio=portfolio)
        orders = Order.objects.filter(portfolio=portfolio)

        # Cash: the ledger explains the balance exactly.
        ledger_total = ledger.aggregate(total=Sum("amount"))["total"]
        self.assertEqual(portfolio.cash_balance, ledger_total)
        last = ledger.order_by("-created_at", "-pk").first()
        self.assertEqual(portfolio.cash_balance, last.balance_after)

        # Reserved cash: exactly the pending buy reservations.
        pending_buys = orders.filter(
            status=Order.Status.PENDING, side=Order.Side.BUY
        )
        reserved = pending_buys.aggregate(total=Sum("reserved_cash"))["total"]
        self.assertEqual(portfolio.reserved_cash, reserved or Decimal("0.00"))

        # Shares: executed buys minus executed sells; reserved = pending sells.
        for holding in Holding.objects.filter(portfolio=portfolio):
            executed = orders.filter(
                stock=holding.stock, status=Order.Status.EXECUTED
            )
            bought = executed.filter(side=Order.Side.BUY).aggregate(
                total=Sum("quantity")
            )["total"] or 0
            sold = executed.filter(side=Order.Side.SELL).aggregate(
                total=Sum("quantity")
            )["total"] or 0
            self.assertEqual(holding.quantity, bought - sold, holding.stock.symbol)
            pending_sold = orders.filter(
                stock=holding.stock,
                status=Order.Status.PENDING,
                side=Order.Side.SELL,
            ).aggregate(total=Sum("reserved_shares"))["total"] or 0
            self.assertEqual(holding.reserved_quantity, pending_sold)

        # Ledger <-> orders: one entry per executed order, none otherwise.
        for order in orders:
            entries = ledger.filter(order=order).count()
            expected = 1 if order.status == Order.Status.EXECUTED else 0
            self.assertEqual(entries, expected, f"order {order.pk} {order.status}")
            if order.status != Order.Status.PENDING:
                self.assertEqual(order.reserved_cash, Decimal("0.00"))
                self.assertEqual(order.reserved_shares, 0)

        # Summary helper follows the documented formulas.
        summary = get_portfolio_summary(user)
        self.assertTrue(summary["has_portfolio"])
        self.assertEqual(summary["cash_balance"], portfolio.cash_balance)
        self.assertEqual(summary["reserved_cash"], portfolio.reserved_cash)
        self.assertEqual(
            summary["available_cash"],
            portfolio.cash_balance - portfolio.reserved_cash,
        )
        holdings_value = Decimal("0.00")
        for item in summary["holdings"]:
            holding = Holding.objects.get(portfolio=portfolio, stock_id=item["stock_id"])
            price = Stock.objects.get(pk=item["stock_id"]).current_price
            self.assertEqual(item["quantity"], holding.quantity)
            self.assertEqual(
                item["available_quantity"],
                holding.quantity - holding.reserved_quantity,
            )
            self.assertEqual(item["position_value"], price * holding.quantity)
            holdings_value += item["position_value"]
        self.assertEqual(summary["holdings_value"], holdings_value)
        self.assertEqual(
            summary["total_account_value"],
            portfolio.cash_balance + holdings_value,
        )

        # History helper: every source record exactly once, nothing else.
        events = list(get_account_history(user, per_page=1000))
        cancelled = orders.filter(status=Order.Status.CANCELLED)
        self.assertEqual(len(events), ledger.count() + cancelled.count())
        ids = [event["event_id"] for event in events]
        self.assertEqual(len(ids), len(set(ids)), "duplicate history events")
        self.assertEqual(
            set(ids),
            {f"cash:{pk}" for pk in ledger.values_list("pk", flat=True)}
            | {f"cancelled_order:{pk}" for pk in cancelled.values_list("pk", flat=True)},
        )
        trade_events = [e for e in events if e["event_type"] in ("PURCHASE", "SALE")]
        trade_orders = [e["order_id"] for e in trade_events]
        self.assertEqual(len(trade_orders), len(set(trade_orders)), "trade shown twice")
        self.assertEqual(
            set(trade_orders),
            set(orders.filter(status=Order.Status.EXECUTED).values_list("pk", flat=True)),
        )
        for event in events:
            if event["event_type"] == "CANCELLATION":
                self.assertIsNone(event["amount"])
                self.assertIsNone(event["balance_after"])
        return summary, events


class CashAndTradeScenarioTests(ReconciliationMixin, TestCase):
    def setUp(self):
        price_patch = patch("market.services.random.uniform", return_value=0)
        price_patch.start()
        self.addCleanup(price_patch.stop)
        self.start_clock()
        self.user = register("alice")
        self.stock = Stock.objects.create(
            symbol="ACME",
            company_name="Acme Corp",
            initial_price=Decimal("25.00"),
            share_volume=1_000_000,
        )

    def portfolio(self):
        return Portfolio.objects.get(user=self.user)

    def holding(self):
        return Holding.objects.get(portfolio__user=self.user, stock=self.stock)

    def test_new_account_is_empty_and_reconciles(self):
        summary, events = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], START)
        self.assertEqual(summary["holdings"], [])
        self.assertEqual(summary["holdings_value"], Decimal("0.00"))
        self.assertEqual(summary["total_account_value"], START)
        self.assertEqual([e["event_type"] for e in events], ["INITIAL_BALANCE"])

    def test_deposit_and_withdrawal(self):
        deposit_cash(self.user, Decimal("500.00"))
        withdraw_cash(self.user, Decimal("200.00"))
        summary, events = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("25300.00"))
        self.assertEqual(
            sorted(e["event_type"] for e in events),
            ["DEPOSIT", "INITIAL_BALANCE", "WITHDRAWAL"],
        )

    def test_executed_buy(self):
        order = self.buy(self.user, self.stock, 10)
        self.assertEqual(order.status, Order.Status.EXECUTED)
        summary, events = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("24750.00"))
        self.assertEqual(self.holding().quantity, 10)
        self.assertEqual(summary["holdings_value"], Decimal("250.00"))
        self.assertEqual(summary["total_account_value"], START)
        purchase = [e for e in events if e["event_type"] == "PURCHASE"]
        self.assertEqual(len(purchase), 1)
        self.assertEqual(purchase[0]["amount"], Decimal("-250.00"))
        self.assertEqual(purchase[0]["execution_price"], Decimal("25.00"))
        self.assertEqual(purchase[0]["quantity"], 10)
        self.assertEqual(purchase[0]["symbol"], "ACME")

    def test_partial_sell(self):
        self.buy(self.user, self.stock, 10)
        self.set_price(self.stock, "30.00")
        order = self.sell(self.user, self.stock, 4)
        self.assertEqual(order.status, Order.Status.EXECUTED)
        summary, _ = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("24870.00"))  # -250 +120
        self.assertEqual(self.holding().quantity, 6)
        self.assertEqual(summary["holdings_value"], Decimal("180.00"))
        self.assertEqual(summary["total_account_value"], Decimal("25050.00"))

    def test_pending_buy_reserves_cash_only(self):
        order = self.buy(self.user, self.stock, 10, moment=CLOSED)
        self.assertEqual(order.status, Order.Status.PENDING)
        summary, events = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], START)
        self.assertEqual(summary["reserved_cash"], Decimal("250.00"))
        self.assertEqual(summary["available_cash"], Decimal("24750.00"))
        self.assertEqual(summary["total_account_value"], START)
        self.assertFalse(Holding.objects.filter(portfolio__user=self.user).exists())
        self.assertEqual(len(events), 1)  # pending orders are not history events

    def test_pending_sell_reserves_shares_only(self):
        self.buy(self.user, self.stock, 10)
        order = self.sell(self.user, self.stock, 4, moment=CLOSED)
        self.assertEqual(order.status, Order.Status.PENDING)
        summary, _ = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("24750.00"))
        item = summary["holdings"][0]
        self.assertEqual(item["quantity"], 10)
        self.assertEqual(item["reserved_quantity"], 4)
        self.assertEqual(item["available_quantity"], 6)
        self.assertEqual(item["position_value"], Decimal("250.00"))

    def test_cancel_pending_buy_releases_cash_without_ledger_entry(self):
        order = self.buy(self.user, self.stock, 10, moment=CLOSED)
        cancel_pending_order(self.user, order.pk)
        summary, events = self.assertReconciles(self.user)
        self.assertEqual(summary["reserved_cash"], Decimal("0.00"))
        self.assertEqual(summary["available_cash"], START)
        self.assertEqual(CashTransaction.objects.filter(order=order).count(), 0)
        cancellations = [e for e in events if e["event_type"] == "CANCELLATION"]
        self.assertEqual(len(cancellations), 1)
        self.assertEqual(cancellations[0]["order_id"], order.pk)

    def test_cancel_pending_sell_releases_shares_without_ledger_entry(self):
        self.buy(self.user, self.stock, 10)
        order = self.sell(self.user, self.stock, 4, moment=CLOSED)
        cancel_pending_order(self.user, order.pk)
        summary, events = self.assertReconciles(self.user)
        self.assertEqual(self.holding().reserved_quantity, 0)
        self.assertEqual(summary["holdings"][0]["available_quantity"], 10)
        self.assertEqual(summary["cash_balance"], Decimal("24750.00"))
        self.assertEqual(
            sorted(e["event_type"] for e in events),
            ["CANCELLATION", "INITIAL_BALANCE", "PURCHASE"],
        )

    def test_pending_buy_executes_later_at_current_price(self):
        order = self.buy(self.user, self.stock, 10, moment=CLOSED)  # reserves 250
        self.set_price(self.stock, "26.00")
        self.process(self.user, moment=NEXT_OPEN)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(order.execution_price, Decimal("26.00"))
        summary, _ = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("24740.00"))
        self.assertEqual(summary["reserved_cash"], Decimal("0.00"))
        self.assertEqual(self.holding().quantity, 10)

    def test_pending_sell_executes_later_at_current_price(self):
        self.buy(self.user, self.stock, 10)
        order = self.sell(self.user, self.stock, 4, moment=CLOSED)
        self.set_price(self.stock, "24.00")
        self.process(self.user, moment=NEXT_OPEN)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        summary, _ = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("24846.00"))  # -250 +96
        self.assertEqual(self.holding().quantity, 6)
        self.assertEqual(self.holding().reserved_quantity, 0)

    def test_repeated_processing_does_not_execute_twice(self):
        order = self.buy(self.user, self.stock, 10, moment=CLOSED)
        self.process(self.user, moment=NEXT_OPEN)
        self.process(self.user, moment=NEXT_OPEN + timedelta(minutes=1))
        self.process(self.user, moment=NEXT_OPEN + timedelta(minutes=2))
        self.assertEqual(CashTransaction.objects.filter(order=order).count(), 1)
        summary, _ = self.assertReconciles(self.user)
        self.assertEqual(self.holding().quantity, 10)
        self.assertEqual(summary["cash_balance"], Decimal("24750.00"))

    def test_cancel_after_execution_is_rejected_and_changes_nothing(self):
        order = self.buy(self.user, self.stock, 10, moment=CLOSED)
        self.process(self.user, moment=NEXT_OPEN)
        before = self.portfolio().cash_balance
        with self.assertRaises(CancellationError):
            cancel_pending_order(self.user, order.pk)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(self.portfolio().cash_balance, before)
        self.assertReconciles(self.user)

    def test_insufficient_cash_at_execution_cancels_and_releases(self):
        withdraw_cash(self.user, Decimal("24700.00"))  # 300.00 left
        order = self.buy(self.user, self.stock, 10, moment=CLOSED)  # reserves 250
        self.set_price(self.stock, "31.00")  # now costs 310 > 300
        self.process(self.user, moment=NEXT_OPEN)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertTrue(order.cancellation_reason)
        summary, events = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("300.00"))
        self.assertEqual(summary["reserved_cash"], Decimal("0.00"))
        self.assertIn("CANCELLATION", [e["event_type"] for e in events])

    def test_inactive_holding_stays_in_account_value(self):
        self.buy(self.user, self.stock, 10)
        Stock.objects.filter(pk=self.stock.pk).update(is_active=False)
        summary, _ = self.assertReconciles(self.user)
        self.assertEqual(len(summary["holdings"]), 1)
        self.assertFalse(summary["holdings"][0]["is_active"])
        self.assertEqual(summary["total_account_value"], START)

    def test_pending_order_on_deactivated_stock_is_cancelled_and_released(self):
        self.buy(self.user, self.stock, 10)
        sell = self.sell(self.user, self.stock, 4, moment=CLOSED)
        Stock.objects.filter(pk=self.stock.pk).update(is_active=False)
        self.process(self.user, moment=NEXT_OPEN)
        sell.refresh_from_db()
        self.assertEqual(sell.status, Order.Status.CANCELLED)
        self.assertEqual(self.holding().reserved_quantity, 0)
        self.assertReconciles(self.user)

    def test_worked_example_in_verification_report(self):
        """The exact values published in docs/data-verification-report.md."""
        deposit_cash(self.user, Decimal("500.00"))
        buy = self.buy(self.user, self.stock, 10)               # open market
        sell = self.sell(self.user, self.stock, 4, moment=CLOSED)  # pending

        summary, events = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("25250.00"))
        self.assertEqual(summary["reserved_cash"], Decimal("0.00"))
        self.assertEqual(summary["available_cash"], Decimal("25250.00"))
        self.assertEqual(summary["holdings_value"], Decimal("250.00"))
        self.assertEqual(summary["total_account_value"], Decimal("25500.00"))
        self.assertEqual(
            summary["holdings"],
            [{
                "stock_id": self.stock.pk,
                "symbol": "ACME",
                "company_name": "Acme Corp",
                "quantity": 10,
                "reserved_quantity": 4,
                "available_quantity": 6,
                "current_price": Decimal("25.00"),
                "position_value": Decimal("250.00"),
                "is_active": True,
            }],
        )
        self.assertEqual(
            [(e["event_type"], e["amount"], e["balance_after"]) for e in events],
            [
                ("PURCHASE", Decimal("-250.00"), Decimal("25250.00")),
                ("DEPOSIT", Decimal("500.00"), Decimal("25500.00")),
                ("INITIAL_BALANCE", Decimal("25000.00"), Decimal("25000.00")),
            ],
        )
        self.assertEqual(events[0]["order_id"], buy.pk)

        cancel_pending_order(self.user, sell.pk)
        _, events = self.assertReconciles(self.user)
        self.assertEqual(events[0]["event_type"], "CANCELLATION")
        self.assertEqual(events[0]["event_id"], f"cancelled_order:{sell.pk}")
        self.assertEqual(events[0]["quantity"], 4)
        self.assertIsNone(events[0]["amount"])
        self.assertEqual(events[0]["description"], "Cancelled by customer.")

    def test_long_history_pages_have_no_gaps_or_overlaps(self):
        for _ in range(12):
            deposit_cash(self.user, Decimal("10.00"))
            withdraw_cash(self.user, Decimal("5.00"))
        order = self.buy(self.user, self.stock, 1, moment=CLOSED)
        cancel_pending_order(self.user, order.pk)
        _, all_events = self.assertReconciles(self.user)
        self.assertEqual(len(all_events), 26)

        seen = []
        page = get_account_history(self.user, page=1, per_page=10)
        while True:
            seen.extend(e["event_id"] for e in page)
            if not page.has_next():
                break
            page = get_account_history(
                self.user, page=page.next_page_number(), per_page=10
            )
        self.assertEqual(seen, [e["event_id"] for e in all_events])
        self.assertEqual(
            seen,
            [e["event_id"] for e in get_account_history(self.user, per_page=1000)],
            "ordering must be repeatable",
        )


class TwoAccountIsolationTests(ReconciliationMixin, TestCase):
    def setUp(self):
        price_patch = patch("market.services.random.uniform", return_value=0)
        price_patch.start()
        self.addCleanup(price_patch.stop)
        self.start_clock()
        self.alice = register("alice")
        self.bob = register("bob")
        self.stock = Stock.objects.create(
            symbol="ACME", company_name="Acme Corp", initial_price=Decimal("25.00")
        )

    def test_each_customer_sees_and_changes_only_their_own_records(self):
        self.buy(self.alice, self.stock, 10)
        bob_pending = self.buy(self.bob, self.stock, 4, moment=CLOSED)
        deposit_cash(self.bob, Decimal("100.00"))

        alice_summary, alice_events = self.assertReconciles(self.alice)
        bob_summary, bob_events = self.assertReconciles(self.bob)

        self.assertEqual(alice_summary["cash_balance"], Decimal("24750.00"))
        self.assertEqual(alice_summary["reserved_cash"], Decimal("0.00"))
        self.assertEqual(bob_summary["cash_balance"], Decimal("25100.00"))
        self.assertEqual(bob_summary["reserved_cash"], Decimal("100.00"))
        self.assertEqual(bob_summary["holdings"], [])

        alice_ledger = {
            f"cash:{pk}"
            for pk in CashTransaction.objects.filter(
                portfolio__user=self.alice
            ).values_list("pk", flat=True)
        }
        self.assertTrue(
            all(e["event_id"] in alice_ledger for e in alice_events)
        )
        self.assertFalse(
            {e["event_id"] for e in alice_events}
            & {e["event_id"] for e in bob_events}
        )

        # Alice cannot cancel Bob's order; nothing changes.
        with self.assertRaises(CancellationError):
            cancel_pending_order(self.alice, bob_pending.pk)
        bob_pending.refresh_from_db()
        self.assertEqual(bob_pending.status, Order.Status.PENDING)

        # Processing Alice's account never touches Bob's pending order.
        self.process(self.alice, moment=NEXT_OPEN)
        bob_pending.refresh_from_db()
        self.assertEqual(bob_pending.status, Order.Status.PENDING)
        self.assertReconciles(self.bob)

    def test_missing_portfolio_does_not_leak_or_create(self):
        from django.contrib.auth import get_user_model

        staff = get_user_model().objects.create_user(username="staffonly")
        summary = get_portfolio_summary(staff)
        self.assertFalse(summary["has_portfolio"])
        self.assertIsNone(summary["cash_balance"])
        self.assertEqual(list(get_account_history(staff)), [])
        self.assertFalse(Portfolio.objects.filter(user=staff).exists())


class MarketCycleIntegrationTests(ReconciliationMixin, TestCase):
    """PR 17 statistics, PR 19 worker cycles, and PR 20 opening rule together."""

    def setUp(self):
        self.start_clock()
        self.user = register("carol")
        self.stock = Stock.objects.create(
            symbol="CYCL",
            company_name="Cycle Co",
            initial_price=Decimal("10.00"),
            share_volume=2_000_000,
        )

    def cycle(self, moment, percent):
        self.at(moment)
        with patch("market.services.random.uniform", return_value=float(percent)):
            return run_market_cycle()

    def test_cycles_build_statistics_and_execute_pending_orders(self):
        order = self.buy(self.user, self.stock, 100, moment=CLOSED)  # reserves 1000

        # Closed market: nothing moves, no statistics recorded.
        result = self.cycle(CLOSED + timedelta(minutes=5), "1.00")
        self.assertFalse(result["market_open"])
        self.assertFalse(StockDailyStatistic.objects.exists())

        # First open cycle: opening is the price before the first update
        # (10.00); the price moves to 10.10 and the pending buy executes.
        result = self.cycle(NEXT_OPEN, "1.00")
        self.assertEqual(result["prices_changed"], 1)
        self.assertEqual(result["portfolios_processed"], 1)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXECUTED)
        self.assertEqual(order.execution_price, Decimal("10.10"))

        # A no-change attempt keeps statistics and price unchanged.
        self.cycle(NEXT_OPEN + timedelta(seconds=61), "0.00")
        self.cycle(NEXT_OPEN + timedelta(seconds=122), "-1.00")  # 10.00 (rounded)

        self.stock.refresh_from_db()
        stats = get_stock_statistics(self.stock, at=NEXT_OPEN + timedelta(minutes=3))
        self.assertEqual(stats["opening_price"], Decimal("10.00"))
        self.assertEqual(stats["high_price"], Decimal("10.10"))
        self.assertEqual(stats["low_price"], Decimal("10.00"))
        self.assertEqual(stats["current_price"], self.stock.current_price)
        self.assertEqual(
            stats["market_capitalization"],
            Decimal(2_000_000) * self.stock.current_price,
        )

        summary, _ = self.assertReconciles(self.user)
        self.assertEqual(summary["cash_balance"], Decimal("23990.00"))  # -1010
        self.assertEqual(
            summary["holdings"][0]["current_price"], self.stock.current_price
        )

    def test_new_market_day_starts_new_statistics(self):
        self.cycle(OPEN, "1.00")          # Monday: open 10.00 -> 10.10
        self.cycle(NEXT_OPEN, "1.00")     # Tuesday: open 10.10 -> 10.20
        days = StockDailyStatistic.objects.filter(stock=self.stock).order_by("market_date")
        self.assertEqual([str(d.market_date) for d in days], ["2026-10-19", "2026-10-20"])
        self.assertEqual(days[0].opening_price, Decimal("10.00"))
        self.assertEqual(days[1].opening_price, Decimal("10.10"))
        self.assertEqual(days[1].high_price, Decimal("10.20"))

    def test_page_views_do_not_trigger_price_generation(self):
        self.at(OPEN)  # market open: a page-triggered update would show up
        self.client.force_login(self.user)
        with patch("market.services.update_stock_price") as update:
            self.client.get("/stocks/")
            self.client.get(f"/stocks/{self.stock.pk}/")
            self.client.get("/dashboard/")
        update.assert_not_called()
        self.assertFalse(StockDailyStatistic.objects.exists())
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.current_price, Decimal("10.00"))
        self.assertFalse(self.stock.price_history.exists())
