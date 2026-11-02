from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def backfill_cost_basis(apps, schema_editor):
    Holding = apps.get_model("trading", "Holding")
    Order = apps.get_model("trading", "Order")
    db = schema_editor.connection.alias

    holdings = Holding.objects.using(db)
    executed_orders = Order.objects.using(db).filter(status="EXECUTED")

    # Include closed positions whose Holding row may have been removed.
    pairs = set(
        holdings.values_list("portfolio_id", "stock_id")
    )
    pairs.update(
        executed_orders.values_list("portfolio_id", "stock_id")
    )

    for portfolio_id, stock_id in sorted(pairs):
        holding = holdings.filter(
            portfolio_id=portfolio_id,
            stock_id=stock_id,
        ).first()

        orders = list(
            executed_orders.filter(
                portfolio_id=portfolio_id,
                stock_id=stock_id,
            ).order_by("executed_at", "id")
        )

        quantity = 0
        basis = ZERO
        sale_allocations = []
        valid = True

        for order in orders:
            if (
                order.executed_at is None
                or order.execution_price is None
                or order.execution_price <= ZERO
                or order.quantity <= 0
            ):
                valid = False
                break

            if order.side == "BUY":
                basis += order.execution_price * order.quantity
                quantity += order.quantity

            elif order.side == "SELL":
                if order.quantity > quantity:
                    valid = False
                    break

                if order.quantity == quantity:
                    sold_basis = basis
                else:
                    sold_basis = (
                        basis * order.quantity / quantity
                    ).quantize(CENT, rounding=ROUND_HALF_UP)

                sale_allocations.append((order.pk, sold_basis))
                basis -= sold_basis
                quantity -= order.quantity

            else:
                valid = False
                break

        expected_quantity = holding.quantity if holding else 0

        # Do not persist a partial reconstruction or invent missing costs.
        if not valid or quantity != expected_quantity:
            continue

        if holding is not None:
            holdings.filter(pk=holding.pk).update(cost_basis=basis)

        for order_id, sold_basis in sale_allocations:
            Order.objects.using(db).filter(pk=order_id).update(
                cost_basis_sold=sold_basis
            )


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0002_holding_cost_basis_order_cost_basis_sold"),
    ]

    operations = [
        migrations.RunPython(
            backfill_cost_basis,
            reverse_code=migrations.RunPython.noop,
        ),
    ]