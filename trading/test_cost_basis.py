from decimal import Decimal
from unittest.mock import patch
from importlib import import_module
from types import SimpleNamespace
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.apps import apps
from django.db import connection

from market.models import Stock
from accounts.services import deposit_cash, withdraw_cash

from .queries import get_portfolio_summary
from .models import Holding, Portfolio
from .services import (
    cancel_pending_order,
    place_buy_order,
    place_sell_order,
    process_pending_orders,
)


class CostBasisTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="basis_customer"
        )
        self.portfolio = Portfolio.objects.create(user=self.user)
        self.stock = Stock.objects.create(
            symbol="BASIS",
            company_name="Basis Test",
            current_price=Decimal("10.00"),
            is_active=True,
        )

    def set_price(self, price):
        Stock.objects.filter(pk=self.stock.pk).update(
            current_price=Decimal(price)
        )

    def holding(self):
        return Holding.objects.get(
            portfolio=self.portfolio,
            stock=self.stock,
        )

    def buy(self, quantity, *, market_open=True):
        with patch(
            "trading.services.is_market_open",
            return_value=market_open,
        ):
            return place_buy_order(
                self.user, self.stock.pk, quantity
            )

    def sell(self, quantity, *, market_open=True):
        with patch(
            "trading.services.is_market_open",
            return_value=market_open,
        ):
            return place_sell_order(
                self.user, self.stock.pk, quantity
            )

    def process(self):
        with patch(
            "trading.services.is_market_open",
            return_value=True,
        ):
            return process_pending_orders(self.user)

    def test_varied_buys_partial_sale_and_reopening(self):
        self.buy(10)
        self.set_price("20.00")
        self.buy(10)

        holding = self.holding()
        self.assertEqual(holding.quantity, 20)
        self.assertEqual(holding.cost_basis, Decimal("300.00"))

        sale = self.sell(5)
        sale.refresh_from_db()
        holding = self.holding()

        self.assertEqual(sale.cost_basis_sold, Decimal("75.00"))
        self.assertEqual(holding.quantity, 15)
        self.assertEqual(holding.cost_basis, Decimal("225.00"))
        self.assertEqual(
            sale.execution_price * sale.quantity - sale.cost_basis_sold,
            Decimal("25.00"),
        )

        final_sale = self.sell(15)
        final_sale.refresh_from_db()
        self.assertEqual(
            final_sale.cost_basis_sold, Decimal("225.00")
        )
        self.assertEqual(self.holding().quantity, 0)
        self.assertEqual(self.holding().cost_basis, Decimal("0.00"))

        self.set_price("7.00")
        self.buy(2)
        self.assertEqual(self.holding().cost_basis, Decimal("14.00"))

    def test_partial_sale_rounding_and_final_remainder(self):
        self.buy(1)
        self.set_price("10.01")
        self.buy(2)

        allocations = []
        for _ in range(3):
            sale = self.sell(1)
            sale.refresh_from_db()
            allocations.append(sale.cost_basis_sold)

        self.assertEqual(
            allocations,
            [
                Decimal("10.01"),
                Decimal("10.01"),
                Decimal("10.00"),
            ],
        )
        self.assertEqual(sum(allocations), Decimal("30.02"))
        self.assertEqual(self.holding().cost_basis, Decimal("0.00"))

    def test_pending_buy_uses_execution_price(self):
        self.buy(2)
        pending = self.buy(3, market_open=False)

        self.assertEqual(self.holding().quantity, 2)
        self.assertEqual(self.holding().cost_basis, Decimal("20.00"))

        self.set_price("8.00")
        self.process()
        pending.refresh_from_db()

        self.assertEqual(pending.status, "EXECUTED")
        self.assertEqual(pending.execution_price, Decimal("8.00"))
        self.assertEqual(self.holding().quantity, 5)
        self.assertEqual(self.holding().cost_basis, Decimal("44.00"))

    def test_pending_sale_and_cancellation_preserve_basis(self):
        self.buy(10)
        cancelled = self.sell(3, market_open=False)

        self.assertEqual(self.holding().cost_basis, Decimal("100.00"))
        self.assertEqual(self.holding().reserved_quantity, 3)
        self.assertIsNone(cancelled.cost_basis_sold)

        cancel_pending_order(self.user, cancelled.pk)
        cancelled.refresh_from_db()

        self.assertIsNone(cancelled.cost_basis_sold)
        self.assertEqual(self.holding().reserved_quantity, 0)
        self.assertEqual(self.holding().cost_basis, Decimal("100.00"))

        pending = self.sell(4, market_open=False)
        self.set_price("12.00")
        self.process()
        pending.refresh_from_db()

        self.assertEqual(pending.status, "EXECUTED")
        self.assertEqual(pending.cost_basis_sold, Decimal("40.00"))
        self.assertEqual(self.holding().quantity, 6)
        self.assertEqual(self.holding().reserved_quantity, 0)
        self.assertEqual(self.holding().cost_basis, Decimal("60.00"))

    def test_unknown_basis_stays_unknown_until_position_closes(self):
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            quantity=5,
            cost_basis=None,
        )

        self.buy(2)
        self.assertIsNone(self.holding().cost_basis)

        partial_sale = self.sell(3)
        partial_sale.refresh_from_db()
        self.assertIsNone(partial_sale.cost_basis_sold)
        self.assertIsNone(self.holding().cost_basis)

        final_sale = self.sell(4)
        final_sale.refresh_from_db()
        self.assertIsNone(final_sale.cost_basis_sold)
        self.assertEqual(self.holding().quantity, 0)
        self.assertEqual(self.holding().cost_basis, Decimal("0.00"))

        self.buy(1)
        self.assertEqual(self.holding().cost_basis, Decimal("10.00"))
    def run_backfill(self):
        migration = import_module(
            "trading.migrations.0003_backfill_cost_basis"
        )
        migration.backfill_cost_basis(
            apps,
            SimpleNamespace(connection=connection),
        )

    def clear_basis(self):
        Holding.objects.filter(
            portfolio=self.portfolio
        ).update(cost_basis=None)
        self.portfolio.orders.update(cost_basis_sold=None)

    def test_backfill_reconstructs_partial_sale(self):
        self.buy(10)
        self.set_price("20.00")
        self.buy(10)
        sale = self.sell(5)

        self.clear_basis()
        self.run_backfill()
        sale.refresh_from_db()

        self.assertEqual(self.holding().quantity, 15)
        self.assertEqual(self.holding().cost_basis, Decimal("225.00"))
        self.assertEqual(sale.cost_basis_sold, Decimal("75.00"))

    def test_backfill_leaves_unexplained_demo_holding_unknown(self):
        Holding.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            quantity=5,
            cost_basis=None,
        )

        self.run_backfill()

        self.assertIsNone(self.holding().cost_basis)

    def test_backfill_quantity_mismatch_saves_no_allocations(self):
        self.buy(10)
        sale = self.sell(5)
        self.clear_basis()

        Holding.objects.filter(
            portfolio=self.portfolio
        ).update(quantity=6)

        self.run_backfill()
        sale.refresh_from_db()

        self.assertIsNone(self.holding().cost_basis)
        self.assertIsNone(sale.cost_basis_sold)

    def test_backfill_rejects_sale_before_purchase(self):
        purchase = self.buy(10)
        sale = self.sell(5)
        self.clear_basis()

        # Force the sale first in the historical execution ordering.
        self.portfolio.orders.filter(pk=purchase.pk).update(
            executed_at=sale.executed_at
        )
        self.portfolio.orders.filter(pk=sale.pk).update(
            executed_at=purchase.executed_at - timedelta(seconds=1)
        )

        self.run_backfill()
        sale.refresh_from_db()

        self.assertIsNone(self.holding().cost_basis)
        self.assertIsNone(sale.cost_basis_sold)

    def test_backfill_reconstructs_closure_and_reopening(self):
        self.buy(3)
        sale = self.sell(3)
        self.set_price("7.00")
        self.buy(2)

        self.clear_basis()
        self.run_backfill()
        sale.refresh_from_db()

        self.assertEqual(sale.cost_basis_sold, Decimal("30.00"))
        self.assertEqual(self.holding().quantity, 2)
        self.assertEqual(self.holding().cost_basis, Decimal("14.00"))

    def test_summary_combines_realized_and_unrealized_gain(self):
        self.buy(10)
        self.set_price("20.00")
        self.buy(10)
        self.sell(5)

        result = get_portfolio_summary(self.user)

        # Bought for $300; sold five for $100 with $75 allocated basis.
        # Remaining shares are worth $300 with $225 remaining basis.
        self.assertEqual(
            result["realized_gain_loss"], Decimal("25.00")
        )
        self.assertEqual(
            result["unrealized_gain_loss"], Decimal("75.00")
        )
        self.assertEqual(
            result["overall_gain_loss"], Decimal("100.00")
        )
        self.assertFalse(result["has_unknown_realized_basis"])
        self.assertEqual(
            result["total_account_value"], Decimal("25100.00")
        )

    def test_funding_changes_do_not_change_investment_gain(self):
        self.buy(10)
        self.set_price("12.00")
        self.sell(4)

        before = get_portfolio_summary(self.user)
        deposit_cash(self.user, Decimal("500.00"))
        withdraw_cash(self.user, Decimal("200.00"))
        after = get_portfolio_summary(self.user)

        self.assertEqual(
            after["total_account_value"],
            before["total_account_value"] + Decimal("300.00"),
        )
        for field in (
            "realized_gain_loss",
            "unrealized_gain_loss",
            "overall_gain_loss",
        ):
            self.assertEqual(after[field], before[field])

        self.assertEqual(
            after["overall_gain_loss"], Decimal("20.00")
        )

    def test_unknown_historical_sale_withholds_overall_gain(self):
        self.buy(5)
        sale = self.sell(5)
        self.portfolio.orders.filter(pk=sale.pk).update(
            cost_basis_sold=None
        )

        # A reopened position has known basis, but the old sale does not.
        self.buy(2)
        result = get_portfolio_summary(self.user)

        self.assertFalse(result["has_unknown_cost_basis"])
        self.assertTrue(result["has_unknown_realized_basis"])
        self.assertIsNone(result["realized_gain_loss"])
        self.assertIsNone(result["overall_gain_loss"])
        self.assertEqual(
            result["unrealized_gain_loss"], Decimal("0.00")
        )

    def test_pending_and_cancelled_sales_do_not_count_as_realized(self):
        self.buy(10)
        self.set_price("12.00")
        cancelled = self.sell(2, market_open=False)
        cancel_pending_order(self.user, cancelled.pk)
        self.sell(3, market_open=False)

        result = get_portfolio_summary(self.user)

        self.assertEqual(
            result["realized_gain_loss"], Decimal("0.00")
        )
        self.assertEqual(
            result["unrealized_gain_loss"], Decimal("20.00")
        )
        self.assertEqual(
            result["overall_gain_loss"], Decimal("20.00")
        )
        self.assertFalse(result["has_unknown_realized_basis"])